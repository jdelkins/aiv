from __future__ import annotations

import sys
import threading
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.markup import escape

from aiv.models import PipelineContext, SetModeCommand, InteractionMode, ShowCommand
from aiv.commands import (
    parse_command,
    run_command,
    cmd_intro,
    cmd_set_mode,
    apply_session_state,
    QuitPipeline,
    StopPipeline,
    get_interaction_count,
    print_info,
)
from aiv.completion import AivCompleter

kb = KeyBindings()


@kb.add("escape", "enter")
def _submit(event):
    text = event.app.current_buffer.text
    if text.strip():
        event.app.current_buffer.history.append_string(text)
    event.app.exit(result=text)


def _watch_conv_file(
    path,
    stop_event: threading.Event,
    app_ref: list,
    app_ref_lock: threading.Lock,
    file_changed: threading.Event,
    baseline: list,
    baseline_lock: threading.Lock,
    poll_interval: float = 1.0,
):
    """Signal external mtime changes, preserving any in-progress prompt text.

    The main thread updates baseline after commands so local writes are not
    mistaken for external changes.
    """
    try:
        last_mtime = path.stat().st_mtime
    except OSError:
        last_mtime = None

    while not stop_event.wait(poll_interval):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        with baseline_lock:
            forced = baseline[0]
        if forced is not None and mtime <= forced:
            last_mtime = mtime
            continue

        if last_mtime is not None and mtime != last_mtime:
            last_mtime = mtime
            file_changed.set()
            with app_ref_lock:
                app = app_ref[0] if app_ref else None
            if app is not None:
                try:
                    app.exit(result=app.current_buffer.text)
                except Exception:
                    pass
        else:
            last_mtime = mtime


def run_repl_loop(ctx: PipelineContext) -> None:
    # Reattach piped stdin to the controlling terminal for interactive input.
    if not sys.stdin.isatty():
        try:
            sys.stdin = open("/dev/tty", "r")
        except OSError:
            print_info(
                "[red]Cannot open /dev/tty — no terminal available for REPL.[/red]"
            )
            return

    ctx.interactive = True

    cmd_intro()
    if ctx.mode == InteractionMode.DEFAULT:
        cmd_set_mode(SetModeCommand(mode=InteractionMode.CHAT), ctx)

    pending_text = ""
    last_seen_count = get_interaction_count(ctx) or 0

    while True:
        history_file = ctx.conv_path.parent / ".aiv-history"
        session = PromptSession(
            history=FileHistory(str(history_file)),
            completer=AivCompleter(),
            complete_while_typing=False,
        )

        app_ref: list = []
        app_ref_lock = threading.Lock()
        file_changed = threading.Event()
        baseline: list = [None]
        baseline_lock = threading.Lock()

        stop_event = threading.Event()
        watcher = threading.Thread(
            target=_watch_conv_file,
            args=(
                ctx.conv_path,
                stop_event,
                app_ref,
                app_ref_lock,
                file_changed,
                baseline,
                baseline_lock,
            ),
            daemon=True,
        )
        watcher.start()

        try:
            while True:
                file_changed.clear()

                def _pre_run():
                    with app_ref_lock:
                        app_ref.clear()
                        app_ref.append(session.app)

                try:
                    text = session.prompt(
                        HTML("\n<ansicyan>aiv> </ansicyan>"),
                        multiline=True,
                        key_bindings=kb,
                        prompt_continuation="...  ",
                        default=pending_text,
                        pre_run=_pre_run,
                    )
                except (EOFError, KeyboardInterrupt):
                    print()
                    return
                finally:
                    with app_ref_lock:
                        app_ref.clear()

                if file_changed.is_set():
                    pending_text = text or ""
                    new_count = get_interaction_count(ctx)
                    if new_count is None:
                        print_info(
                            "[red]Conversation file is unreadable or malformed.[/red]"
                        )
                    else:
                        # Reload profile identity, implementation type, options,
                        # and all persisted overrides together. Never continue
                        # with stale settings if the selected profile or key
                        # source can no longer be resolved.
                        try:
                            apply_session_state(ctx)
                        except (OSError, ValueError) as e:
                            print_info(f"[red]{escape(str(e))}[/red]")
                            return

                        if new_count == 0 and last_seen_count > 0:
                            print_info(
                                "[yellow]Conversation was cleared externally.[/yellow]"
                            )
                        elif new_count < last_seen_count:
                            print_info(
                                f"[yellow]Conversation was modified externally "
                                f"({last_seen_count} → {new_count} interactions).[/yellow]"
                            )
                        elif new_count > last_seen_count:
                            try:
                                run_command(
                                    ShowCommand(args=f"{last_seen_count + 1}-"),
                                    ctx,
                                )
                            except (StopPipeline, QuitPipeline):
                                pass

                    if new_count is not None:
                        last_seen_count = new_count
                    continue

                pending_text = ""
                if not text.strip():
                    continue

                cmd = parse_command(text)
                try:
                    run_command(cmd, ctx)
                finally:
                    # Absorb local writes even when command execution raises.
                    last_seen_count = get_interaction_count(ctx) or 0
                    try:
                        with baseline_lock:
                            baseline[0] = ctx.conv_path.stat().st_mtime
                    except OSError:
                        pass

        except StopPipeline:
            # Restart prompt/history/watch state after a directory change.
            continue
        except QuitPipeline:
            return
        finally:
            stop_event.set()

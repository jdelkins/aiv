from __future__ import annotations

import sys
import threading
import time

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory

from aiv.conversation import get_conversation_file
from aiv.models import PipelineContext, SetModeCommand, InteractionMode, ShowCommand
from aiv.commands import (
    parse_command,
    run_command,
    cmd_intro,
    cmd_set_mode,
    QuitPipeline,
    StopPipeline,
    HistoryCommand,
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
    """Poll the conversation file's mtime on a background daemon thread.
    On change: set file_changed, then call app.exit() on the currently
    registered Application (if any). app.exit() is thread-safe in
    prompt_toolkit — it schedules the exit via the app's internal event loop.

    The main thread writes the post-command mtime into baseline so that file
    changes caused by a response are absorbed and never treated as external."""
    try:
        last_mtime = path.stat().st_mtime
    except OSError:
        last_mtime = None

    while not stop_event.is_set():
        time.sleep(poll_interval)
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue

        # If the main thread updated the baseline (e.g. after a response wrote
        # to the file), absorb up to that mtime and skip firing.
        with baseline_lock:
            forced = baseline[0]
        if forced is not None and mtime <= forced:
            last_mtime = mtime
            continue

        if last_mtime is not None and mtime != last_mtime:
            last_mtime = mtime
            # Signal before calling app.exit() so the main thread can reliably
            # distinguish a watcher-driven exit from a normal user submission.
            file_changed.set()
            with app_ref_lock:
                app = app_ref[0] if app_ref else None
            if app is not None:
                try:
                    # Pass the buffer text as the exit result so the main thread
                    # can stash it and re-populate the next prompt.
                    app.exit(result=app.current_buffer.text)
                except Exception:
                    pass
        else:
            last_mtime = mtime


def run_repl_loop(ctx: PipelineContext) -> None:
    # If stdin was a pipe (e.g. piped context via `echo foo | aiv -i -c -`),
    # prompt_toolkit would see EOF immediately and exit. Reattach stdin to the
    # terminal so the REPL is actually interactive.
    if not sys.stdin.isatty():
        try:
            sys.stdin = open("/dev/tty", "r")
        except OSError:
            from rich.console import Console

            Console().print(
                "[red]Cannot open /dev/tty — no terminal available for REPL.[/red]"
            )
            return

    # Mark context as interactive so cmd_reset/cmd_delete show confirmation prompts
    ctx.interactive = True

    cmd_intro()
    if ctx.mode == InteractionMode.DEFAULT:
        cmd_set_mode(SetModeCommand(mode=InteractionMode.CHAT), ctx)

    # Any text the user had typed mid-prompt when a file-change reload fires is
    # stashed here and re-injected as the default on the next prompt invocation.
    pending_text: str = ""

    last_seen_count: int = get_interaction_count(ctx) or 0

    while True:
        # Resolve history file alongside the conversation file's parent directory
        # so per-repo history stays with the repo, and global history stays global.
        history_file = ctx.conv_path.parent / ".aiv-history"
        session = PromptSession(
            history=FileHistory(str(history_file)),
            completer=AivCompleter(),
            complete_while_typing=False,  # Tab-triggered only; live completion is noisy
        )

        # app_ref holds the live Application so the watcher thread can call
        # app.exit() on it. A list is used as a mutable container so the
        # pre_run closure can update it without a nonlocal declaration.
        # The lock guards cross-thread reads and writes of app_ref.
        # file_changed lets the main thread distinguish a watcher-driven prompt
        # exit from a normal user submission.
        app_ref: list = []
        app_ref_lock = threading.Lock()
        file_changed = threading.Event()

        # baseline holds the mtime the main thread last wrote after a command
        # completed. The watcher absorbs any file change at or below this value
        # so that writes caused by a response never trigger a reload.
        baseline: list = [None]
        baseline_lock = threading.Lock()

        # One watcher per prompt session. stop_event is set in the finally block
        # so the daemon thread exits cleanly whenever we break out of the inner loop
        # (e.g. StopPipeline from a `cd` command) and a new session is created.
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
                # Reset the change flag at the top of each prompt iteration so a
                # change that was already handled doesn't re-trigger immediately.
                file_changed.clear()

                def _pre_run():
                    # pre_run is called by prompt_toolkit immediately before the
                    # prompt's event loop starts — the earliest point at which
                    # session.app is guaranteed to exist. Publish it into app_ref
                    # so the watcher thread can call app.exit() when needed.
                    with app_ref_lock:
                        app_ref.clear()
                        app_ref.append(session.app)

                try:
                    text = session.prompt(
                        HTML("<ansicyan>aiv> </ansicyan>"),
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
                    # Unregister the app immediately so the watcher cannot call
                    # exit() on a prompt that is no longer running.
                    with app_ref_lock:
                        app_ref.clear()

                if file_changed.is_set():
                    # The prompt was interrupted by an external change to the
                    # conversation file. Stash whatever the user had typed,
                    # display any new turns, then loop back so the prompt
                    # reappears with that text pre-populated.
                    pending_text = text or ""
                    new_count = get_interaction_count(ctx)
                    if new_count is None:
                        print_info(
                            "[red]Conversation file is unreadable or malformed.[/red]"
                        )
                    elif new_count == 0 and last_seen_count > 0:
                        print_info(
                            "[yellow]Conversation was cleared externally.[/yellow]"
                        )
                    elif new_count < last_seen_count:
                        print_info(
                            f"[yellow]Conversation was modified externally ({last_seen_count} → {new_count} interactions).[/yellow]"
                        )
                    elif new_count >= last_seen_count:
                        try:
                            run_command(
                                ShowCommand(
                                    args=f"{min(new_count, last_seen_count + 1)}-"
                                ),
                                ctx,
                            )
                        except (StopPipeline, QuitPipeline):
                            pass
                    if new_count is not None:
                        last_seen_count = new_count
                    continue

                # Normal submission — clear any stashed text.
                pending_text = ""

                if not text.strip():
                    continue

                cmd = parse_command(text)
                try:
                    run_command(cmd, ctx)
                finally:
                    # Re-baseline the watcher to the current mtime after every
                    # command — whether it succeeded or raised an exception —
                    # so that any writes the command made to the conversation
                    # file are not mistaken for external changes. The exception
                    # (StopPipeline, QuitPipeline, etc.) propagates naturally
                    # after the finally block completes.
                    try:
                        with baseline_lock:
                            baseline[0] = ctx.conv_path.stat().st_mtime
                    except OSError:
                        pass

                # StopPipeline and QuitPipeline raised by run_command bubble
                # through the finally above and are caught here.
                # This code is only reached on a clean (non-raising) return.
                # The explicit catches below are therefore unreachable for the
                # raising cases — the exceptions propagate to the outer loop.

        except StopPipeline:
            # StopPipeline means: restart the prompt session, but otherwise
            # maintain the pipeline context. Example: changing working
            # directory, which should in general use a different prompt
            # history file.
            continue
        except QuitPipeline:
            # QuitPipeline means: we are done, bye
            return

        finally:
            # Signal the watcher thread to exit before we loop back and create
            # a new session (and a new watcher) for the next prompt session.
            stop_event.set()

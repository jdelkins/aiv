from __future__ import annotations

import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory

from aiv.config import CONFIG_DIR
from aiv.conversation import get_conversation_file
from aiv.models import PipelineContext, SetModeCommand, InteractionMode
from aiv.commands import (
    parse_command,
    run_command,
    cmd_intro,
    QuitPipeline,
    cmd_set_mode,
)
from aiv.completion import AivCompleter

kb = KeyBindings()


@kb.add("escape", "enter")
def _submit(event):
    text = event.app.current_buffer.text
    if text.strip():
        event.app.current_buffer.history.append_string(text)
    event.app.exit(result=text)


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

    from aiv.conversation import get_conversation_file as _gcf
    import subprocess

    # Resolve history file alongside the conversation file's parent directory
    # so per-repo history stays with the repo, and global history stays global.
    history_file = ctx.conv_path.parent / ".aiv-history"

    session = PromptSession(
        history=FileHistory(str(history_file)),
        completer=AivCompleter(),
        complete_while_typing=False,  # Tab-triggered only; live completion is noisy
    )

    cmd_intro()
    if ctx.mode == InteractionMode.DEFAULT:
        cmd_set_mode(SetModeCommand(mode=InteractionMode.CHAT), ctx)

    while True:
        try:
            text = session.prompt(
                HTML("<ansicyan>aiv> </ansicyan>"),
                multiline=True,
                key_bindings=kb,
                prompt_continuation="...  ",
            )
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not text.strip():
            continue

        cmd = parse_command(text)
        try:
            run_command(cmd, ctx)
        except QuitPipeline:
            break

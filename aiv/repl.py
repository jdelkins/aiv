#!/usr/bin/env python3

import argparse
import sys

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory

from aiv.common import (
    get_version,
    find_repo_root,
    CONFIG_DIR,
)
from aiv.commands import (
    PipelineContext,
    Command,
    parse_command,
    run_command,
    run_pipeline,
    ResetCommand,
    ReplCommand,
    cmd_help,
    QuitPipeline,
)

kb = KeyBindings()


@kb.add("escape", "enter")
def _submit(event):
    text = event.app.current_buffer.text
    if text.strip():
        event.app.current_buffer.history.append_string(text)
    event.app.exit(result=text)


def run_repl_loop(ctx: PipelineContext):
    # If stdin was a pipe (e.g. piped context via `echo foo | aiv -i -c -`),
    # prompt_toolkit would see EOF immediately and exit. Reattach stdin to the
    # terminal so the REPL is actually interactive.
    if not sys.stdin.isatty():
        try:
            sys.stdin = open("/dev/tty", "r")
        except OSError:
            from rich.console import Console
            Console().print("[red]Cannot open /dev/tty — no terminal available for REPL.[/red]")
            return

    repo_root = find_repo_root()
    history_file = (repo_root if repo_root is not None else CONFIG_DIR) / ".aiv-history"
    session = PromptSession(history=FileHistory(str(history_file)))

    cmd_help()

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


def run_cli():
    """Entry point for the aiv-repl console script."""
    parser = argparse.ArgumentParser(
        prog="aiv-repl",
        description="aiv interactive REPL",
        add_help=False,
    )
    parser.add_argument("--model", "-m", dest="model", default=None)
    parser.add_argument("--sys-prompt", "-s", dest="sys_prompt", default=None)
    parser.add_argument("--reset", "-R", dest="reset", action="store_true")
    parser.add_argument("--code", "-X", dest="mode_code", action="store_true")
    parser.add_argument("--help", "-h", dest="help", action="store_true")
    parser.add_argument("--version", "-v", dest="version", action="store_true")
    args = parser.parse_args()

    if args.help:
        print(
            """aiv-repl - aiv interactive REPL
Usage   : aiv-repl [options]
Options : -R, --reset            Wipe conversation on startup
          -X, --code             Code-only mode (no markdown, caveats as comments)
          -m, --model MODEL      Override Anthropic model for this session
          -s, --sys-prompt TEXT  Override system prompt for this session
          -h, --help             Display this help message
          -v, --version          Display version information""",
            file=sys.stderr,
        )
        sys.exit(0)

    if args.version:
        print(f"aiv-repl {get_version()}", file=sys.stderr)
        sys.exit(0)

    # aiv-repl always needs a terminal — check early and bail clearly
    if not sys.stdin.isatty():
        try:
            sys.stdin = open("/dev/tty", "r")
        except OSError:
            print("aiv-repl: no terminal available", file=sys.stderr)
            sys.exit(1)

    from aiv.common import load_config
    try:
        config = load_config()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    api_key = config.get("api_key", "")
    if not api_key:
        print("aiv-repl: api_key not set", file=sys.stderr)
        sys.exit(1)

    max_tokens_raw = config.get("max_tokens", "4096")
    if not max_tokens_raw.isdigit():
        print("aiv-repl: max_tokens must be a positive integer", file=sys.stderr)
        sys.exit(1)

    ctx = PipelineContext(
        model=args.model or config.get("model", "claude-3-7-sonnet-latest"),
        sys_prompt=args.sys_prompt or config.get("sys_prompt", ""),
        mode_code=args.mode_code,
        api_key=api_key,
        max_tokens=int(max_tokens_raw),
    )

    commands: list[Command] = []
    if args.reset:
        commands.append(ResetCommand())
    commands.append(ReplCommand())
    run_pipeline(commands, ctx)


if __name__ == "__main__":
    run_cli()

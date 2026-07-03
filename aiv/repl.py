from __future__ import annotations

import sys
import argparse

from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory

from aiv.common import get_version, find_repo_root, load_config, CONFIG_DIR
from aiv.models import PipelineContext, InteractionMode
from aiv.specs import COMMAND_SPECS
from aiv.commands import (
    Command,
    parse_command,
    run_command,
    run_pipeline,
    ResetCommand,
    ReplCommand,
    cmd_help,
    QuitPipeline,
)
from aiv.completion import AivCompleter

kb = KeyBindings()

# Flags excluded from the standalone aiv-repl entry point: these either
# require a running pipeline context (--context, --history, --show) or are
# nonsensical for a script that immediately drops into ReplCommand (--repl).
_REPL_EXCLUDED_LONG_OPTIONS = ("--history", "--show", "--context", "--repl")


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

            Console().print(
                "[red]Cannot open /dev/tty — no terminal available for REPL.[/red]"
            )
            return

    # Mark context as interactive so cmd_reset/cmd_delete show confirmation prompts
    ctx.interactive = True

    repo_root = find_repo_root()
    history_file = (repo_root if repo_root is not None else CONFIG_DIR) / ".aiv-history"

    session = PromptSession(
        history=FileHistory(str(history_file)),
        completer=AivCompleter(),
        complete_while_typing=False,  # Tab-triggered only; live completion is noisy in a REPL
    )

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


def _repl_specs():
    """CommandSpecs exposed as flags on the standalone aiv-repl entry point."""
    return [
        spec
        for spec in COMMAND_SPECS
        if spec.long_option
        and spec.argparse_kwargs
        and spec.long_option not in _REPL_EXCLUDED_LONG_OPTIONS
    ]


def _build_repl_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiv-repl",
        description="aiv interactive REPL (use `aiv -i` instead)",
        add_help=False,
    )
    for spec in _repl_specs():
        flags = [spec.long_option]
        if spec.short_option:
            flags.insert(0, spec.short_option)
        dest = spec.long_option.lstrip("-").replace("-", "_")
        parser.add_argument(*flags, dest=dest, **spec.argparse_kwargs)

    parser.add_argument("--version", "-v", dest="version", action="store_true")
    return parser


def print_repl_help():
    """Build the --help option listing dynamically from the CommandSpec registry."""
    lines = [
        "aiv-repl - aiv interactive REPL (use `aiv -i` instead)",
        "Usage   : aiv-repl [options]",
        "Options :",
    ]
    for spec in _repl_specs():
        flags = spec.long_option
        if spec.short_option:
            flags = f"{spec.short_option}, {flags}"
        arg_hint = f" {spec.usage.upper()}" if spec.usage else ""
        col = f"  {flags}{arg_hint}"
        lines.append(f"{col:<38} {spec.help}")
    lines.append(f"{'  --version, -v':<38} Display version information")
    print("\n".join(lines), file=sys.stderr)


def run_cli():
    """Entry point for the aiv-repl console script (kept for backwards compatibility)."""
    parser = _build_repl_parser()
    args = parser.parse_args()

    if getattr(args, "help", False):
        print_repl_help()
        sys.exit(0)

    if getattr(args, "version", False):
        print(f"aiv-repl {get_version()}", file=sys.stderr)
        sys.exit(0)

    if getattr(args, "chat", False) and getattr(args, "code", False):
        print("aiv-repl: --chat and --code are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if not sys.stdin.isatty():
        try:
            sys.stdin = open("/dev/tty", "r")
        except OSError:
            print("aiv-repl: no terminal available", file=sys.stderr)
            sys.exit(1)

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

    initial_mode: InteractionMode | None = None
    if getattr(args, "chat", False):
        initial_mode = InteractionMode.CHAT
    elif getattr(args, "code", False):
        initial_mode = InteractionMode.CODE

    # model/sys_prompt/max_tokens: CLI args override config directly here since
    # aiv-repl runs outside the commands_from_args/pipeline flow used by cli.py.
    model = getattr(args, "model", None) or config.get(
        "model", "claude-3-7-sonnet-latest"
    )
    sys_prompt = getattr(args, "sys_prompt", None) or config.get("sys_prompt", "")
    max_tokens_arg = getattr(args, "max_tokens", None)
    max_tokens = int(max_tokens_arg) if max_tokens_arg else int(max_tokens_raw)

    ctx = PipelineContext(
        model=model,
        sys_prompt=sys_prompt,
        mode=initial_mode,
        api_key=api_key,
        max_tokens=max_tokens,
        interactive=True,
    )

    commands: list[Command] = []
    if getattr(args, "reset", False):
        commands.append(ResetCommand())
    commands.append(ReplCommand())
    run_pipeline(commands, ctx)

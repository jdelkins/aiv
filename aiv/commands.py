#!/usr/bin/env python3

from __future__ import annotations

import glob
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.table import Table
from anthropic.types import MessageParam

from aiv.common import (
    MODE_CHAT_SUFFIX,
    MODE_CODE_SUFFIX,
    get_conversation_file,
    load_conversation,
    save_conversation,
    reset_conversation,
    append_user_turn,
    build_interactions,
    flatten_interactions,
    count_context_blocks,
    first_line,
    format_bytes,
    parse_range,
    build_user_content,
    run_turn,
    CONFIG_DIR,
)

console = Console()


# ---------------------------------------------------------------------------
# Command dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ContextCommand:
    path: str  # glob pattern or "-" for stdin


@dataclass
class PromptCommand:
    text: str


@dataclass
class HistoryCommand:
    range: str | None = None


@dataclass
class ShowCommand:
    args: str


@dataclass
class DeleteCommand:
    range: str


@dataclass
class ResetCommand:
    pass


@dataclass
class HelpCommand:
    pass


@dataclass
class ReplCommand:
    pass


@dataclass
class ExitCommand:
    pass


Command = (
    ContextCommand
    | PromptCommand
    | HistoryCommand
    | ShowCommand
    | DeleteCommand
    | ResetCommand
    | HelpCommand
    | ReplCommand
    | ExitCommand
)


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    model: str = "claude-3-7-sonnet-latest"
    sys_prompt: str = ""
    mode_code: bool = False
    stdin_data: str | None = None
    api_key: str = ""
    max_tokens: int = 4096
    interactive: bool = False  # set True by run_repl_loop
    piped_stdin: bool = False  # True if stdin was a pipe at invocation

    @property
    def mode_suffix(self) -> str:
        return MODE_CODE_SUFFIX if self.mode_code else MODE_CHAT_SUFFIX


# ---------------------------------------------------------------------------
# Markdown detection + shared output renderer
# ---------------------------------------------------------------------------

MARKDOWN_PATTERNS = [
    r"^```",
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$",
    r"\[[^\]]+\]\(https?://[^\)]+\)",
    r"^\*\*[^*]+\*\*:?\s*$",
    r"^\s*\d+\.\s+\*\*[^*]+\*\*",
    r"^\s*[-*+]\s+\*\*[^*]+\*\*",
]


def looks_like_markdown(text: str) -> bool:
    for line in text.splitlines():
        for pattern in MARKDOWN_PATTERNS:
            if re.search(pattern, line):
                return True
    return False


def render_output(text: str, ctx: PipelineContext):
    """Canonical output renderer: glow for markdown, raw print for code mode or plain text."""
    import subprocess

    if not ctx.mode_code and looks_like_markdown(text):
        subprocess.run(["glow", "-"], input=text, text=True)
    else:
        print(text)


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------


def print_history_table(interactions: list[list[MessageParam]], start: int, end: int):
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("#", style="dim", width=4, justify="right")
    table.add_column("Role", width=10)
    table.add_column("Context", width=14, justify="right")
    table.add_column("First Line")

    for i in range(start - 1, end):
        interaction = interactions[i]
        num = str(i + 1)
        for msg in interaction:
            role = msg["role"]
            content = msg["content"]
            content_str = content if isinstance(content, str) else str(content)
            total_bytes = len(content_str.encode())
            block_count = count_context_blocks(content_str)
            ctx_str = format_bytes(total_bytes)
            if block_count:
                ctx_str += f" / {block_count}f"
            fl = first_line(content_str)
            role_style = "green" if role == "user" else "magenta"
            table.add_row(num, f"[{role_style}]{role}[/{role_style}]", ctx_str, fl)
            num = ""

    console.print(table)


# ---------------------------------------------------------------------------
# Command implementations
# ---------------------------------------------------------------------------


def cmd_history(cmd: HistoryCommand):
    conv_path = get_conversation_file()
    messages = load_conversation(conv_path)
    interactions = build_interactions(messages)

    if not interactions:
        console.print("[yellow]No conversation history.[/yellow]")
        return

    if cmd.range:
        parsed = parse_range(cmd.range, len(interactions))
        if parsed is None:
            console.print(f"[red]Invalid range: {cmd.range}[/red]")
            return
        start, end = parsed
    else:
        start, end = 1, len(interactions)

    print_history_table(interactions, start, end)


def cmd_show(cmd: ShowCommand, ctx: PipelineContext):
    parts = cmd.args.strip().split()
    if not parts:
        console.print("[red]Usage: !show <num|range> [user|assistant] [--raw|-r][/red]")
        return

    raw_mode = False
    filtered_parts = []
    for p in parts:
        if p in ("--raw", "-r"):
            raw_mode = True
        else:
            filtered_parts.append(p)
    parts = filtered_parts

    conv_path = get_conversation_file()
    messages = load_conversation(conv_path)
    interactions = build_interactions(messages)

    range_tuple = parse_range(parts[0], len(interactions))
    if range_tuple is None:
        console.print(f"[red]Invalid number or range: {parts[0]}[/red]")
        return
    start, end = range_tuple

    role_filter = parts[1].lower() if len(parts) > 1 else None
    if role_filter and role_filter not in ("user", "assistant"):
        console.print("[red]Role must be 'user' or 'assistant'[/red]")
        return

    for i in range(start - 1, end):
        interaction = interactions[i]
        num = i + 1
        for msg in interaction:
            if role_filter and msg["role"] != role_filter:
                continue
            content = msg["content"]
            content_str = content if isinstance(content, str) else str(content)
            role = msg["role"]
            role_style = "green" if role == "user" else "magenta"
            console.print(
                f"\n[bold {role_style}]--- {role} (interaction {num}) ---[/bold {role_style}]"
            )
            if raw_mode:
                print(content_str)
            else:
                render_output(content_str, ctx)


def cmd_delete(cmd: DeleteCommand, ctx: PipelineContext):
    conv_path = get_conversation_file()
    messages = load_conversation(conv_path)
    interactions = build_interactions(messages)

    if not interactions:
        console.print("[yellow]No conversation history.[/yellow]")
        return

    range_tuple = parse_range(cmd.range.strip(), len(interactions))
    if range_tuple is None:
        console.print(f"[red]Invalid range: {cmd.range}[/red]")
        return

    start, end = range_tuple

    remaining_after = interactions[end:]
    if start == 1 and remaining_after:
        first_remaining = remaining_after[0][0]
        if first_remaining["role"] != "user":
            console.print(
                "[bold red]Warning:[/bold red] This would leave the conversation "
                "starting with an assistant turn, which is invalid for the Anthropic API."
            )

    # Same confirmation logic as cmd_reset: confirm if interactive (REPL) or if
    # nothing was piped into this invocation. Skip confirmation only when stdin
    # was explicitly piped (a scripted, non-interactive invocation).
    should_confirm = ctx.interactive or not ctx.piped_stdin

    if not should_confirm:
        new_interactions = interactions[: start - 1] + interactions[end:]
        save_conversation(flatten_interactions(new_interactions), conv_path)
        return

    console.print(
        f"\n[bold]Preview of interactions to be deleted ({start}-{end}):[/bold]"
    )
    print_history_table(interactions, start, end)

    try:
        confirm = console.input(
            f"\n[bold red]Delete interactions {start}-{end}? (y/n):[/bold red] "
        )
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Cancelled.[/yellow]")
        return

    if confirm.strip().lower() != "y":
        console.print("[yellow]Cancelled.[/yellow]")
        return

    new_interactions = interactions[: start - 1] + interactions[end:]
    save_conversation(flatten_interactions(new_interactions), conv_path)
    console.print(f"[green]Deleted interactions {start}-{end}.[/green]")


def cmd_reset(ctx: PipelineContext):
    conv_path = get_conversation_file()
    messages = load_conversation(conv_path)
    interactions = build_interactions(messages)
    # Confirm if interactive (inside REPL) or if no stdin was piped (direct terminal invocation).
    # Skip confirmation if stdin was piped — the user clearly scripted this.
    should_confirm = ctx.interactive or not ctx.piped_stdin

    if not interactions:
        # Only print this if someone will see it
        if should_confirm:
            console.print("[yellow]Conversation is already empty.[/yellow]")
        return

    if not should_confirm:
        reset_conversation(conv_path)
        return

    console.print(
        f"\n[bold]Current conversation ({len(interactions)} interaction(s)):[/bold]"
    )
    print_history_table(interactions, 1, len(interactions))

    try:
        confirm = console.input(
            "\n[bold red]Wipe entire conversation? (y/n):[/bold red] "
        )
    except (EOFError, KeyboardInterrupt):
        console.print("\n[yellow]Cancelled.[/yellow]")
        return

    if confirm.strip().lower() != "y":
        console.print("[yellow]Cancelled.[/yellow]")
        return

    reset_conversation(conv_path)
    console.print("[green]Conversation reset.[/green]")


def cmd_context(cmd: ContextCommand, ctx: PipelineContext):
    if cmd.path == "-":
        data = ctx.stdin_data or ""
        ctx.stdin_data = None  # consume
        if not data:
            console.print("[yellow]No stdin data to add as context.[/yellow]")
            return
        append_user_turn(build_user_content("", [], data))
        console.print("[green]Added stdin as context.[/green]")
    else:
        matches = glob.glob(cmd.path, recursive=True)
        if not matches:
            console.print(f"[red]No files matched: {cmd.path}[/red]")
            return
        append_user_turn(build_user_content("", [cmd.path], None))
        console.print(
            f"[green]Added context: {cmd.path} ({len(matches)} file(s))[/green]"
        )


def cmd_prompt(cmd: PromptCommand, ctx: PipelineContext):
    stdin_data = ctx.stdin_data or None
    ctx.stdin_data = None  # consume

    try:
        response_text = run_turn(
            prompt=cmd.text,
            context_files=[],
            stdin_data=stdin_data,
            mode_suffix=ctx.mode_suffix,
            api_key=ctx.api_key,
            model=ctx.model,
            max_tokens=ctx.max_tokens,
            sys_prompt=ctx.sys_prompt,
        )
    except Exception as e:
        print(f"aiv: {e}", file=sys.stderr)
        return

    render_output(response_text, ctx)


def cmd_help():
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="dim")

    commands = [
        ("!history \[range]", "Show conversation history (optional range, e.g. 3-7)"),
        (
            "!show <range> \[role] \[--raw|-r]",
            "Show full turn (role: user|assistant, default: both)",
        ),
        ("!delete <range>", "Delete interactions with preview + confirm"),
        ("!reset", "Wipe conversation (same as aiv -R), with confirm"),
        ("!context <path>", "Add file to context (glob pattern or - for stdin)"),
        ("!help", "Show this help"),
        ("!quit, !exit", "End the session"),
    ]

    console.print("\n[bold cyan]aiv REPL commands[/bold cyan]\n")
    for c, desc in commands:
        table.add_row(c, desc)
    console.print(table)
    console.print(
        "\n  [dim]Alt-Enter (or Escape then Enter) submits a prompt "
        "(allows multiline input with Enter)[/dim]\n"
    )


# ---------------------------------------------------------------------------
# parse_command: text -> Command
# ---------------------------------------------------------------------------


def parse_command(text: str) -> Command:
    stripped = text.strip()
    if not stripped.startswith("!"):
        return PromptCommand(text=stripped)

    parts = stripped.split(None, 1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "!history":
        return HistoryCommand(range=args.strip() or None)
    elif cmd == "!show":
        return ShowCommand(args=args)
    elif cmd == "!delete":
        return DeleteCommand(range=args.strip())
    elif cmd == "!reset":
        return ResetCommand()
    elif cmd == "!context":
        return ContextCommand(path=args.strip())
    elif cmd == "!help":
        return HelpCommand()
    elif cmd == "!repl":
        return ReplCommand()
    elif cmd in ("!quit", "!exit"):
        return ExitCommand()
    else:
        console.print(
            f"[red]Unknown command: {cmd}. Type !help for available commands.[/red]"
        )
        return ExitCommand()


# ---------------------------------------------------------------------------
# commands_from_args: argparse Namespace -> list[Command]
# ---------------------------------------------------------------------------


def commands_from_args(args) -> list[Command]:
    """
    Translate a parsed argparse Namespace into an ordered Command pipeline.

    Ordering:
      1. ResetCommand (if --reset)
      2. ContextCommand per -c value
      3. PromptCommand (if prompt given)
      4. HistoryCommand (if --history)
      5. ShowCommand (if --show)
      6. ReplCommand (if -i), otherwise pipeline ends naturally
    """
    commands: list[Command] = []

    if getattr(args, "reset", False):
        commands.append(ResetCommand())

    for pattern in getattr(args, "context_files", []):
        commands.append(ContextCommand(path=pattern))

    prompt_text = " ".join(args.prompt) if args.prompt else ""
    if prompt_text:
        commands.append(PromptCommand(text=prompt_text))

    history_val = getattr(args, "history", None)
    if history_val is not None:
        range_str = None if history_val is True else str(history_val)
        commands.append(HistoryCommand(range=range_str))

    show_val = getattr(args, "show", None)
    if show_val is not None:
        range_str = "1-" if show_val is True else str(show_val)
        commands.append(ShowCommand(args=range_str))

    if getattr(args, "repl", False):
        commands.append(ReplCommand())

    return commands


# ---------------------------------------------------------------------------
# run_command / run_pipeline
# ---------------------------------------------------------------------------


class QuitPipeline(Exception):
    pass


def run_command(cmd: Command, ctx: PipelineContext) -> None:
    """Execute a single command. Raises QuitPipeline on ExitCommand."""
    if isinstance(cmd, ContextCommand):
        cmd_context(cmd, ctx)
    elif isinstance(cmd, PromptCommand):
        cmd_prompt(cmd, ctx)
    elif isinstance(cmd, HistoryCommand):
        cmd_history(cmd)
    elif isinstance(cmd, ShowCommand):
        cmd_show(cmd, ctx)
    elif isinstance(cmd, DeleteCommand):
        cmd_delete(cmd, ctx)
    elif isinstance(cmd, ResetCommand):
        cmd_reset(ctx)
    elif isinstance(cmd, HelpCommand):
        cmd_help()
    elif isinstance(cmd, ReplCommand):
        # Deferred import to avoid circular dependency: repl.py imports commands.py
        from aiv.repl import run_repl_loop

        run_repl_loop(ctx)
    elif isinstance(cmd, ExitCommand):
        raise QuitPipeline()


def run_pipeline(commands: list[Command], ctx: PipelineContext) -> None:
    """Execute commands in order. Stops on QuitPipeline or end of list."""
    try:
        for cmd in commands:
            run_command(cmd, ctx)
    except QuitPipeline:
        pass

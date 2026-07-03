from __future__ import annotations

import glob
import re
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table
from anthropic.types import MessageParam

from aiv.common import (
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
)
from aiv.models import (
    InteractionMode,
    Command,
    ContextCommand,
    PromptCommand,
    HistoryCommand,
    ShowCommand,
    DeleteCommand,
    ResetCommand,
    HelpCommand,
    ReplCommand,
    ExitCommand,
    NoOpCommand,
    SetModelCommand,
    SetMaxTokensCommand,
    SetSysPromptCommand,
    SetModeCommand,
    PipelineContext,
)
from aiv.specs import (
    COMMAND_SPECS,
    COMMAND_LOOKUP,
    OPTION_LOOKUP,
    PROMPT_SPEC,
    CommandSpec,
)

console = Console()


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

    if ctx.mode != InteractionMode.CODE and looks_like_markdown(text):
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
    should_confirm = ctx.interactive or not ctx.piped_stdin

    if not interactions:
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


def cmd_set_model(cmd: SetModelCommand, ctx: PipelineContext):
    ctx.model = cmd.model
    if ctx.interactive:
        console.print(f"[green]Model set to {cmd.model}[/green]")


def cmd_set_max_tokens(cmd: SetMaxTokensCommand, ctx: PipelineContext):
    ctx.max_tokens = cmd.max_tokens
    if ctx.interactive:
        console.print(f"[green]max_tokens set to {cmd.max_tokens}[/green]")


def cmd_set_sys_prompt(cmd: SetSysPromptCommand, ctx: PipelineContext):
    ctx.sys_prompt = cmd.sys_prompt
    if ctx.interactive:
        console.print(f"[green]sys_prompt updated[/green]")


def cmd_set_mode(cmd: SetModeCommand, ctx: PipelineContext):
    ctx.mode = cmd.mode
    if ctx.interactive:
        label = cmd.mode.value if cmd.mode is not None else "default"
        console.print(f"[green]Mode set to {label}[/green]")


def cmd_help():
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="dim")

    console.print("\n[bold cyan]aiv REPL commands[/bold cyan]\n")
    for spec in COMMAND_SPECS:
        if not spec.names:
            continue  # skip the bare-prompt pseudo-spec
        name = ", ".join(spec.names)
        full_usage = f"{name} {spec.usage}".strip()
        table.add_row(full_usage, spec.help)
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
    name = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    spec = COMMAND_LOOKUP.get(name)
    if spec is None:
        console.print(
            f"[red]Unknown command: {name}. Type !help for available commands.[/red]"
        )
        return NoOpCommand()

    return spec.parse(args)


# ---------------------------------------------------------------------------
# commands_from_args: argparse Namespace -> list[Command]
# ---------------------------------------------------------------------------


def commands_from_args(args) -> list[Command]:
    """
    Translate a parsed argparse Namespace into an ordered Command pipeline.
    Each CommandSpec with a long_option is checked against the namespace;
    matching values emit a Command at the spec's precedence. The list is
    stable-sorted by precedence so registry/input order is preserved within
    equal-precedence groups (e.g. multiple --context flags).
    """
    pending: list[tuple[int, Command]] = []

    for spec in COMMAND_SPECS:
        if not spec.long_option:
            continue

        dest = spec.long_option.lstrip("-").replace("-", "_")
        val = getattr(args, dest, None)

        if val is None or val is False:
            continue

        # action="append" produces a list (e.g. --context used multiple times)
        if isinstance(val, list):
            for item in val:
                sub_args = item if isinstance(item, str) else ""
                pending.append((spec.precedence, spec.parse(sub_args)))
        elif val is True:
            # store_true / store_const flags
            pending.append((spec.precedence, spec.parse("")))
        else:
            pending.append((spec.precedence, spec.parse(str(val))))

    # Inject positional prompt at its declared precedence
    prompt_text = " ".join(args.prompt) if getattr(args, "prompt", None) else ""
    if prompt_text:
        pending.append((PROMPT_SPEC.precedence, PromptCommand(text=prompt_text)))

    # Stable sort: equal precedence preserves original input/registry order
    pending.sort(key=lambda t: t[0])
    return [cmd for _, cmd in pending]


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
    elif isinstance(cmd, SetModelCommand):
        cmd_set_model(cmd, ctx)
    elif isinstance(cmd, SetMaxTokensCommand):
        cmd_set_max_tokens(cmd, ctx)
    elif isinstance(cmd, SetSysPromptCommand):
        cmd_set_sys_prompt(cmd, ctx)
    elif isinstance(cmd, SetModeCommand):
        cmd_set_mode(cmd, ctx)
    elif isinstance(cmd, HelpCommand):
        cmd_help()
    elif isinstance(cmd, ReplCommand):
        # Deferred import to avoid circular dependency: repl.py imports commands.py
        from aiv.repl import run_repl_loop

        run_repl_loop(ctx)
    elif isinstance(cmd, ExitCommand):
        raise QuitPipeline()
    elif isinstance(cmd, NoOpCommand):
        pass


def run_pipeline(commands: list[Command], ctx: PipelineContext) -> None:
    """Execute commands in order. Stops on QuitPipeline or end of list."""
    try:
        for cmd in commands:
            run_command(cmd, ctx)
    except QuitPipeline:
        pass

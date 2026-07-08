from __future__ import annotations
from aiv.config import get_version
import shutil
import glob
import re
import subprocess
import sys
from pathlib import Path
from rich.console import Console
from rich.table import Table
from rich.markdown import Markdown
from anthropic.types import MessageParam

from aiv.conversation import (
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
    strip_context_blocks,
)
from aiv.content import build_user_content
from aiv.api import run_turn
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
    SetPromptSuffixCommand,
    PipelineContext,
    ShowVersionCommand,
    ShowPipelineContextCommand,
)
from aiv.specs import (
    COMMAND_SPECS,
    COMMAND_LOOKUP,
    OPTION_LOOKUP,
    PROMPT_SPEC,
    CommandSpec,
)

# stdout console for primary output (history tables, show content, help)
console = Console()

# stderr console for all informational/status messages so they never pollute
# piped stdout regardless of tty state
info = Console(stderr=True)


# ---------------------------------------------------------------------------
# Markdown detection + shared output renderer
# ---------------------------------------------------------------------------

# Any single strong pattern match → treat as markdown
MARKDOWN_STRONG = [
    # fenced code block
    r"^```",
    # table separator row
    r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?\s*$",
    # markdown link
    r"\[[^\]]+\]\(https?://[^\)]+\)",
    # atx heading
    r"^#{1,6}\s+\S",
    # blockquote
    r"^\s*>\s+\S",
]

# Three or more weak pattern matches required → treat as markdown
MARKDOWN_WEAK = [
    # inline code
    r"`[^`]+`",
    # bold
    r"\*\*[^*]+\*\*",
    # list item with bold label
    r"^\s*[-*+]\s+\*\*[^*]+\*\*",
    # ordered list item with bold label
    r"^\s*\d+\.\s+\*\*[^*]+\*\*",
]

# If any of these match, skip markdown rendering regardless of other signals
MARKDOWN_NEVER = [
    r"^---CONTEXT_TXT:",
    r"^raw code\b",
]

# Tunable thresholds for symbol/digit density heuristic
_SYMBOL_DENSITY_THRESHOLD = 0.08
_DIGIT_DENSITY_THRESHOLD = 0.15
_CODE_SYMBOLS = frozenset(r"{}[]()<>=|;:\\/@#$%^&*~")


def _looks_like_code(text: str) -> bool:
    """Heuristic: high symbol or digit density suggests code/technical output."""
    n = len(text)
    if n == 0:
        return False
    symbols = sum(1 for c in text if c in _CODE_SYMBOLS)
    digits = sum(1 for c in text if c.isdigit())
    return (symbols / n) > _SYMBOL_DENSITY_THRESHOLD or (
        digits / n
    ) > _DIGIT_DENSITY_THRESHOLD


def looks_like_markdown(text: str) -> bool:
    lines = text.splitlines()
    if not lines:
        return False

    # Negative signals: bail out immediately
    for line in lines:
        for pattern in MARKDOWN_NEVER:
            if re.search(pattern, line):
                return False
    if _looks_like_code(text):
        return False

    # Strong positive signals: any single match is sufficient
    for line in lines:
        for pattern in MARKDOWN_STRONG:
            if re.search(pattern, line):
                return True

    # Weak positive signals: require 3 or more hits across distinct lines
    weak_hits = 0
    for line in lines:
        for pattern in MARKDOWN_WEAK:
            if re.search(pattern, line):
                weak_hits += 1
                if weak_hits >= 3:
                    return True
                break  # count at most one weak hit per line

    return False


def render_output(text: str, ctx: PipelineContext) -> None:
    """
    Canonical output renderer: rich Markdown for markdown content, raw print
    for code mode or plain text.
    """
    if ctx.mode != InteractionMode.CODE and looks_like_markdown(text):
        console.print(Markdown(text))
        return
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


def cmd_history(cmd: HistoryCommand, ctx: PipelineContext):
    messages = load_conversation(ctx.conv_path)
    interactions = build_interactions(messages)

    if not interactions:
        info.print("[yellow]No conversation history.[/yellow]")
        return

    if cmd.range:
        parsed = parse_range(cmd.range, len(interactions))
        if parsed is None:
            info.print(f"[red]Invalid range: {cmd.range}[/red]")
            return
        start, end = parsed
    else:
        start, end = 1, len(interactions)

    print_history_table(interactions, start, end)


def cmd_show(cmd: ShowCommand, ctx: PipelineContext):
    parts = cmd.args.strip().split()

    raw_mode = False
    filtered_parts = []
    for p in parts:
        if p in ("--raw", "-r"):
            raw_mode = True
        else:
            filtered_parts.append(p)
    parts = filtered_parts

    messages = load_conversation(ctx.conv_path)
    interactions = build_interactions(messages)

    if not interactions:
        info.print("[yellow]No conversation history.[/yellow]")
        return

    # If no positional args, show entire history
    range_str = parts[0] if parts else "1-"

    range_tuple = parse_range(range_str, len(interactions))
    if range_tuple is None:
        info.print(f"[red]Invalid number or range: {range_str}[/red]")
        return
    start, end = range_tuple

    role_filter = parts[1].lower() if len(parts) > 1 else None
    if role_filter and role_filter not in ("user", "assistant"):
        info.print("[red]Role must be 'user' or 'assistant'[/red]")
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
            # headers go to stderr; content goes to stdout via render_output
            info.print(
                f"\n[bold {role_style}]--- {role} (interaction {num}) ---[/bold {role_style}]"
            )
            if raw_mode:
                print(content_str)
            else:
                render_output(content_str, ctx)


def cmd_delete(cmd: DeleteCommand, ctx: PipelineContext):
    messages = load_conversation(ctx.conv_path)
    interactions = build_interactions(messages)

    if not interactions:
        info.print("[yellow]No conversation history.[/yellow]")
        return

    range_tuple = parse_range(cmd.range.strip(), len(interactions))
    if range_tuple is None:
        info.print(f"[red]Invalid range: {cmd.range}[/red]")
        return

    start, end = range_tuple

    remaining_after = interactions[end:]
    if start == 1 and remaining_after:
        first_remaining = remaining_after[0][0]
        if first_remaining["role"] != "user":
            info.print(
                "[bold red]Warning:[/bold red] This would leave the conversation "
                "starting with an assistant turn, which is invalid for the Anthropic API."
            )

    should_confirm = ctx.interactive or not ctx.piped_stdin

    if not should_confirm:
        new_interactions = interactions[: start - 1] + interactions[end:]
        save_conversation(flatten_interactions(new_interactions), ctx.conv_path)
        return

    info.print(f"\n[bold]Preview of interactions to be deleted ({start}-{end}):[/bold]")
    print_history_table(interactions, start, end)

    try:
        confirm = console.input(
            f"\n[bold red]Delete interactions {start}-{end}? (y/n):[/bold red] "
        )
    except (EOFError, KeyboardInterrupt):
        info.print("\n[yellow]Cancelled.[/yellow]")
        return

    if confirm.strip().lower() != "y":
        info.print("[yellow]Cancelled.[/yellow]")
        return

    new_interactions = interactions[: start - 1] + interactions[end:]
    save_conversation(flatten_interactions(new_interactions), ctx.conv_path)
    info.print(f"[green]Deleted interactions {start}-{end}.[/green]")


def cmd_reset(ctx: PipelineContext):
    messages = load_conversation(ctx.conv_path)
    interactions = build_interactions(messages)
    should_confirm = ctx.interactive or not ctx.piped_stdin

    if not interactions:
        if should_confirm:
            info.print("[yellow]Conversation is already empty.[/yellow]")
        return

    if not should_confirm:
        reset_conversation(ctx.conv_path)
        return

    info.print(
        f"\n[bold]Current conversation ({len(interactions)} interaction(s)):[/bold]"
    )
    print_history_table(interactions, 1, len(interactions))

    try:
        confirm = console.input(
            "\n[bold red]Wipe entire conversation? (y/n):[/bold red] "
        )
    except (EOFError, KeyboardInterrupt):
        info.print("\n[yellow]Cancelled.[/yellow]")
        return

    if confirm.strip().lower() != "y":
        info.print("[yellow]Cancelled.[/yellow]")
        return

    reset_conversation(ctx.conv_path)
    info.print("[green]Conversation reset.[/green]")


def cmd_context(cmd: ContextCommand, ctx: PipelineContext):
    if cmd.path == "-":
        data = ctx.consume_stdin()
        if not data:
            info.print("[yellow]No stdin data to add as context.[/yellow]")
            return
        append_user_turn(
            build_user_content(
                "",
                [],
                data,
                stdin_ctx_file=cmd.ctx_file,
                stdin_ctx_range=cmd.ctx_range,
            ),
            ctx.conv_path,
        )
        info.print("[green]Added stdin as context.[/green]")
    else:
        matches = glob.glob(cmd.path, recursive=True)
        if not matches:
            info.print(f"[red]No files matched: {cmd.path}[/red]")
            return
        append_user_turn(build_user_content("", [cmd.path], None), ctx.conv_path)
        info.print(f"[green]Added context: {cmd.path} ({len(matches)} file(s))[/green]")


def cmd_prompt(cmd: PromptCommand, ctx: PipelineContext):
    stdin_data = ctx.consume_stdin()

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
            conv_path=ctx.conv_path,
        )
    except Exception as e:
        info.print(f"[red]aiv: {e}[/red]")
        return

    render_output(response_text, ctx)


def cmd_set_model(cmd: SetModelCommand, ctx: PipelineContext):
    if cmd.model is not None:
        ctx.model = cmd.model
    if ctx.interactive:
        info.print(f"[green]Model set to: {ctx.model}[/green]")


def cmd_set_max_tokens(cmd: SetMaxTokensCommand, ctx: PipelineContext):
    if cmd.max_tokens is not None:
        ctx.max_tokens = cmd.max_tokens
    if ctx.interactive:
        info.print(f"[green]max_tokens set to: {ctx.max_tokens}[/green]")


def cmd_set_sys_prompt(cmd: SetSysPromptCommand, ctx: PipelineContext):
    if cmd.sys_prompt is not None:
        ctx.sys_prompt = cmd.sys_prompt
    if ctx.interactive:
        info.print(f"[green]sys_prompt set to: {ctx.sys_prompt}[/green]")


def cmd_set_mode(cmd: SetModeCommand, ctx: PipelineContext):
    if cmd.mode is not None:
        ctx.mode = cmd.mode
    if ctx.interactive:
        info.print(f"[green]Mode set to: {ctx.mode.value}[/green]")


def cmd_set_prompt_suffix(cmd: SetPromptSuffixCommand, ctx: PipelineContext):
    if cmd.suffix is not None:
        ctx.mode_suffix = "\n\n" + cmd.suffix
    if ctx.interactive:
        info.print(f"[green]Prompt suffix set to: {ctx.mode_suffix}[/green]")


def cmd_help():
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="dim")

    console.print("\n[bold cyan]aiv REPL commands[/bold cyan]\n")
    for spec in COMMAND_SPECS:
        if not spec.names:
            continue  # skip the bare-prompt pseudo-spec
        name = ", ".join(spec.names)
        display_usage = spec.repl_usage if spec.repl_usage is not None else spec.usage
        full_usage = f"{name} {display_usage}".strip()
        table.add_row(full_usage, spec.help)
    console.print(table)
    console.print(
        "\n  [dim]Alt-Enter (or Escape then Enter) submits a prompt "
        "(allows multiline input with Enter)[/dim]\n"
    )


def cmd_intro():
    console.print(
        "\n[bold cyan]aiv REPL:[/bold cyan] [cyan]Type a prompt or !help for a list of commands.[/cyan]"
    )
    console.print(
        "[dim]Alt-Enter (or Escape then Enter) submits a prompt or command.\n"
    )


def cmd_version():
    console.print(f"aiv {get_version()}\n")


def cmd_pipeline_context(ctx):
    console.print(f"{ctx}\n")


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
        info.print(
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
            # store_true flags
            pending.append((spec.precedence, spec.parse("")))
        else:
            # nargs="?" with const=True: val may be True (flag with no argument)
            # or a string (flag with argument). True means no argument was given,
            # so pass "" rather than str(True) which would be treated as a range.
            str_val = "" if val is True else str(val)
            pending.append((spec.precedence, spec.parse(str_val)))

    # Inject positional prompt at its declared precedence
    prompt_text = " ".join(args.prompt) if getattr(args, "prompt", None) else ""
    if prompt_text:
        pending.append((PROMPT_SPEC.precedence, PromptCommand(text=prompt_text)))
    elif len(pending) == 0:
        repl_command = OPTION_LOOKUP["--repl"]
        pending.append((repl_command.precedence, ReplCommand()))

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
        cmd_history(cmd, ctx)
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
    elif isinstance(cmd, SetPromptSuffixCommand):
        cmd_set_prompt_suffix(cmd, ctx)
    elif isinstance(cmd, HelpCommand):
        cmd_help()
    elif isinstance(cmd, ReplCommand):
        # Deferred import to avoid circular dependency: repl.py imports commands.py
        from aiv.repl import run_repl_loop

        run_repl_loop(ctx)
    elif isinstance(cmd, ShowVersionCommand):
        cmd_version()
    elif isinstance(cmd, ShowPipelineContextCommand):
        cmd_pipeline_context(ctx)
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

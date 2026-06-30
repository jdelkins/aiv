import subprocess
import sys
import re
import glob as _glob
from pathlib import Path
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.table import Table
from anthropic.types import MessageParam

from aiv.common import (
    get_conversation_file,
    load_conversation,
    save_conversation,
    build_interactions,
    flatten_interactions,
    strip_context_blocks,
    count_context_blocks,
    first_line,
    format_bytes,
    parse_range,
    find_repo_root,
    CONFIG_DIR,
)

kb = KeyBindings()
console = Console()


@kb.add("c-j")
def submit(event):
    text = event.app.current_buffer.text
    if text.strip():
        event.app.current_buffer.history.append_string(text)
    event.app.exit(result=text)


class QuitRepl(Exception):
    pass


MARKDOWN_PATTERNS = [
    r"^#{1,6}\s",  # headings
    r"^\s*[-*+]\s",  # unordered lists
    r"^\s*\d+\.\s",  # ordered lists
    r"^```",  # fenced code blocks
    r"\*\*\S",  # bold
    r"`[^`]+`",  # inline code
    r"^\s*\|.+\|",  # tables
    r"^\s*>",  # blockquotes
    r"\[.+\]\(.+\)",  # links
]


def looks_like_markdown(text: str) -> bool:
    for line in text.splitlines():
        for pattern in MARKDOWN_PATTERNS:
            if re.search(pattern, line):
                return True
    return False


def cmd_history(args: str, conv_path: Path):
    messages = load_conversation(conv_path)
    interactions = build_interactions(messages)

    if not interactions:
        console.print("[yellow]No conversation history.[/yellow]")
        return

    if args.strip():
        parsed = parse_range(args.strip(), len(interactions))
        if parsed is None:
            console.print(f"[red]Invalid range: {args.strip()}[/red]")
            return
        start, end = parsed
    else:
        start, end = 1, len(interactions)

    print_history_table(interactions, start, end)


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
            # content may be a list of blocks in the Anthropic API but in practice
            # aiv always writes plain strings; cast for local use
            content_str = content if isinstance(content, str) else str(content)
            total_bytes = len(content_str.encode())
            block_count = count_context_blocks(content_str)
            ctx = format_bytes(total_bytes)
            if block_count:
                ctx += f" / {block_count}f"
            fl = first_line(content_str)
            role_style = "green" if role == "user" else "magenta"
            table.add_row(num, f"[{role_style}]{role}[/{role_style}]", ctx, fl)
            num = ""

    console.print(table)


def cmd_show(args: str, conv_path: Path):
    parts = args.strip().split()
    if not parts:
        console.print("[red]Usage: !show <num> [user|assistant] [--raw|-r][/red]")
        return

    raw_mode = False
    filtered_parts = []
    for p in parts:
        if p in ("--raw", "-r"):
            raw_mode = True
        else:
            filtered_parts.append(p)
    parts = filtered_parts

    messages = load_conversation(conv_path)
    interactions = build_interactions(messages)

    try:
        num = int(parts[0])
    except ValueError:
        console.print(f"[red]Invalid interaction number: {parts[0]}[/red]")
        return

    if num < 1 or num > len(interactions):
        console.print(
            f"[red]Interaction {num} out of range (1-{len(interactions)})[/red]"
        )
        return

    role_filter = parts[1].lower() if len(parts) > 1 else None
    if role_filter and role_filter not in ("user", "assistant"):
        console.print("[red]Role must be 'user' or 'assistant'[/red]")
        return

    interaction = interactions[num - 1]
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
        if not raw_mode and looks_like_markdown(content_str):
            subprocess.run(["glow", "-"], input=content_str, text=True)
        else:
            print(content_str)


def cmd_delete(args: str, conv_path: Path):
    messages = load_conversation(conv_path)
    interactions = build_interactions(messages)

    if not interactions:
        console.print("[yellow]No conversation history.[/yellow]")
        return

    range_tuple = parse_range(args.strip(), len(interactions))
    if range_tuple is None:
        console.print(f"[red]Invalid range: {args.strip()}[/red]")
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


def cmd_reset(conv_path: Path):
    messages = load_conversation(conv_path)
    interactions = build_interactions(messages)

    if not interactions:
        console.print("[yellow]Conversation is already empty.[/yellow]")
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

    save_conversation([], conv_path)
    console.print("[green]Conversation reset.[/green]")


def cmd_context(args: str):
    path = args.strip()
    if not path:
        console.print("[red]Usage: !context <path>[/red]")
        return
    matches = _glob.glob(path, recursive=True)
    if not matches:
        console.print(f"[red]No files matched: {path}[/red]")
        return
    result = subprocess.run(["aiv", "-c", path], capture_output=True, text=True)
    if result.returncode != 0:
        console.print(f"[red]{result.stderr}[/red]")
    else:
        console.print(f"[green]Added context: {path} ({len(matches)} file(s))[/green]")


def cmd_help():
    table = Table(show_header=False, box=None, padding=(0, 2, 0, 0))
    table.add_column(style="cyan", no_wrap=True)
    table.add_column(style="dim")

    commands = [
        ("!history \[range]", "Show conversation history (optional range, e.g. 3-7)"),
        (
            "!show <num> \[role] \[--raw|-r]",
            "Show full turn (role: user|assistant, default: both)",
        ),
        ("!delete <range>", "Delete interactions with preview + confirm"),
        ("!reset", "Wipe conversation (same as aiv -R), with confirm"),
        ("!context <path>", "Add file to context (aiv -c <path>)"),
        ("!help", "Show this help"),
        ("!quit, !exit", "End the session"),
    ]

    console.print("\n[bold cyan]aiv REPL commands[/bold cyan]\n")
    for cmd, desc in commands:
        table.add_row(cmd, desc)
    console.print(table)
    console.print(
        "\n  [dim]Ctrl-J submits a prompt (allows multiline input with Enter)[/dim]\n"
    )


def handle_command(text: str, conv_path: Path) -> bool:
    """
    Returns True if text was a !command, False otherwise.
    """
    stripped = text.strip()
    if not stripped.startswith("!"):
        return False

    parts = stripped.split(None, 1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    if cmd == "!history":
        cmd_history(args, conv_path)
    elif cmd == "!show":
        cmd_show(args, conv_path)
    elif cmd == "!delete":
        if not args.strip():
            console.print("[red]Usage: !delete <num> or !delete <start-end>[/red]")
        else:
            cmd_delete(args, conv_path)
    elif cmd == "!reset":
        cmd_reset(conv_path)
    elif cmd == "!context":
        cmd_context(args)
    elif cmd == "!help":
        cmd_help()
    elif cmd in ("!quit", "!exit"):
        raise QuitRepl()
    else:
        console.print(
            f"[red]Unknown command: {cmd}. Type !help for available commands.[/red]"
        )

    return True


def run():
    cmd_help()
    # History file lives at repo root if available, else falls back to CONFIG_DIR
    repo_root = find_repo_root()
    history_file = (repo_root if repo_root is not None else CONFIG_DIR) / ".aiv-history"
    session = PromptSession(history=FileHistory(str(history_file)))
    while True:
        conv_path = get_conversation_file()

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

        try:
            if handle_command(text, conv_path):
                continue
        except QuitRepl:
            break

        result = subprocess.run(
            ["aiv", "-C", text],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
            continue
        subprocess.run(["glow", "-"], input=result.stdout, text=True)


if __name__ == "__main__":
    run()

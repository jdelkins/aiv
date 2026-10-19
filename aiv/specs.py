from __future__ import annotations
from pathlib import Path

from dataclasses import dataclass, field
from typing import Callable

from aiv.models import (
    InteractionMode,
    Command,
    ContextCommand,
    ExtractPromptContextCommand,
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
    SetProviderCommand,
    SetApiKeyFileCommand,
    SetMaxTokensCommand,
    SetSysPromptCommand,
    SetModeCommand,
    ShowVersionCommand,
    ShowPipelineContextCommand,
    SetPromptSuffixCommand,
    SetPromptMarkerCommand,
    WorkingDirectoryCommand,
)


def _parse_context_arg(args: str) -> ContextCommand:
    """
    Parse a context argument which may be:
      - a plain glob pattern:                  "src/**/*.py"
      - stdin with no metadata:                "-" or "stdin"
      - stdin with optional metadata:          "stdin,file=foo.py,range=45:67"
      - stdin with metadata via = quoting:     "-,file=foo.py,range=45:67"
                                               (only reachable as -c=-,file=...)

    Keys are case-insensitive; order is irrelevant; unknown keys are ignored.
    range= should be "START:END" (1-indexed inclusive).
    """
    args = args.strip()
    is_stdin = (
        args == "-"
        or args == "stdin"
        or args.startswith("stdin,")
        or args.startswith("-,")
    )
    if not is_stdin:
        return ContextCommand(path=args)

    if args.startswith("stdin"):
        remainder = args[len("stdin") :]
    elif args.startswith("-,"):
        remainder = args[1:]
    else:
        remainder = ""

    meta: dict[str, str] = {}
    for part in remainder.split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            meta[k.strip().lower()] = v.strip()

    ctx_file = meta.get("file") or None
    ctx_range = meta.get("range") or None

    return ContextCommand(path="-", ctx_file=ctx_file, ctx_range=ctx_range)


def _parse_extract_arg(args: str) -> ExtractPromptContextCommand:
    """
    Same parsing logic as _parse_context_arg but produces an
    ExtractPromptContextCommand.
    """
    args = args.strip()
    is_stdin = (
        args == "-"
        or args == "stdin"
        or args.startswith("stdin,")
        or args.startswith("-,")
    )
    if not is_stdin:
        return ExtractPromptContextCommand(path=args)

    if args.startswith("stdin"):
        remainder = args[len("stdin") :]
    elif args.startswith("-,"):
        remainder = args[1:]
    else:
        remainder = ""

    meta: dict[str, str] = {}
    for part in remainder.split(","):
        if "=" in part:
            k, _, v = part.partition("=")
            meta[k.strip().lower()] = v.strip()

    ctx_file = meta.get("file") or None
    ctx_range = meta.get("range") or None

    return ExtractPromptContextCommand(path="-", ctx_file=ctx_file, ctx_range=ctx_range)


@dataclass(frozen=True)
class CommandSpec:
    names: tuple[str, ...]  # REPL dispatch keys; empty tuple = CLI-only
    help: str  # one-line description shared by !help and --help
    parse: Callable[[str], Command]  # args string -> Command (args="" for flag-only)
    usage: str = ""  # args fragment only, e.g. "[range]" — not including name
    repl_usage: str | None = None  # overrides usage in REPL !help if set
    long_option: str | None = None  # CLI long flag e.g. "--history"; None = REPL-only
    short_option: str | None = None  # CLI short flag e.g. "-H"; None = no short flag
    argparse_kwargs: dict = field(
        default_factory=dict
    )  # passed verbatim to add_argument()
    takes_path: bool = False  # completion hint: tab-complete args as filesystem path
    takes_dir: bool = False  # completion hint: tab-complete args as filesystem dirs
    precedence: int = 50  # lower runs earlier; registry order breaks ties


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# Precedence bands:
#   5   — working directory change
#   10  — destructive session reset
#   19  — provider profile selection: loads implementation type, options, model,
#         credentials, and token budget before explicit overrides
#   20  — session configuration (model, max_tokens, api-key-file, mode,
#         sys-prompt, prompt-marker)
#   25  — prompt suffix edits (after mode selection)
#   30  — context loading / extraction
#   40  — prompt
#   50  — read-only display commands
#   90  — REPL handoff / exit

COMMAND_SPECS: list[CommandSpec] = [
    CommandSpec(
        names=("!cd",),
        long_option="--working-directory",
        short_option="-d",
        usage="<dir>",
        help="Set current working directory before running commands",
        takes_dir=True,
        parse=lambda args: WorkingDirectoryCommand(
            dir=Path(args.strip()).expanduser() if args != "" else None
        ),
        argparse_kwargs=dict(nargs=1, metavar="dir"),
        precedence=5,
    ),
    CommandSpec(
        names=("!reset",),
        long_option="--reset",
        short_option="-R",
        usage="",
        help="Wipe conversation with confirm",
        parse=lambda _args: ResetCommand(),
        argparse_kwargs=dict(action="store_true"),
        precedence=10,
    ),
    CommandSpec(
        names=("!provider",),
        long_option="--provider",
        short_option="-P",
        usage="<provider>",
        repl_usage="[provider]",
        help="Select a named provider profile and load its configured defaults",
        parse=lambda args: SetProviderCommand(provider=args.strip() or None),
        argparse_kwargs=dict(default=None, metavar="PROVIDER"),
        precedence=19,
    ),
    CommandSpec(
        names=("!model",),
        long_option="--model",
        short_option="-m",
        usage="<model>",
        help="Set the model",
        parse=lambda args: SetModelCommand(model=args.strip() if args != "" else None),
        argparse_kwargs=dict(default=None, metavar="MODEL"),
        precedence=20,
    ),
    CommandSpec(
        names=("!api-key-file",),
        long_option="--api-key-file",
        short_option=None,
        usage="<file>",
        help="Read API key from file and set it for the session",
        takes_path=True,
        parse=lambda args: SetApiKeyFileCommand(path=Path(args.strip()).expanduser()),
        argparse_kwargs=dict(default=None, metavar="FILE"),
        precedence=20,
    ),
    CommandSpec(
        names=("!max-tokens",),
        long_option="--max-tokens",
        short_option=None,
        usage="<n>",
        help="Set max output tokens",
        parse=lambda args: SetMaxTokensCommand(
            max_tokens=(int(args.strip()) if args != "" else None)
        ),
        argparse_kwargs=dict(default=None, metavar="N"),
        precedence=20,
    ),
    CommandSpec(
        names=("!sys-prompt",),
        long_option="--sys-prompt",
        short_option="-s",
        usage="<prompt>",
        help="Set the system prompt",
        parse=lambda args: SetSysPromptCommand(
            sys_prompt=(args.strip() if args != "" else None)
        ),
        argparse_kwargs=dict(default=None, metavar="PROMPT"),
        precedence=20,
    ),
    CommandSpec(
        names=("!chat",),
        long_option="--chat",
        short_option="-C",
        usage="",
        help="Conversational mode (markdown enabled)",
        parse=lambda _args: SetModeCommand(mode=InteractionMode.CHAT),
        argparse_kwargs=dict(action="store_true"),
        precedence=20,
    ),
    CommandSpec(
        names=("!code",),
        long_option="--code",
        short_option="-X",
        usage="",
        help="Code-only mode (no markdown, caveats as comments)",
        parse=lambda _args: SetModeCommand(mode=InteractionMode.CODE),
        argparse_kwargs=dict(action="store_true"),
        precedence=20,
    ),
    CommandSpec(
        names=("!mode",),
        long_option=None,
        short_option=None,
        usage="[chat|code|default]",
        help="Set interaction mode (chat, code, or default/none)",
        parse=lambda args: SetModeCommand(
            mode={
                "chat": InteractionMode.CHAT,
                "code": InteractionMode.CODE,
                "default": InteractionMode.DEFAULT,
            }.get(args.strip().lower())
        ),
        precedence=20,
    ),
    CommandSpec(
        # CHAT/CODE edits are durable; other modes use an ephemeral override.
        # Run after mode selection, regardless of CLI flag order.
        names=("!suffix",),
        long_option="--prompt-suffix",
        short_option=None,
        usage="<suffix>",
        help="Set a custom prompt suffix (edits current CHAT/CODE suffix in place, or sets an ephemeral override otherwise)",
        parse=lambda args: SetPromptSuffixCommand(args.strip() if args != "" else None),
        argparse_kwargs=dict(default=None, metavar="SUFFIX"),
        precedence=25,
    ),
    CommandSpec(
        names=("!prompt-marker",),
        long_option="--prompt-marker",
        short_option=None,
        usage="<marker>",
        help="Set the prompt extraction marker string (default: '## prompt:')",
        parse=lambda args: SetPromptMarkerCommand(marker=args.strip() or None),
        argparse_kwargs=dict(default=None, metavar="MARKER"),
        precedence=20,
    ),
    CommandSpec(
        names=("!context",),
        long_option="--context",
        short_option="-c",
        usage="<file_pattern|stdin[,file=PATH][,range=L:L]>",
        repl_usage="<file_pattern>",
        help="Add context from files (glob pattern) or stdin; use 'stdin,file=PATH,range=L:L' for metadata",
        parse=_parse_context_arg,
        argparse_kwargs=dict(action="append", default=[], metavar="file_pattern"),
        takes_path=True,
        precedence=30,
    ),
    CommandSpec(
        names=("!extract",),
        long_option="--extract",
        short_option="-e",
        usage="<file_pattern|stdin[,file=PATH][,range=L:L]>",
        repl_usage="<file_pattern>",
        help="Extract prompt marker lines as prompt, add rest as context, output AI response (or passthrough if no marker)",
        parse=_parse_extract_arg,
        argparse_kwargs=dict(action="append", default=[], metavar="file_pattern"),
        takes_path=True,
        precedence=30,
    ),
    CommandSpec(
        # Bare text is a prompt; commands_from_args handles the positional CLI
        # argument separately using this spec's precedence.
        names=(),
        long_option=None,
        short_option=None,
        usage="<prompt>",
        help="Send a prompt to the model",
        parse=lambda args: PromptCommand(text=args),
        precedence=40,
    ),
    CommandSpec(
        names=("!history",),
        long_option="--history",
        short_option="-H",
        usage="[range]",
        help="Show conversation history (optional range, e.g. 3-7)",
        parse=lambda args: HistoryCommand(range=args.strip() or None),
        argparse_kwargs=dict(nargs="?", const=True, default=None, metavar="range"),
        precedence=50,
    ),
    CommandSpec(
        names=("!show",),
        long_option="--show",
        short_option="-S",
        usage="<range> [user|assistant] [--raw|-r]",
        help="Show full turn content",
        parse=lambda args: ShowCommand(args=args),
        argparse_kwargs=dict(nargs="?", const=True, default=None, metavar="range"),
        precedence=50,
    ),
    CommandSpec(
        names=("!delete",),
        long_option=None,
        short_option=None,
        usage="<range>",
        help="Delete interactions with preview + confirm",
        parse=lambda args: DeleteCommand(range=args.strip()),
        precedence=50,
    ),
    CommandSpec(
        names=("!help",),
        long_option="--help",
        short_option="-h",
        usage="",
        help="Show this help",
        parse=lambda _args: HelpCommand(),
        argparse_kwargs=dict(action="store_true"),
        precedence=50,
    ),
    CommandSpec(
        names=("!version",),
        long_option="--version",
        short_option="-v",
        usage="",
        help="Display version information",
        parse=lambda _args: ShowVersionCommand(),
        argparse_kwargs=dict(action="store_true"),
        precedence=50,
    ),
    CommandSpec(
        names=("!params",),
        long_option=None,
        short_option=None,
        usage="",
        help="Show runtime parameters",
        parse=lambda _args: ShowPipelineContextCommand(),
        precedence=50,
    ),
    CommandSpec(
        names=(),
        long_option="--repl",
        short_option="-i",
        usage="",
        help="Enter interactive REPL (after processing any prompt)",
        parse=lambda _args: ReplCommand(),
        argparse_kwargs=dict(action="store_true"),
        precedence=90,
    ),
    CommandSpec(
        names=("!quit", "!exit"),
        long_option=None,
        short_option=None,
        usage="",
        help="End the session",
        parse=lambda _args: ExitCommand(),
        precedence=90,
    ),
]


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

COMMAND_LOOKUP: dict[str, CommandSpec] = {
    name: spec for spec in COMMAND_SPECS for name in spec.names
}

OPTION_LOOKUP: dict[str, CommandSpec] = {
    spec.long_option: spec for spec in COMMAND_SPECS if spec.long_option
}

PROMPT_SPEC: CommandSpec = next(
    s
    for s in COMMAND_SPECS
    if s.long_option is None and not s.names and not s.argparse_kwargs
)

from __future__ import annotations
from pathlib import Path

from dataclasses import dataclass, field
from typing import Callable

from aiv.config import VALID_PROVIDERS
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
        remainder = args[len("stdin"):]
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
        remainder = args[len("stdin"):]
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
    precedence: int = 50  # pipeline ordering: lower runs earlier; stable sort preserves
    # registry order within equal precedence


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
# Precedence bands:
#   5   — working directory change (must run before conv_path is resolved)
#   10  — destructive session reset (must run before anything reads state)
#   19  — provider switch (must run before model/max_tokens/api-key-file, since
#         cmd_set_provider pulls that provider's configured defaults for all
#         three as a side effect of switching)
#   20  — session configuration (model, max_tokens, api-key-file, mode,
#         sys-prompt, prompt-marker) — all depend on provider already being
#         resolved, hence running strictly after band 19
#   25  — prompt suffix override (after mode, since !suffix's CHAT/CODE-in-place
#         behavior depends on ctx.mode already reflecting the current mode)
#   30  — context loading
#   40  — prompt / main action
#   50  — read-only display commands (history, show)
#   90  — REPL handoff (always last; hands off control of the process)

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
        usage=f"<{'|'.join(VALID_PROVIDERS)}>",
        help="Set the API provider",
        parse=lambda args: SetProviderCommand(
            provider=args.strip() if args != "" else None
        ),
        argparse_kwargs=dict(default=None, metavar="PROVIDER"),
        precedence=19,  # must resolve before !model/!api-key-file/!max-tokens (all
                         # 20), since cmd_set_provider pulls that provider's
                         # configured defaults for all three as a side effect
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
        # Required argument: the path itself is not retained anywhere queryable,
        # only its effect (api_key). No bare "show current value" form, unlike
        # most other Set* specs, so argparse_kwargs omits nargs="?"/const=True.
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
        # REPL-only: allows resetting mode to default mid-session
        # usage: !mode, !mode chat, !mode code, !mode default
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
            }.get(
                args.strip().lower()
            )  # unrecognised or empty -> None (display the mode)
        ),
        precedence=20,
    ),
    CommandSpec(
        # Behavior depends on ctx.mode at the time it's invoked: in CHAT/CODE
        # mode it edits that mode's persistent suffix in place (session-state
        # eligible); otherwise it sets an ephemeral CUSTOM-mode override that
        # is never persisted. See cmd_set_prompt_suffix in commands.py.
        # precedence=25 (after mode-setting commands at 20) so that e.g.
        # `aiv -X --prompt-suffix "..."` edits CODE's suffix, not DEFAULT's,
        # regardless of flag order on the command line.
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
    # PromptCommand has no REPL !-command name (bare text is a prompt) and no
    # long_option (positional args, not a flag). It lives here so commands_from_args
    # can look up its precedence and emit it into the sorted pipeline correctly.
    CommandSpec(
        names=(),  # bare text in REPL; not dispatched via COMMAND_LOOKUP
        long_option=None,  # positional, not a flag; handled specially in commands_from_args
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
        long_option=None,  # no CLI equivalent: requires interactive confirm
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
        long_option=None,  # no CLI equivalent: nonsensical outside REPL
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

# Keyed by REPL name (e.g. "!history") -> CommandSpec
COMMAND_LOOKUP: dict[str, CommandSpec] = {
    name: spec for spec in COMMAND_SPECS for name in spec.names
}

# Keyed by long_option (e.g. "--history") -> CommandSpec; excludes CLI-less specs
OPTION_LOOKUP: dict[str, CommandSpec] = {
    spec.long_option: spec for spec in COMMAND_SPECS if spec.long_option
}

# Prompt spec reference — used by commands_from_args for positional arg injection
PROMPT_SPEC: CommandSpec = next(
    s
    for s in COMMAND_SPECS
    if s.long_option is None and not s.names and not s.argparse_kwargs
)

# Caveat: no new CommandSpec entries were added for mode_chat_suffix/
# mode_code_suffix per the decision to reuse the single !suffix/--prompt-suffix
# spec for both — the branching on ctx.mode happens entirely inside
# cmd_set_prompt_suffix (commands.py), not at the spec/parsing layer. The only
# change to the !suffix spec itself is precedence 20->25 and an updated help
# string reflecting its new mode-dependent behavior.
#
# Caveat: !suffix's precedence=25 placement (after !mode/!chat/!code at 20, but
# before !context at 30) matters for a one-shot invocation like
# `aiv -X --prompt-suffix "be extra terse"` — -X (SetModeCommand->CODE) must
# resolve before --prompt-suffix so ctx.mode is already CODE when
# cmd_set_prompt_suffix runs, otherwise it would take the DEFAULT/CUSTOM branch
# instead of editing mode_code_suffix in place.

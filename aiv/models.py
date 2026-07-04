from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from aiv.config import MODE_CHAT_SUFFIX, MODE_CODE_SUFFIX


class InteractionMode(Enum):
    CHAT = "chat"
    CODE = "code"


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


@dataclass
class NoOpCommand:
    pass


@dataclass
class SetModelCommand:
    model: str | None


@dataclass
class SetMaxTokensCommand:
    max_tokens: int | None


@dataclass
class SetSysPromptCommand:
    sys_prompt: str | None


@dataclass
class SetModeCommand:
    mode: InteractionMode | None


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
    | NoOpCommand
    | SetModelCommand
    | SetMaxTokensCommand
    | SetSysPromptCommand
    | SetModeCommand
)


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    model: str = "claude-3-7-sonnet-latest"
    sys_prompt: str = ""
    mode: InteractionMode | None = None
    stdin_data: str | None = None
    api_key: str = ""
    max_tokens: int = 4096
    interactive: bool = False  # set True by run_repl_loop
    piped_stdin: bool = False  # True if stdin was a pipe at invocation
    glow_available: bool = True  # set False on first FileNotFoundError from glow
    # conv_path has no safe scalar default — it must be resolved at startup
    # via conversation.get_conversation_file() and passed explicitly.
    # Using field(default_factory=...) would silently re-resolve on every
    # instantiation (e.g. in tests), so we require it as a keyword argument.
    # Callers: cli.py main(), repl.py run_cli() (being removed), and tests.
    conv_path: Path = field(default_factory=lambda: Path(".aiv-conversation.json"))

    @property
    def mode_suffix(self) -> str:
        if self.mode == InteractionMode.CODE:
            return MODE_CODE_SUFFIX
        elif self.mode == InteractionMode.CHAT:
            return MODE_CHAT_SUFFIX
        return ""

    def consume_stdin(self) -> str | None:
        """Return stdin_data and clear it so it is only consumed once."""
        data = self.stdin_data
        self.stdin_data = None
        return data

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from aiv.common import MODE_CHAT_SUFFIX, MODE_CODE_SUFFIX


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
    model: str


@dataclass
class SetMaxTokensCommand:
    max_tokens: int


@dataclass
class SetSysPromptCommand:
    sys_prompt: str


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
    interactive: bool = False   # set True by run_repl_loop
    piped_stdin: bool = False   # True if stdin was a pipe at invocation

    @property
    def mode_suffix(self) -> str:
        if self.mode == InteractionMode.CODE:
            return MODE_CODE_SUFFIX
        elif self.mode == InteractionMode.CHAT:
            return MODE_CHAT_SUFFIX
        # None: no suffix; plain output, appropriate for piped/non-interactive use
        return ""

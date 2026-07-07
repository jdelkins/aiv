from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from aiv.config import MODE_CHAT_SUFFIX, MODE_CODE_SUFFIX


class InteractionMode(Enum):
    CHAT = "chat"
    CODE = "code"
    DEFAULT = "default"


# ---------------------------------------------------------------------------
# Command dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ContextCommand:
    path: str  # glob pattern or "-" for stdin
    ctx_file: str | None = None  # use as location hint
    ctx_range: str | None = None  # line range, e.g. "45:67"


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
class ShowVersionCommand:
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
    | ShowVersionCommand
)


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------


@dataclass
class PipelineContext:
    model: str = "claude-3-7-sonnet-latest"
    sys_prompt: str = ""
    mode: InteractionMode = InteractionMode.DEFAULT
    stdin_data: str | None = None
    api_key: str = ""
    max_tokens: int = 4096
    interactive: bool = False  # set True by run_repl_loop
    piped_stdin: bool = False  # True if stdin was a pipe at invocation
    glow_available: bool = True  # set False on first FileNotFoundError from glow
    # conv_path_override: pass an explicit Path (e.g. in tests) to skip auto-resolution.
    # Leave as None in production — get_conversation_file() is called lazily on first
    # access to ctx.conv_path, along with load_conversation + validate_conversation.
    conv_path_override: Path | None = None

    def __post_init__(self):
        self._conv_path: Path | None = None

    @property
    def conv_path(self) -> Path:
        if self._conv_path is None:
            from aiv.conversation import (
                get_conversation_file,
                load_conversation,
                validate_conversation,
            )

            path = self.conv_path_override or get_conversation_file()
            messages = load_conversation(path)
            validate_conversation(messages, path)
            self._conv_path = path
        return self._conv_path

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

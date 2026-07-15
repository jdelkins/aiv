from __future__ import annotations
import os

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from aiv.config import get_config, DEFAULT_PROMPT_MARKER


class InteractionMode(str, Enum):
    CHAT = "chat"
    CODE = "code"
    CUSTOM = "custom"
    DEFAULT = "default"


class ConversationError(Exception):
    """Raised when a conversation file fails structural validation."""
    pass


# ---------------------------------------------------------------------------
# Command dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ContextCommand:
    path: str
    ctx_file: str | None = None
    ctx_range: str | None = None


@dataclass
class ExtractPromptContextCommand:
    path: str
    ctx_file: str | None = None
    ctx_range: str | None = None


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
class ShowPipelineContextCommand:
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


@dataclass
class SetPromptSuffixCommand:
    suffix: str | None


@dataclass
class SetPromptMarkerCommand:
    marker: str | None


@dataclass
class WorkingDirectoryCommand:
    dir: Path | None


Command = (
    ContextCommand
    | ExtractPromptContextCommand
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
    | SetPromptSuffixCommand
    | SetPromptMarkerCommand
    | ShowVersionCommand
    | ShowPipelineContextCommand
    | WorkingDirectoryCommand
)


# ---------------------------------------------------------------------------
# PipelineContext
# ---------------------------------------------------------------------------


class PipelineContext:
    def __init__(
        self,
        model: str = "claude-3-7-sonnet-latest",
        sys_prompt: str = "",
        mode: InteractionMode = InteractionMode.DEFAULT,
        stdin_data: str | None = None,
        api_key: str = "",
        max_tokens: int = 4096,
        interactive: bool = False,
        piped_stdin: bool = False,
    ):
        self.model = model
        self.sys_prompt = sys_prompt
        self.stdin_data = stdin_data
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.interactive = interactive
        self.piped_stdin = piped_stdin
        self._conv_path: Path | None = None
        self._mode: InteractionMode = InteractionMode.DEFAULT
        self._mode_suffix: str | None = None
        self.mode = mode

        try:
            self.prompt_marker: str = get_config().get("prompt_marker", DEFAULT_PROMPT_MARKER)
        except FileNotFoundError:
            self.prompt_marker = DEFAULT_PROMPT_MARKER

    @property
    def conv_path(self) -> Path:
        if self._conv_path is None:
            from aiv.conversation import get_conversation_file
            self._conv_path = get_conversation_file()
        return self._conv_path

    @conv_path.setter
    def conv_path(self, path: Path | None):
        self._conv_path = path

    @property
    def mode(self) -> InteractionMode:
        return self._mode

    @mode.setter
    def mode(self, value: InteractionMode) -> None:
        self._mode = value
        self._mode_suffix = None

    @property
    def mode_suffix(self) -> str:
        if self._mode_suffix is not None:
            return self._mode_suffix
        if self._mode not in (InteractionMode.CODE, InteractionMode.CHAT):
            return ""
        config = get_config()
        if self._mode == InteractionMode.CODE:
            return config.get("mode_code_suffix", "")
        return config.get("mode_chat_suffix", "")

    @mode_suffix.setter
    def mode_suffix(self, value: str) -> None:
        self._mode_suffix = value
        self._mode = InteractionMode.CUSTOM

    @property
    def working_directory(self) -> str:
        return os.getcwd()

    @working_directory.setter
    def working_directory(self, cwd: Path) -> None:
        os.chdir(cwd)
        self._conv_path = None

    def print_summary(self, console):
        from rich.table import Table

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("field", style="cyan", no_wrap=True)
        table.add_column("value", style="white")

        try:
            mode_suffix_display = (
                repr(self.mode_suffix) if self.mode_suffix else "[dim]<empty>[/dim]"
            )
        except FileNotFoundError:
            mode_suffix_display = "[dim]<config not found>[/dim]"

        rows = [
            ("model", self.model),
            ("mode", self.mode.value),
            ("mode_suffix", mode_suffix_display),
            (
                "sys_prompt",
                repr(self.sys_prompt) if self.sys_prompt else "[dim]<empty>[/dim]",
            ),
            (
                "stdin_data",
                repr(self.stdin_data) if self.stdin_data else "[dim]<empty>[/dim]",
            ),
            ("max_tokens", str(self.max_tokens)),
            ("interactive", str(self.interactive)),
            ("piped_stdin", str(self.piped_stdin)),
            ("api_key", "***" if self.api_key else "[dim]<empty>[/dim]"),
            ("working_directory", str(self.working_directory)),
            ("conv_path", str(self.conv_path)),
            ("prompt_marker", repr(self.prompt_marker)),
        ]

        for field, value in rows:
            table.add_row(field, value)

        console.print("\n [bold blue]Runtime Parameters[/bold blue]\n")
        console.print(table)
        console.print("")

    def consume_stdin(self) -> str | None:
        data = self.stdin_data
        self.stdin_data = None
        return data

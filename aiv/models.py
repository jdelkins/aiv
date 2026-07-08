from __future__ import annotations
import sys

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from aiv.config import get_config


class InteractionMode(Enum):
    CHAT = "chat"
    CODE = "code"
    CUSTOM = "custom"
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
    | SetPromptSuffixCommand
    | ShowVersionCommand
    | ShowPipelineContextCommand
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
        interactive: bool = False,  # set True by run_repl_loop
        piped_stdin: bool = False,  # True if stdin was a pipe at invocation
        glow_available: bool = True,  # set False on first FileNotFoundError from glow
        # conv_path_override: pass an explicit Path (e.g. in tests) to skip auto-resolution.
        # Leave as None in production — get_conversation_file() is called lazily on first
        # access to ctx.conv_path, along with load_conversation + validate_conversation.
        conv_path_override: Path | None = None,
    ):
        self.model = model
        self.sys_prompt = sys_prompt
        self.stdin_data = stdin_data
        self.api_key = api_key
        self.max_tokens = max_tokens
        self.interactive = interactive
        self.piped_stdin = piped_stdin
        self.glow_available = glow_available
        self.conv_path_override = conv_path_override
        self._conv_path: Path | None = None
        self._mode: InteractionMode = InteractionMode.DEFAULT
        # None = "not explicitly set, derive lazily from mode on read"
        # str  = "explicitly overridden, use as-is"
        self._mode_suffix: str | None = None
        self.mode = mode  # run through setter to set _mode (suffix stays None)

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
    def mode(self) -> InteractionMode:
        return self._mode

    @mode.setter
    def mode(self, value: InteractionMode) -> None:
        self._mode = value
        self._mode_suffix = None  # clear override; getter will derive from mode lazily

    @property
    def mode_suffix(self) -> str:
        if self._mode_suffix is not None:
            return self._mode_suffix
        # DEFAULT and CUSTOM have no config-derived suffix — return early to
        # avoid calling get_config() in environments without a config file.
        if self._mode not in (InteractionMode.CODE, InteractionMode.CHAT):
            return ""
        # Raises FileNotFoundError — callers at the CLI boundary handle it with
        # sys.exit; __repr__ and tests catch it gracefully without calling sys.exit.
        config = get_config()
        if self._mode == InteractionMode.CODE:
            return config.get("mode_code_suffix", "")
        return config.get("mode_chat_suffix", "")

    @mode_suffix.setter
    def mode_suffix(self, value: str) -> None:
        self._mode_suffix = value
        self._mode = (
            InteractionMode.CUSTOM
        )  # directly set backing var, bypass mode.setter

    def __repr__(self) -> str:
        from rich.console import Console
        from rich.table import Table
        import io

        table = Table(
            title="Runtime Parameters", show_header=False, box=None, padding=(0, 1)
        )
        table.add_column("field", style="bold cyan", no_wrap=True)
        table.add_column("value", style="white")

        try:
            mode_suffix = self.mode_suffix
            mode_suffix_display = (
                repr(mode_suffix) if mode_suffix else "[dim]<empty>[/dim]"
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
            ("glow_available", str(self.glow_available)),
            ("api_key", "***" if self.api_key else "[dim]<empty>[/dim]"),
            (
                "conv_path_override",
                (
                    str(self.conv_path_override)
                    if self.conv_path_override
                    else "[dim]<empty>[/dim]"
                ),
            ),
        ]

        for field, value in rows:
            table.add_row(field, value)

        buf = io.StringIO()
        console = Console(file=buf, highlight=False)
        console.print(table)
        return buf.getvalue().rstrip()

    def consume_stdin(self) -> str | None:
        """Return stdin_data and clear it so it is only consumed once."""
        data = self.stdin_data
        self.stdin_data = None
        return data

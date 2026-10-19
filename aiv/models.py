from __future__ import annotations

import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from aiv.config import (
    get_config,
    DEFAULT_PROMPT_MARKER,
    DEFAULT_MODE_CHAT_SUFFIX,
    DEFAULT_MODE_CODE_SUFFIX,
    VALID_PROVIDER_TYPES,
)


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
class SetProviderCommand:
    provider: str | None


@dataclass
class SetApiKeyFileCommand:
    path: Path


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
    | SetProviderCommand
    | SetApiKeyFileCommand
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
        provider: str = "anthropic",
        sys_prompt: str = "",
        mode_chat_suffix: str = DEFAULT_MODE_CHAT_SUFFIX,
        mode_code_suffix: str = DEFAULT_MODE_CODE_SUFFIX,
        mode: InteractionMode = InteractionMode.DEFAULT,
        stdin_data: str | None = None,
        api_key: str = "",
        api_key_file: Path | None = None,
        max_tokens: int = 4096,
        interactive: bool = False,
        piped_stdin: bool = False,
        provider_type: str | None = None,
        provider_options: Mapping[str, object] | None = None,
    ):
        # Infer types only for legacy built-in names. Custom profiles must be
        # resolved by the caller, not by reading configuration here.
        if provider_type is None:
            if provider not in VALID_PROVIDER_TYPES:
                raise ValueError(
                    f"aiv: provider {provider!r} requires a resolved provider_type"
                )
            provider_type = provider
        if provider_type not in VALID_PROVIDER_TYPES:
            raise ValueError(
                f"aiv: invalid provider type {provider_type!r}; "
                f"must be one of {VALID_PROVIDER_TYPES}"
            )

        self.model = model
        # Profile identity is persisted; implementation type and options are
        # derived from configuration and never stored in session_state.
        self.provider = provider
        self.provider_type = provider_type
        self.provider_options: dict[str, object] = (
            deepcopy(dict(provider_options)) if provider_options is not None else {}
        )
        self.sys_prompt = sys_prompt
        # Callers initialize these from config; commands can edit each suffix
        # independently without forcing CUSTOM mode.
        self.mode_chat_suffix = mode_chat_suffix
        self.mode_code_suffix = mode_code_suffix
        self.stdin_data = stdin_data
        self.api_key = api_key
        # Effective key-file path, including a configured default if applicable.
        # None means no file-backed credential is active. Only a path differing
        # from the profile default is persisted; key material is never persisted.
        self.api_key_file = api_key_file
        self.max_tokens = max_tokens
        self.interactive = interactive
        self.piped_stdin = piped_stdin
        self._conv_path: Path | None = None
        self._mode: InteractionMode = InteractionMode.DEFAULT
        self._mode_suffix: str | None = None
        self.mode = mode

        try:
            self.prompt_marker: str = get_config().get(
                "prompt_marker", DEFAULT_PROMPT_MARKER
            )
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
        """Resolve the suffix for the active mode.

        CUSTOM overrides are ephemeral. CHAT and CODE suffixes are independent
        fields whose edits are eligible for session-state persistence.
        """
        if self._mode_suffix is not None:
            return self._mode_suffix
        if self._mode == InteractionMode.CODE:
            return self.mode_code_suffix
        if self._mode == InteractionMode.CHAT:
            return self.mode_chat_suffix
        return ""

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
        from rich.markup import escape
        from rich.table import Table

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("field", style="cyan", no_wrap=True)
        table.add_column("value", style="white")

        rows = [
            ("provider", escape(self.provider)),
            ("provider_type", escape(self.provider_type)),
            ("provider_options", escape(repr(self.provider_options))),
            ("model", escape(self.model)),
            ("mode", escape(self.mode.value)),
            (
                "mode_suffix",
                escape(repr(self.mode_suffix))
                if self.mode_suffix
                else "[dim]<empty>[/dim]",
            ),
            ("mode_chat_suffix", escape(repr(self.mode_chat_suffix))),
            ("mode_code_suffix", escape(repr(self.mode_code_suffix))),
            (
                "sys_prompt",
                escape(repr(self.sys_prompt))
                if self.sys_prompt
                else "[dim]<empty>[/dim]",
            ),
            (
                "stdin_data",
                escape(repr(self.stdin_data))
                if self.stdin_data
                else "[dim]<empty>[/dim]",
            ),
            ("max_tokens", str(self.max_tokens)),
            ("interactive", str(self.interactive)),
            ("piped_stdin", str(self.piped_stdin)),
            ("api_key", "***" if self.api_key else "[dim]<empty>[/dim]"),
            (
                "api_key_file",
                escape(str(self.api_key_file))
                if self.api_key_file
                else "[dim]<default>[/dim]",
            ),
            ("working_directory", escape(self.working_directory)),
            ("conv_path", escape(str(self.conv_path))),
            ("prompt_marker", escape(repr(self.prompt_marker))),
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

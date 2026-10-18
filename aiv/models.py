from __future__ import annotations
import os

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from aiv.config import (
    get_config,
    DEFAULT_PROMPT_MARKER,
    DEFAULT_MODE_CHAT_SUFFIX,
    DEFAULT_MODE_CODE_SUFFIX,
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
    ):
        self.model = model
        self.provider = provider
        self.sys_prompt = sys_prompt
        # Real, independently-settable fields now (previously read live from
        # get_config() inside the mode_suffix property on every access). This
        # is what lets !suffix edit CHAT/CODE mode's suffix in place without
        # forcing CUSTOM mode, and what session_state diffing compares against
        # config defaults. Callers (cli.py) are expected to source the initial
        # values from get_config(), same as sys_prompt already does.
        self.mode_chat_suffix = mode_chat_suffix
        self.mode_code_suffix = mode_code_suffix
        self.stdin_data = stdin_data
        self.api_key = api_key
        # Path to the api_key_file currently in effect, if any — None means the
        # resolved provider's config default (or inline api_key) is in use, not
        # an explicit !api-key-file/--api-key-file override. Distinct from
        # api_key itself: this is what gets diffed against config defaults and
        # persisted to session_state, since the raw key material is never
        # written to the conversation file.
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
        """
        Resolves the suffix to append for the current mode. CUSTOM mode (set
        via the mode_suffix setter below) takes priority and is intentionally
        never persisted anywhere — it's a purely in-memory, per-session
        override (e.g. REPL's `!mode default` + `!suffix ...` workflow). CHAT
        and CODE modes read their own independently-settable fields, which ARE
        eligible for session_state persistence (see commands.py's
        _sync_session_state) since !suffix edits them in place without
        forcing CUSTOM when a mode is already active.
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
        from rich.table import Table

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("field", style="cyan", no_wrap=True)
        table.add_column("value", style="white")

        rows = [
            ("provider", self.provider),
            ("model", self.model),
            ("mode", self.mode.value),
            (
                "mode_suffix",
                repr(self.mode_suffix) if self.mode_suffix else "[dim]<empty>[/dim]",
            ),
            ("mode_chat_suffix", repr(self.mode_chat_suffix)),
            ("mode_code_suffix", repr(self.mode_code_suffix)),
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
            (
                "api_key_file",
                str(self.api_key_file) if self.api_key_file else "[dim]<default>[/dim]",
            ),
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


# Caveat: mode_suffix's property getter no longer calls get_config() at all, and
# can no longer raise FileNotFoundError — print_summary's prior try/except around
# mode_suffix access has been removed accordingly. cli.py MUST now pass
# mode_chat_suffix/mode_code_suffix explicitly when constructing PipelineContext
# (sourced from get_config(), same as sys_prompt already is) rather than relying
# on the old lazy-config-read behavior; if cli.py isn't updated, every ctx will
# silently fall back to this module's import-time DEFAULT_MODE_CHAT_SUFFIX/
# DEFAULT_MODE_CODE_SUFFIX constructor defaults instead of the user's configured
# values. This is addressed in the cli.py pass later in this sequence.
#
# Caveat: no new SetModeChatSuffixCommand/SetModeCodeSuffixCommand dataclasses
# were added, per the decision to keep a single !suffix command — commands.py's
# cmd_set_prompt_suffix is expected to branch on ctx.mode and write directly to
# ctx.mode_chat_suffix/ctx.mode_code_suffix when mode is CHAT/CODE, or fall
# through to the mode_suffix setter (unchanged CUSTOM-forcing path) otherwise.

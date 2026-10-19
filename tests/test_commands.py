from __future__ import annotations
import os
import json
import argparse
from copy import deepcopy
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from rich.console import Console

from aiv.models import (
    PipelineContext,
    InteractionMode,
    PromptCommand,
    HistoryCommand,
    ShowCommand,
    ContextCommand,
    ExtractPromptContextCommand,
    SetModeCommand,
    SetPromptSuffixCommand,
    ResetCommand,
    ReplCommand,
    ShowVersionCommand,
    SetModelCommand,
    SetProviderCommand,
    SetApiKeyFileCommand,
    SetMaxTokensCommand,
    SetSysPromptCommand,
)
from aiv.commands import (
    commands_from_args,
    render_output,
    StopPipeline,
    _adjust_range,
    _apply_leading_ws,
    cmd_extract_prompt_context,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_conv_path(tmp_path) -> Path:
    return tmp_path / "conversation.json"


@pytest.fixture
def ctx(tmp_conv_path) -> PipelineContext:
    ctx = PipelineContext(api_key="test")
    ctx.conv_path = tmp_conv_path
    return ctx


@pytest.fixture(autouse=True)
def restore_cwd():
    original = os.getcwd()
    yield
    os.chdir(original)


def make_args(**kwargs) -> argparse.Namespace:
    defaults = dict(
        prompt=[],
        reset=False,
        model=None,
        provider=None,
        api_key_file=None,
        max_tokens=None,
        sys_prompt=None,
        prompt_suffix=None,
        chat=False,
        code=False,
        context=[],
        extract=[],
        history=None,
        show=None,
        help=False,
        repl=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


_MOCK_CONFIG = {
    "prompt_marker": "## prompt:",
    "mode_code_suffix": "\n\nRespond with CODE ONLY.",
    "mode_chat_suffix": "\n\nRespond using markdown.",
    "sys_prompt": "You are a test assistant.",
}


@pytest.fixture(autouse=True)
def patch_get_config():
    with patch("aiv.models.get_config", return_value=_MOCK_CONFIG):
        yield


@pytest.fixture
def tmp_conv(tmp_path):
    ctx = PipelineContext(
        model="claude-test",
        api_key="test-key",
        mode=InteractionMode.CODE,
    )
    ctx.conv_path = tmp_path / "conversation.json"
    ctx.prompt_marker = "## prompt:"
    return ctx


def _read_conv(ctx: PipelineContext) -> list:
    return _read_full(ctx).get("messages", [])


def _read_full(ctx: PipelineContext) -> dict:
    if not ctx.conv_path.exists():
        return {}
    return json.loads(ctx.conv_path.read_text())


# ---------------------------------------------------------------------------
# Provider/session_state test fixtures
# ---------------------------------------------------------------------------

# anthropic matches PipelineContext's constructor defaults so unrelated setter
# tests do not produce spurious model/max_tokens diffs.
_MOCK_PROVIDER_SETTINGS = {
    "anthropic": {
        "type": "anthropic",
        "api_key": "anthropic-key",
        "api_key_file": None,
        "model": "claude-3-7-sonnet-latest",
        "max_tokens": 4096,
        "options": {},
    },
    "openai": {
        "type": "openai",
        "api_key": "openai-key",
        "api_key_file": "/configured/openai-key-file",
        "model": "gpt-default",
        "max_tokens": 8192,
        "options": {},
    },
    "openai-reasoning": {
        "type": "openai-reasoning",
        "api_key": "openai-key",
        "api_key_file": "/configured/openai-key-file",
        "model": "o3-default",
        "max_tokens": 16384,
        "options": {},
    },
    "deep": {
        "type": "openai-reasoning",
        "api_key": "deep-key",
        "api_key_file": None,
        "model": "o3-deep",
        "max_tokens": 16384,
        "options": {"reasoning_effort": "high"},
    },
    "quick": {
        "type": "openai-reasoning",
        "api_key": "quick-key",
        "api_key_file": None,
        "model": "o3-quick",
        "max_tokens": 4096,
        "options": {"reasoning_effort": "low"},
    },
    "unconfigured": {
        "type": "openai",
        "api_key": None,
        "api_key_file": None,
        "model": None,
        "max_tokens": 4096,
        "options": {},
    },
}


def _fake_get_provider_settings(provider: str) -> dict:
    if provider not in _MOCK_PROVIDER_SETTINGS:
        raise ValueError(f"aiv: unknown provider {provider!r}")
    return deepcopy(_MOCK_PROVIDER_SETTINGS[provider])


@pytest.fixture
def patch_provider_config():
    # Match the constructor's global defaults while avoiding real config I/O.
    with (
        patch(
            "aiv.commands.get_config",
            return_value={"provider": "anthropic", "sys_prompt": ""},
        ),
        patch(
            "aiv.commands.get_provider_settings",
            side_effect=_fake_get_provider_settings,
        ) as resolver,
    ):
        yield resolver


# ---------------------------------------------------------------------------
# commands_from_args
# ---------------------------------------------------------------------------


class TestCommandsFromArgs:
    def test_no_args_produces_repl(self):
        cmds = commands_from_args(make_args())
        assert len(cmds) == 1
        assert isinstance(cmds[0], ReplCommand)

    def test_version_flag(self):
        cmds = commands_from_args(make_args(version=True))
        assert len(cmds) == 1
        assert isinstance(cmds[0], ShowVersionCommand)

    def test_prompt_only(self):
        cmds = commands_from_args(make_args(prompt=["hello", "world"]))
        assert len(cmds) == 1
        assert isinstance(cmds[0], PromptCommand)
        assert cmds[0].text == "hello world"

    def test_chat_flag(self):
        cmds = commands_from_args(make_args(chat=True))
        assert len(cmds) == 1
        assert isinstance(cmds[0], SetModeCommand)
        assert cmds[0].mode == InteractionMode.CHAT

    def test_code_flag(self):
        cmds = commands_from_args(make_args(code=True))
        assert len(cmds) == 1
        assert isinstance(cmds[0], SetModeCommand)
        assert cmds[0].mode == InteractionMode.CODE

    def test_reset_flag(self):
        cmds = commands_from_args(make_args(reset=True))
        assert len(cmds) == 1
        assert isinstance(cmds[0], ResetCommand)

    def test_repl_flag(self):
        cmds = commands_from_args(make_args(repl=True))
        assert len(cmds) == 1
        assert isinstance(cmds[0], ReplCommand)

    def test_single_context(self):
        cmds = commands_from_args(make_args(context=["foo.py"]))
        assert len(cmds) == 1
        assert isinstance(cmds[0], ContextCommand)
        assert cmds[0].path == "foo.py"

    def test_multiple_context_flags(self):
        cmds = commands_from_args(make_args(context=["foo.py", "bar.py"]))
        assert len(cmds) == 2
        assert all(isinstance(c, ContextCommand) for c in cmds)
        assert cmds[0].path == "foo.py"
        assert cmds[1].path == "bar.py"

    def test_history_no_arg(self):
        cmds = commands_from_args(make_args(history=True))
        assert len(cmds) == 1
        assert isinstance(cmds[0], HistoryCommand)
        assert cmds[0].range is None

    def test_history_with_range(self):
        cmds = commands_from_args(make_args(history="3-7"))
        assert len(cmds) == 1
        assert isinstance(cmds[0], HistoryCommand)
        assert cmds[0].range == "3-7"

    def test_show_no_arg(self):
        cmds = commands_from_args(make_args(show=True))
        assert len(cmds) == 1
        assert isinstance(cmds[0], ShowCommand)
        assert cmds[0].args == ""

    def test_show_with_arg(self):
        cmds = commands_from_args(make_args(show="2 user"))
        assert len(cmds) == 1
        assert isinstance(cmds[0], ShowCommand)
        assert cmds[0].args == "2 user"

    @pytest.mark.parametrize("provider", ["openai", "deep"])
    def test_provider_flag(self, provider):
        cmds = commands_from_args(make_args(provider=provider))
        assert len(cmds) == 1
        assert isinstance(cmds[0], SetProviderCommand)
        assert cmds[0].provider == provider

    def test_api_key_file_flag(self, tmp_path):
        key_file = str(tmp_path / "key.txt")
        cmds = commands_from_args(make_args(api_key_file=key_file))
        assert len(cmds) == 1
        assert isinstance(cmds[0], SetApiKeyFileCommand)
        assert cmds[0].path == Path(key_file).expanduser()

    def test_provider_precedence_before_model(self):
        cmds = commands_from_args(make_args(provider="deep", model="custom-model"))
        assert isinstance(cmds[0], SetProviderCommand)
        assert isinstance(cmds[1], SetModelCommand)

    def test_provider_precedence_before_api_key_file(self, tmp_path):
        cmds = commands_from_args(
            make_args(provider="deep", api_key_file=str(tmp_path / "key.txt"))
        )
        assert isinstance(cmds[0], SetProviderCommand)
        assert isinstance(cmds[1], SetApiKeyFileCommand)

    def test_provider_precedence_before_max_tokens(self):
        cmds = commands_from_args(make_args(provider="deep", max_tokens="9000"))
        assert isinstance(cmds[0], SetProviderCommand)
        assert isinstance(cmds[1], SetMaxTokensCommand)

    def test_mode_precedence_before_prompt_suffix(self):
        cmds = commands_from_args(make_args(code=True, prompt_suffix="be terse"))
        assert isinstance(cmds[0], SetModeCommand)
        assert isinstance(cmds[1], SetPromptSuffixCommand)

    def test_precedence_ordering(self):
        cmds = commands_from_args(
            make_args(
                reset=True,
                chat=True,
                context=["foo.py"],
                prompt=["hello"],
            )
        )
        assert isinstance(cmds[0], ResetCommand)
        assert isinstance(cmds[1], SetModeCommand)
        assert isinstance(cmds[2], ContextCommand)
        assert isinstance(cmds[3], PromptCommand)

    def test_repl_comes_last(self):
        cmds = commands_from_args(make_args(prompt=["hello"], repl=True))
        assert isinstance(cmds[-1], ReplCommand)

    def test_extract_flag_produces_extract_command(self):
        cmds = commands_from_args(make_args(extract=["stdin,file=flake.nix,range=3:7"]))
        assert len(cmds) == 1
        assert isinstance(cmds[0], ExtractPromptContextCommand)
        assert cmds[0].path == "-"
        assert cmds[0].ctx_file == "flake.nix"
        assert cmds[0].ctx_range == "3:7"

    def test_extract_file_path(self):
        cmds = commands_from_args(make_args(extract=["src/foo.py"]))
        assert len(cmds) == 1
        assert isinstance(cmds[0], ExtractPromptContextCommand)
        assert cmds[0].path == "src/foo.py"


# ---------------------------------------------------------------------------
# render_output
# ---------------------------------------------------------------------------

MARKDOWN_TEXT = "```python\nprint('hello')\n```"
PLAIN_TEXT = "just some plain text with no markdown"


class TestRenderOutput:
    def test_plain_text_prints_directly(self, ctx, capsys):
        render_output(PLAIN_TEXT, InteractionMode.DEFAULT, ctx)
        assert PLAIN_TEXT in capsys.readouterr().out

    def test_code_mode_always_prints_directly(self, ctx, capsys):
        ctx.mode = InteractionMode.CODE
        render_output(MARKDOWN_TEXT, InteractionMode.CODE, ctx)
        assert MARKDOWN_TEXT in capsys.readouterr().out

    def test_markdown_rendered_in_chat_mode(self, ctx):
        ctx.mode = InteractionMode.CHAT
        with patch("aiv.commands.console") as mock_console:
            render_output(MARKDOWN_TEXT, InteractionMode.CHAT, ctx)
            mock_console.print.assert_called_once()

    def test_markdown_rendered_in_default_mode(self, ctx):
        assert ctx.mode == InteractionMode.DEFAULT
        with patch("aiv.commands.console") as mock_console:
            render_output(MARKDOWN_TEXT, InteractionMode.DEFAULT, ctx)
            mock_console.print.assert_called_once()

    def test_markdown_rendered_in_custom_mode(self, ctx):
        ctx.mode_suffix = "respond tersely"
        assert ctx.mode == InteractionMode.CUSTOM
        with patch("aiv.commands.console") as mock_console:
            render_output(MARKDOWN_TEXT, InteractionMode.CUSTOM, ctx)
            mock_console.print.assert_called_once()


# ---------------------------------------------------------------------------
# PipelineContext profile fields
# ---------------------------------------------------------------------------


class TestPipelineContextProvider:
    @pytest.mark.parametrize("provider", ["anthropic", "openai", "openai-reasoning"])
    def test_builtin_name_infers_type(self, provider):
        context = PipelineContext(provider=provider)
        assert context.provider_type == provider
        assert context.provider_options == {}

    def test_custom_name_requires_resolved_type(self):
        with pytest.raises(ValueError, match="requires a resolved provider_type"):
            PipelineContext(provider="deep")

    def test_invalid_type_is_rejected(self):
        with pytest.raises(ValueError, match="invalid provider type"):
            PipelineContext(provider="deep", provider_type="unsupported")

    def test_explicit_type_takes_precedence_over_name(self):
        context = PipelineContext(
            provider="openai",
            provider_type="openai-reasoning",
        )
        assert context.provider_type == "openai-reasoning"

    def test_options_are_deep_copied(self):
        options = {"nested": {"value": "original"}}
        context = PipelineContext(
            provider="deep",
            provider_type="openai-reasoning",
            provider_options=options,
        )
        context.provider_options["nested"]["value"] = "changed"
        assert options == {"nested": {"value": "original"}}

    def test_default_options_are_not_shared(self):
        first = PipelineContext()
        second = PipelineContext()
        first.provider_options["test"] = True
        assert second.provider_options == {}

    def test_summary_displays_literal_profile_fields(self, ctx):
        ctx.provider = "[bold]deep[/bold]"
        ctx.provider_type = "openai-reasoning"
        ctx.provider_options = {"reasoning_effort": "[red]high[/red]"}
        output = StringIO()
        console = Console(file=output, width=200, color_system=None)

        ctx.print_summary(console)

        text = output.getvalue()
        assert "[bold]deep[/bold]" in text
        assert "provider_type" in text
        assert "openai-reasoning" in text
        assert "provider_options" in text
        assert "[red]high[/red]" in text


# ---------------------------------------------------------------------------
# PipelineContext mode / mode_suffix interaction
# ---------------------------------------------------------------------------


class TestPipelineContextMode:
    def test_default_mode_suffix_is_empty(self, ctx):
        assert ctx.mode == InteractionMode.DEFAULT
        assert ctx.mode_suffix == ""

    def test_setting_mode_suffix_sets_custom_mode(self, ctx):
        ctx.mode_suffix = "be concise"
        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == "be concise"

    def test_setting_mode_clears_custom_suffix(self, ctx):
        ctx.mode_suffix = "be concise"
        assert ctx.mode == InteractionMode.CUSTOM
        ctx.mode = InteractionMode.DEFAULT
        assert ctx.mode == InteractionMode.DEFAULT
        assert ctx.mode_suffix == ""

    def test_setting_mode_to_custom_clears_suffix(self, ctx):
        ctx.mode_suffix = "be concise"
        ctx.mode = InteractionMode.CUSTOM
        assert ctx.mode_suffix == ""

    def test_mode_suffix_setter_prepends_newlines_via_cmd(self, ctx):
        from aiv.commands import cmd_set_prompt_suffix

        cmd_set_prompt_suffix(
            SetPromptSuffixCommand(suffix="respond in bullet points"), ctx
        )
        assert ctx.mode_suffix == "\n\nrespond in bullet points"
        assert ctx.mode == InteractionMode.CUSTOM

    def test_mode_suffix_none_suffix_is_noop(self, ctx):
        from aiv.commands import cmd_set_prompt_suffix

        original_mode = ctx.mode
        original_suffix = ctx.mode_suffix
        cmd_set_prompt_suffix(SetPromptSuffixCommand(suffix=None), ctx)
        assert ctx.mode == original_mode
        assert ctx.mode_suffix == original_suffix

    def test_resetting_mode_after_custom_suffix(self, ctx):
        ctx.mode_suffix = "\n\nbe terse"
        ctx.mode = InteractionMode.DEFAULT
        assert ctx.mode == InteractionMode.DEFAULT
        assert ctx.mode_suffix == ""

    def test_custom_suffix_survives_unrelated_ctx_changes(self, ctx):
        ctx.mode_suffix = "custom instructions"
        ctx.model = "claude-3-5-haiku-latest"
        ctx.max_tokens = 1024
        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == "custom instructions"

    def test_overwriting_suffix_stays_custom(self, ctx):
        ctx.mode_suffix = "first suffix"
        ctx.mode_suffix = "second suffix"
        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == "second suffix"

    def test_clearing_suffix_with_empty_string(self, ctx):
        ctx.mode_suffix = "something"
        ctx.mode_suffix = ""
        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == ""

    def test_code_mode_suffix_reads_ctx_field(self, tmp_conv_path):
        ctx = PipelineContext(api_key="test", mode_code_suffix="# code only")
        ctx.conv_path = tmp_conv_path
        ctx.mode = InteractionMode.CODE
        assert ctx.mode_suffix == "# code only"

    def test_chat_mode_suffix_reads_ctx_field(self, tmp_conv_path):
        ctx = PipelineContext(api_key="test", mode_chat_suffix="be friendly")
        ctx.conv_path = tmp_conv_path
        ctx.mode = InteractionMode.CHAT
        assert ctx.mode_suffix == "be friendly"

    def test_code_mode_suffix_empty_field_returns_empty(self, tmp_conv_path):
        ctx = PipelineContext(api_key="test", mode_code_suffix="")
        ctx.conv_path = tmp_conv_path
        ctx.mode = InteractionMode.CODE
        assert ctx.mode_suffix == ""

    def test_chat_mode_suffix_empty_field_returns_empty(self, tmp_conv_path):
        ctx = PipelineContext(api_key="test", mode_chat_suffix="")
        ctx.conv_path = tmp_conv_path
        ctx.mode = InteractionMode.CHAT
        assert ctx.mode_suffix == ""


# ---------------------------------------------------------------------------
# cmd_set_mode
# ---------------------------------------------------------------------------


class TestCmdSetMode:
    def test_set_mode_updates_ctx(self, ctx):
        from aiv.commands import cmd_set_mode

        cmd_set_mode(SetModeCommand(mode=InteractionMode.CODE), ctx)
        assert ctx.mode == InteractionMode.CODE

    def test_set_mode_none_is_noop(self, ctx):
        from aiv.commands import cmd_set_mode

        cmd_set_mode(SetModeCommand(mode=None), ctx)
        assert ctx.mode == InteractionMode.DEFAULT

    def test_set_mode_clears_prior_custom_suffix(self, ctx):
        from aiv.commands import cmd_set_mode

        ctx.mode_suffix = "custom stuff"
        cmd_set_mode(SetModeCommand(mode=InteractionMode.DEFAULT), ctx)
        assert ctx.mode == InteractionMode.DEFAULT
        assert ctx.mode_suffix == ""


# ---------------------------------------------------------------------------
# cmd_set_model / cmd_set_max_tokens / cmd_set_sys_prompt
# ---------------------------------------------------------------------------


class TestCmdSetters:
    def test_set_model(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_model

        cmd_set_model(SetModelCommand(model="claude-3-5-haiku-latest"), ctx)
        assert ctx.model == "claude-3-5-haiku-latest"

    def test_set_model_none_is_noop(self, ctx):
        from aiv.commands import cmd_set_model

        original = ctx.model
        cmd_set_model(SetModelCommand(model=None), ctx)
        assert ctx.model == original

    def test_set_max_tokens(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_max_tokens

        cmd_set_max_tokens(SetMaxTokensCommand(max_tokens=1024), ctx)
        assert ctx.max_tokens == 1024

    def test_set_max_tokens_none_is_noop(self, ctx):
        from aiv.commands import cmd_set_max_tokens

        original = ctx.max_tokens
        cmd_set_max_tokens(SetMaxTokensCommand(max_tokens=None), ctx)
        assert ctx.max_tokens == original

    def test_set_max_tokens_persists_diff(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_max_tokens

        cmd_set_max_tokens(SetMaxTokensCommand(max_tokens=777), ctx)
        assert _read_full(ctx)["session_state"]["max_tokens"] == 777

    def test_set_max_tokens_matching_default_omits_session_state(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_max_tokens

        cmd_set_max_tokens(SetMaxTokensCommand(max_tokens=4096), ctx)
        assert "session_state" not in _read_full(ctx)

    def test_set_sys_prompt(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_sys_prompt

        cmd_set_sys_prompt(SetSysPromptCommand(sys_prompt="you are a pirate"), ctx)
        assert ctx.sys_prompt == "you are a pirate"

    def test_set_sys_prompt_none_is_noop(self, ctx):
        from aiv.commands import cmd_set_sys_prompt

        original = ctx.sys_prompt
        cmd_set_sys_prompt(SetSysPromptCommand(sys_prompt=None), ctx)
        assert ctx.sys_prompt == original

    def test_set_sys_prompt_persists_diff(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_sys_prompt

        cmd_set_sys_prompt(SetSysPromptCommand(sys_prompt="you are a pirate"), ctx)
        assert _read_full(ctx)["session_state"]["sys_prompt"] == "you are a pirate"


# ---------------------------------------------------------------------------
# cmd_set_provider
# ---------------------------------------------------------------------------


class TestCmdSetProvider:
    def test_set_provider_updates_model_key_and_max_tokens(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        assert ctx.provider == "openai"
        assert ctx.provider_type == "openai"
        assert ctx.provider_options == {}
        assert ctx.model == "gpt-default"
        assert ctx.api_key == "openai-key"
        assert ctx.api_key_file == Path("/configured/openai-key-file")
        assert ctx.max_tokens == 8192

    def test_set_provider_none_is_noop(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider

        original = deepcopy(vars(ctx))
        cmd_set_provider(SetProviderCommand(provider=None), ctx)
        assert vars(ctx) == original
        patch_provider_config.assert_not_called()
        assert not ctx.conv_path.exists()

    def test_set_provider_invalid_is_rejected(self, ctx, patch_provider_config, capsys):
        from aiv.commands import cmd_set_provider

        original = deepcopy(vars(ctx))
        with pytest.raises(StopPipeline):
            cmd_set_provider(SetProviderCommand(provider="not-a-real-provider"), ctx)
        assert vars(ctx) == original
        assert not ctx.conv_path.exists()
        assert "unknown provider" in capsys.readouterr().err

    def test_invalid_provider_preserves_existing_state(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        original_context = deepcopy(vars(ctx))
        original_file = ctx.conv_path.read_bytes()

        with pytest.raises(StopPipeline):
            cmd_set_provider(SetProviderCommand(provider="typo"), ctx)

        assert vars(ctx) == original_context
        assert ctx.conv_path.read_bytes() == original_file

    def test_invalid_provider_stops_pipeline_before_prompt(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider, run_pipeline

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        original_context = deepcopy(vars(ctx))
        original_file = ctx.conv_path.read_bytes()

        with patch("aiv.commands.run_turn") as mock_turn:
            with pytest.raises(SystemExit) as exc:
                run_pipeline(
                    [
                        SetProviderCommand(provider="typo"),
                        PromptCommand(text="Must not be sent"),
                    ],
                    ctx,
                )

        assert exc.value.code == 1
        mock_turn.assert_not_called()
        assert vars(ctx) == original_context
        assert ctx.conv_path.read_bytes() == original_file

    def test_set_provider_persists_session_state_diff(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        assert _read_full(ctx)["session_state"] == {"provider": "openai"}

    def test_default_provider_omits_session_state(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="anthropic"), ctx)
        assert "session_state" not in _read_full(ctx)

    def test_switching_back_to_default_clears_session_state(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        cmd_set_provider(SetProviderCommand(provider="anthropic"), ctx)
        assert "session_state" not in _read_full(ctx)

    def test_switching_provider_drops_prior_model_override(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider, cmd_set_model

        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        cmd_set_model(SetModelCommand(model="custom-model"), ctx)
        cmd_set_provider(SetProviderCommand(provider="anthropic"), ctx)
        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        assert ctx.model == "gpt-default"

    def test_switching_provider_drops_prior_max_tokens_override(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider, cmd_set_max_tokens

        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        cmd_set_max_tokens(SetMaxTokensCommand(max_tokens=99999), ctx)
        cmd_set_provider(SetProviderCommand(provider="anthropic"), ctx)
        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        assert ctx.max_tokens == 8192

    def test_custom_profile_sets_type_and_options(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)

        assert ctx.provider == "deep"
        assert ctx.provider_type == "openai-reasoning"
        assert ctx.provider_options == {"reasoning_effort": "high"}
        assert ctx.model == "o3-deep"
        assert ctx.api_key == "deep-key"
        assert ctx.max_tokens == 16384
        assert _read_full(ctx)["session_state"] == {"provider": "deep"}

    def test_switch_between_profiles_of_same_type(
        self, ctx, patch_provider_config, tmp_path
    ):
        from aiv.commands import (
            cmd_set_provider,
            cmd_set_model,
            cmd_set_max_tokens,
            cmd_set_api_key_file,
        )

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        cmd_set_model(SetModelCommand(model="custom"), ctx)
        cmd_set_max_tokens(SetMaxTokensCommand(max_tokens=99999), ctx)
        key_file = tmp_path / "override.key"
        key_file.write_text("override-key\n")
        cmd_set_api_key_file(SetApiKeyFileCommand(path=key_file), ctx)

        cmd_set_provider(SetProviderCommand(provider="quick"), ctx)

        assert ctx.provider == "quick"
        assert ctx.provider_type == "openai-reasoning"
        assert ctx.provider_options == {"reasoning_effort": "low"}
        assert ctx.model == "o3-quick"
        assert ctx.api_key == "quick-key"
        assert ctx.api_key_file is None
        assert ctx.max_tokens == 4096
        assert _read_full(ctx)["session_state"] == {"provider": "quick"}

    def test_selecting_same_profile_reloads_defaults(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider, cmd_set_model

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        cmd_set_model(SetModelCommand(model="custom"), ctx)
        ctx.provider_options["reasoning_effort"] = "low"

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)

        assert ctx.model == "o3-deep"
        assert ctx.provider_options == {"reasoning_effort": "high"}
        assert _read_full(ctx)["session_state"] == {"provider": "deep"}

    def test_missing_profile_values_clear_prior_model_and_key(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        cmd_set_provider(SetProviderCommand(provider="unconfigured"), ctx)

        assert ctx.provider == "unconfigured"
        assert ctx.provider_type == "openai"
        assert ctx.provider_options == {}
        assert ctx.model == ""
        assert ctx.api_key == ""
        assert ctx.api_key_file is None
        assert _read_full(ctx)["session_state"] == {"provider": "unconfigured"}

    def test_switch_to_other_type_clears_options(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        cmd_set_provider(SetProviderCommand(provider="anthropic"), ctx)

        assert ctx.provider_type == "anthropic"
        assert ctx.provider_options == {}

    def test_options_are_copied_from_resolver(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider

        settings = _fake_get_provider_settings("deep")
        settings["options"] = {"nested": {"value": "original"}}
        patch_provider_config.side_effect = None
        patch_provider_config.return_value = settings

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        ctx.provider_options["nested"]["value"] = "changed"

        assert settings["options"] == {"nested": {"value": "original"}}

    def test_invalid_resolved_budget_does_not_mutate_context(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider

        settings = _fake_get_provider_settings("deep")
        settings["max_tokens"] = "invalid"
        patch_provider_config.side_effect = None
        patch_provider_config.return_value = settings
        original = deepcopy(vars(ctx))

        with pytest.raises(StopPipeline):
            cmd_set_provider(SetProviderCommand(provider="deep"), ctx)

        assert vars(ctx) == original
        assert not ctx.conv_path.exists()


# ---------------------------------------------------------------------------
# cmd_set_api_key_file
# ---------------------------------------------------------------------------


class TestCmdSetApiKeyFile:
    def test_sets_api_key_and_file(self, ctx, tmp_path, patch_provider_config):
        from aiv.commands import cmd_set_api_key_file

        key_file = tmp_path / "key.txt"
        key_file.write_text("secret-key-value\n")
        cmd_set_api_key_file(SetApiKeyFileCommand(path=key_file), ctx)
        assert ctx.api_key == "secret-key-value"
        assert ctx.api_key_file == key_file

    def test_missing_file_is_rejected(self, ctx, tmp_path, patch_provider_config):
        from aiv.commands import cmd_set_api_key_file

        original_key = ctx.api_key
        cmd_set_api_key_file(
            SetApiKeyFileCommand(path=tmp_path / "nonexistent.txt"), ctx
        )
        assert ctx.api_key == original_key
        assert ctx.api_key_file is None

    def test_missing_file_does_not_touch_conversation_file(
        self, ctx, tmp_path, patch_provider_config
    ):
        from aiv.commands import cmd_set_api_key_file

        cmd_set_api_key_file(
            SetApiKeyFileCommand(path=tmp_path / "nonexistent.txt"), ctx
        )
        assert not ctx.conv_path.exists()

    def test_valid_file_persists_session_state(
        self, ctx, tmp_path, patch_provider_config
    ):
        from aiv.commands import cmd_set_api_key_file

        key_file = tmp_path / "key.txt"
        key_file.write_text("secret\n")
        cmd_set_api_key_file(SetApiKeyFileCommand(path=key_file), ctx)
        state = _read_full(ctx)["session_state"]
        assert state["api_key_file"] == str(key_file)
        assert "secret" not in json.dumps(state)

    def test_relative_file_is_normalized(self, ctx, tmp_path, patch_provider_config):
        from aiv.commands import cmd_set_api_key_file

        os.chdir(tmp_path)
        key_file = tmp_path / "key.txt"
        key_file.write_text("secret\n")
        cmd_set_api_key_file(SetApiKeyFileCommand(path=Path("key.txt")), ctx)

        assert ctx.api_key_file == key_file
        assert _read_full(ctx)["session_state"]["api_key_file"] == str(key_file)


# ---------------------------------------------------------------------------
# cmd_set_prompt_suffix — mode-dependent branching
# ---------------------------------------------------------------------------


class TestCmdSetPromptSuffixModeDependent:
    def test_chat_mode_edits_in_place_and_persists(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_mode, cmd_set_prompt_suffix

        cmd_set_mode(SetModeCommand(mode=InteractionMode.CHAT), ctx)
        cmd_set_prompt_suffix(SetPromptSuffixCommand(suffix="be extra cheerful"), ctx)

        assert ctx.mode == InteractionMode.CHAT
        assert ctx.mode_chat_suffix == "\n\nbe extra cheerful"
        assert (
            _read_full(ctx)["session_state"]["mode_chat_suffix"]
            == "\n\nbe extra cheerful"
        )

    def test_code_mode_edits_in_place_and_persists(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_mode, cmd_set_prompt_suffix

        cmd_set_mode(SetModeCommand(mode=InteractionMode.CODE), ctx)
        cmd_set_prompt_suffix(SetPromptSuffixCommand(suffix="no comments at all"), ctx)

        assert ctx.mode == InteractionMode.CODE
        assert ctx.mode_code_suffix == "\n\nno comments at all"
        assert (
            _read_full(ctx)["session_state"]["mode_code_suffix"]
            == "\n\nno comments at all"
        )

    def test_default_mode_takes_ephemeral_path_and_does_not_persist(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_prompt_suffix

        assert ctx.mode == InteractionMode.DEFAULT
        cmd_set_prompt_suffix(SetPromptSuffixCommand(suffix="reply in Portuguese"), ctx)

        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == "\n\nreply in Portuguese"
        assert "session_state" not in _read_full(ctx)

    def test_custom_mode_takes_ephemeral_path_and_does_not_persist(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_prompt_suffix

        ctx.mode_suffix = "first override"
        cmd_set_prompt_suffix(SetPromptSuffixCommand(suffix="second override"), ctx)

        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == "\n\nsecond override"
        assert "session_state" not in _read_full(ctx)

    def test_switching_away_from_chat_preserves_other_modes_override(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_mode, cmd_set_prompt_suffix

        cmd_set_mode(SetModeCommand(mode=InteractionMode.CHAT), ctx)
        cmd_set_prompt_suffix(SetPromptSuffixCommand(suffix="chat override"), ctx)
        cmd_set_mode(SetModeCommand(mode=InteractionMode.CODE), ctx)
        cmd_set_prompt_suffix(SetPromptSuffixCommand(suffix="code override"), ctx)

        state = _read_full(ctx)["session_state"]
        assert state["mode_chat_suffix"] == "\n\nchat override"
        assert state["mode_code_suffix"] == "\n\ncode override"


# ---------------------------------------------------------------------------
# apply_session_state
# ---------------------------------------------------------------------------


class TestApplySessionState:
    def test_defaults_when_no_session_state(self, ctx, patch_provider_config):
        from aiv.commands import apply_session_state

        apply_session_state(ctx)
        assert ctx.provider == "anthropic"
        assert ctx.provider_type == "anthropic"
        assert ctx.provider_options == {}
        assert ctx.model == "claude-3-7-sonnet-latest"
        assert ctx.api_key == "anthropic-key"
        assert ctx.max_tokens == 4096

    def test_picks_up_persisted_provider_override(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider, apply_session_state

        cmd_set_provider(SetProviderCommand(provider="openai"), ctx)
        fresh_ctx = PipelineContext(api_key="")
        fresh_ctx.conv_path = ctx.conv_path

        apply_session_state(fresh_ctx)

        assert fresh_ctx.provider == "openai"
        assert fresh_ctx.provider_type == "openai"
        assert fresh_ctx.provider_options == {}
        assert fresh_ctx.model == "gpt-default"
        assert fresh_ctx.api_key == "openai-key"
        assert fresh_ctx.max_tokens == 8192

    def test_restores_custom_profile(self, ctx, patch_provider_config):
        from aiv.commands import cmd_set_provider, apply_session_state

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        fresh_ctx = PipelineContext(api_key="")
        fresh_ctx.conv_path = ctx.conv_path

        apply_session_state(fresh_ctx)

        assert fresh_ctx.provider == "deep"
        assert fresh_ctx.provider_type == "openai-reasoning"
        assert fresh_ctx.provider_options == {"reasoning_effort": "high"}
        assert fresh_ctx.model == "o3-deep"
        assert fresh_ctx.api_key == "deep-key"
        assert fresh_ctx.max_tokens == 16384

    def test_picks_up_persisted_sys_prompt_and_suffixes(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import (
            cmd_set_mode,
            cmd_set_sys_prompt,
            cmd_set_prompt_suffix,
            apply_session_state,
        )

        cmd_set_sys_prompt(SetSysPromptCommand(sys_prompt="pirate mode"), ctx)
        cmd_set_mode(SetModeCommand(mode=InteractionMode.CHAT), ctx)
        cmd_set_prompt_suffix(SetPromptSuffixCommand(suffix="chat override"), ctx)
        fresh_ctx = PipelineContext(api_key="")
        fresh_ctx.conv_path = ctx.conv_path

        apply_session_state(fresh_ctx)

        assert fresh_ctx.sys_prompt == "pirate mode"
        assert fresh_ctx.mode_chat_suffix == "\n\nchat override"

    def test_raises_on_missing_api_key_file(self, ctx, tmp_path, patch_provider_config):
        from aiv.commands import apply_session_state
        from aiv.conversation import save_session_state

        save_session_state({"api_key_file": str(tmp_path / "gone.txt")}, ctx.conv_path)
        original = deepcopy(vars(ctx))

        with pytest.raises(FileNotFoundError):
            apply_session_state(ctx)

        assert vars(ctx) == original

    def test_restores_profile_with_explicit_overrides(
        self, ctx, tmp_path, patch_provider_config
    ):
        from aiv.commands import apply_session_state
        from aiv.conversation import save_session_state

        key_file = tmp_path / "override.key"
        key_file.write_text("override-key\n")
        save_session_state(
            {
                "provider": "deep",
                "model": "custom-model",
                "max_tokens": 12345,
                "api_key_file": str(key_file),
            },
            ctx.conv_path,
        )

        apply_session_state(ctx)

        assert ctx.provider == "deep"
        assert ctx.provider_type == "openai-reasoning"
        assert ctx.provider_options == {"reasoning_effort": "high"}
        assert ctx.model == "custom-model"
        assert ctx.max_tokens == 12345
        assert ctx.api_key == "override-key"
        assert ctx.api_key_file == key_file

    def test_external_profile_change_reloads_type_and_options(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import apply_session_state
        from aiv.conversation import save_session_state

        save_session_state({"provider": "deep"}, ctx.conv_path)
        apply_session_state(ctx)
        assert ctx.provider_options == {"reasoning_effort": "high"}

        save_session_state({"provider": "quick"}, ctx.conv_path)
        apply_session_state(ctx)
        assert ctx.provider == "quick"
        assert ctx.provider_type == "openai-reasoning"
        assert ctx.provider_options == {"reasoning_effort": "low"}

        save_session_state({"provider": "anthropic"}, ctx.conv_path)
        apply_session_state(ctx)
        assert ctx.provider_type == "anthropic"
        assert ctx.provider_options == {}

    def test_type_and_options_are_derived_not_restored(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import apply_session_state
        from aiv.conversation import save_session_state

        save_session_state(
            {
                "provider": "deep",
                "provider_type": "anthropic",
                "provider_options": {"reasoning_effort": "low"},
            },
            ctx.conv_path,
        )

        apply_session_state(ctx)

        assert ctx.provider_type == "openai-reasoning"
        assert ctx.provider_options == {"reasoning_effort": "high"}

    def test_unknown_persisted_profile_does_not_mutate_context(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import apply_session_state
        from aiv.conversation import save_session_state

        save_session_state({"provider": "removed-profile"}, ctx.conv_path)
        original = deepcopy(vars(ctx))
        original_file = ctx.conv_path.read_bytes()

        with pytest.raises(ValueError, match="unknown provider"):
            apply_session_state(ctx)

        assert vars(ctx) == original
        assert ctx.conv_path.read_bytes() == original_file

    def test_missing_profile_values_clear_existing_values(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import apply_session_state
        from aiv.conversation import save_session_state

        ctx.provider_options = {"reasoning_effort": "high"}
        save_session_state({"provider": "unconfigured"}, ctx.conv_path)

        apply_session_state(ctx)

        assert ctx.model == ""
        assert ctx.api_key == ""
        assert ctx.api_key_file is None
        assert ctx.provider_type == "openai"
        assert ctx.provider_options == {}

    def test_options_are_copied_from_resolver(self, ctx, patch_provider_config):
        from aiv.commands import apply_session_state
        from aiv.conversation import save_session_state

        settings = _fake_get_provider_settings("deep")
        settings["options"] = {"nested": {"value": "original"}}
        patch_provider_config.side_effect = None
        patch_provider_config.return_value = settings
        save_session_state({"provider": "deep"}, ctx.conv_path)

        apply_session_state(ctx)
        ctx.provider_options["nested"]["value"] = "changed"

        assert settings["options"] == {"nested": {"value": "original"}}


# ---------------------------------------------------------------------------
# Request forwarding — no SDK calls
# ---------------------------------------------------------------------------


class TestProviderRequestForwarding:
    def test_prompt_forwards_resolved_type_and_options(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider, cmd_prompt

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        with patch("aiv.commands.run_turn", return_value="answer") as mock_turn:
            cmd_prompt(PromptCommand(text="question"), ctx)

        mock_turn.assert_called_once_with(
            prompt="question",
            context_files=[],
            stdin_data=None,
            mode=ctx.mode,
            mode_suffix=ctx.mode_suffix,
            api_key="deep-key",
            model="o3-deep",
            provider_type="openai-reasoning",
            max_tokens=16384,
            sys_prompt=ctx.sys_prompt,
            conv_path=ctx.conv_path,
            provider_options={"reasoning_effort": "high"},
        )

    def test_extract_forwards_resolved_type_and_options(
        self, ctx, patch_provider_config
    ):
        from aiv.commands import cmd_set_provider

        cmd_set_provider(SetProviderCommand(provider="deep"), ctx)
        ctx.stdin_data = "## prompt: rewrite\ncode\n"

        with patch("aiv.commands.run_turn", return_value="code") as mock_turn:
            cmd_extract_prompt_context(ExtractPromptContextCommand(path="-"), ctx)

        mock_turn.assert_called_once_with(
            prompt="rewrite",
            context_files=[],
            stdin_data=None,
            mode=ctx.mode,
            mode_suffix=ctx.mode_suffix,
            api_key="deep-key",
            model="o3-deep",
            provider_type="openai-reasoning",
            max_tokens=16384,
            sys_prompt=ctx.sys_prompt,
            conv_path=ctx.conv_path,
            provider_options={"reasoning_effort": "high"},
        )


# ---------------------------------------------------------------------------
# Working directory semantics
# ---------------------------------------------------------------------------


class TestWorkingDirectory:
    def test_getter_reflects_cwd(self, ctx, tmp_path):
        os.chdir(tmp_path)
        assert ctx.working_directory == str(tmp_path)

    def test_setter_changes_cwd(self, ctx, tmp_path):
        ctx.working_directory = tmp_path
        assert os.getcwd() == str(tmp_path)

    def test_setter_invalidates_conv_path_cache(self, ctx, tmp_path):
        _ = ctx.conv_path
        assert ctx._conv_path is not None
        ctx.working_directory = tmp_path
        assert ctx._conv_path is None

    def test_conv_path_reresolved_after_directory_change(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        ctx = PipelineContext(api_key="test")

        with patch("aiv.conversation._resolve_git_root", return_value=None):
            os.chdir(dir_a)
            ctx._conv_path = None
            path_a = ctx.conv_path
            ctx.working_directory = dir_b
            assert ctx._conv_path is None
            path_b = ctx.conv_path

        assert path_a == path_b

    def test_explicit_conv_path_cleared_by_directory_change(self, ctx, tmp_path):
        explicit = tmp_path / "explicit.json"
        ctx.conv_path = explicit
        assert ctx._conv_path == explicit
        ctx.working_directory = tmp_path
        assert ctx._conv_path is None

    def test_working_directory_returns_string(self, ctx):
        assert isinstance(ctx.working_directory, str)

    def test_cmd_changes_cwd(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        cmd_working_directory(WorkingDirectoryCommand(dir=tmp_path), ctx)
        assert os.getcwd() == str(tmp_path)

    def test_cmd_invalidates_conv_path_cache(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        _ = ctx.conv_path
        assert ctx._conv_path is not None
        cmd_working_directory(WorkingDirectoryCommand(dir=tmp_path), ctx)
        assert ctx._conv_path is None

    def test_cmd_none_dir_is_noop(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        original_cwd = os.getcwd()
        ctx.conv_path = tmp_path / "conversation.json"
        original_conv = ctx._conv_path
        cmd_working_directory(WorkingDirectoryCommand(dir=None), ctx)
        assert os.getcwd() == original_cwd
        assert ctx._conv_path == original_conv

    def test_cmd_prints_in_interactive_mode(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        ctx.interactive = True
        with pytest.raises(StopPipeline):
            cmd_working_directory(WorkingDirectoryCommand(dir=tmp_path), ctx)
        assert os.getcwd() == str(tmp_path)

    def test_cmd_silent_in_non_interactive_mode(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        ctx.interactive = False
        with patch("aiv.commands.info") as mock_info:
            cmd_working_directory(WorkingDirectoryCommand(dir=tmp_path), ctx)
            mock_info.print.assert_not_called()


# ---------------------------------------------------------------------------
# _adjust_range / _apply_leading_ws
# ---------------------------------------------------------------------------


class TestAdjustRange:
    def test_basic(self):
        assert _adjust_range("3:7", 2) == "3:5"

    def test_no_colon(self):
        assert _adjust_range("45", 3) == "45"

    def test_open_end(self):
        assert _adjust_range("3:", 2) == "3:"

    def test_non_numeric_end(self):
        assert _adjust_range("3:abc", 2) == "3:abc"

    def test_zero_prompt_lines(self):
        assert _adjust_range("3:7", 0) == "3:7"


class TestApplyLeadingWs:
    def test_restores_indentation(self):
        body = "    foo = 1;\n    bar = 2;\n"
        response = "foo = 1;\n    bar = 2;\n"
        assert _apply_leading_ws(body, response).startswith("    foo = 1;")

    def test_no_indent_body(self):
        body = "foo = 1;\nbar = 2;\n"
        response = "foo = 1;\nbar = 2;\n"
        assert _apply_leading_ws(body, response) == response

    def test_empty_response(self):
        assert _apply_leading_ws("  foo", "") == ""

    def test_empty_body(self):
        assert _apply_leading_ws("", "  foo\n") == "foo\n"

    def test_skips_empty_body_lines(self):
        body = "\n\n    foo = 1;\n"
        assert _apply_leading_ws(body, "foo = 1;\n") == "    foo = 1;\n"


# ---------------------------------------------------------------------------
# cmd_extract_prompt_context — stdin, marker found
# ---------------------------------------------------------------------------


class TestExtractStdinMarkerFound:
    def test_output_has_leading_ws_corrected(self, tmp_conv, capsys):
        tmp_conv.stdin_data = "  ## prompt: give me this back\n  foo = 1;\n  bar = 2;\n"
        cmd = ExtractPromptContextCommand(
            path="-", ctx_file="test.nix", ctx_range="1:3"
        )
        with patch("aiv.commands.run_turn", return_value="foo = 1;\n  bar = 2;"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert capsys.readouterr().out.startswith("  foo = 1;")

    def test_prompt_text_extracted(self, tmp_conv):
        tmp_conv.stdin_data = "  ## prompt: give me this back\n  foo = 1;\n"
        cmd = ExtractPromptContextCommand(
            path="-", ctx_file="test.nix", ctx_range="1:2"
        )
        with patch("aiv.commands.run_turn", return_value="foo = 1;") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert mock_rt.call_args.kwargs["prompt"] == "give me this back"

    def test_range_adjusted(self, tmp_conv):
        tmp_conv.stdin_data = "  ## prompt: do something\n  a\n  b\n  c\n  d\n"
        cmd = ExtractPromptContextCommand(path="-", ctx_file="f.py", ctx_range="1:5")
        with patch("aiv.commands.run_turn", return_value="a\n  b\n  c\n  d"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert "1:4" in _read_conv(tmp_conv)[0]["message"]["content"]

    def test_trailing_newline_preserved(self, tmp_conv, capsys):
        tmp_conv.stdin_data = "## prompt: return x\nx = 1\n"
        with patch("aiv.commands.run_turn", return_value="x = 1"):
            cmd_extract_prompt_context(ExtractPromptContextCommand(path="-"), tmp_conv)
        assert capsys.readouterr().out.endswith("\n")

    def test_no_trailing_newline_not_added(self, tmp_conv, capsys):
        tmp_conv.stdin_data = "## prompt: return x\nx = 1"
        with patch("aiv.commands.run_turn", return_value="x = 1\n"):
            cmd_extract_prompt_context(ExtractPromptContextCommand(path="-"), tmp_conv)
        assert not capsys.readouterr().out.endswith("\n")

    def test_multiline_prompt(self, tmp_conv):
        tmp_conv.stdin_data = (
            "## prompt: first line\n## prompt: second line\ncode here\n"
        )
        with patch("aiv.commands.run_turn", return_value="code here") as mock_rt:
            cmd_extract_prompt_context(ExtractPromptContextCommand(path="-"), tmp_conv)
        assert mock_rt.call_args.kwargs["prompt"] == "first line\nsecond line"

    def test_context_stored_without_marker(self, tmp_conv):
        tmp_conv.stdin_data = "## prompt: do it\nfoo = 1\n"
        cmd = ExtractPromptContextCommand(path="-", ctx_file="x.py", ctx_range="10:11")
        with patch("aiv.commands.run_turn", return_value="foo = 1"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        messages = _read_conv(tmp_conv)
        assert len(messages) == 1
        content = messages[0]["message"]["content"]
        assert "## prompt:" not in content
        assert "foo = 1" in content

    def test_context_range_hint(self, tmp_conv):
        tmp_conv.stdin_data = "## prompt: do it\nfoo = 1\n"
        cmd = ExtractPromptContextCommand(path="-", ctx_file="x.py", ctx_range="10:11")
        with patch("aiv.commands.run_turn", return_value="foo = 1"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert "x.py:10:10" in _read_conv(tmp_conv)[0]["message"]["content"]


# ---------------------------------------------------------------------------
# cmd_extract_prompt_context — stdin, no marker
# ---------------------------------------------------------------------------


class TestExtractStdinNoMarker:
    def test_exact_passthrough(self, tmp_conv, capsys):
        raw = "  foo = 1;\n  bar = 2;\n"
        tmp_conv.stdin_data = raw
        with patch("aiv.commands.run_turn") as mock_rt:
            cmd_extract_prompt_context(ExtractPromptContextCommand(path="-"), tmp_conv)
            mock_rt.assert_not_called()
        assert capsys.readouterr().out == raw

    def test_context_stored(self, tmp_conv):
        tmp_conv.stdin_data = "foo = 1;\nbar = 2;\n"
        cmd = ExtractPromptContextCommand(path="-", ctx_file="x.py", ctx_range="5:6")
        with patch("aiv.commands.run_turn") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
            mock_rt.assert_not_called()
        messages = _read_conv(tmp_conv)
        assert len(messages) == 1
        assert "foo = 1;" in messages[0]["message"]["content"]


# ---------------------------------------------------------------------------
# cmd_extract_prompt_context — file path
# ---------------------------------------------------------------------------


class TestExtractFile:
    def test_marker_found_prompt_extracted(self, tmp_conv, tmp_path, capsys):
        f = tmp_path / "test.nix"
        f.write_text("## prompt: give this back\nfoo = 1;\n")
        cmd = ExtractPromptContextCommand(path=str(f))
        with patch("aiv.commands.run_turn", return_value="foo = 1;") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert mock_rt.call_args.kwargs["prompt"] == "give this back"
        assert "foo = 1;" in capsys.readouterr().out

    def test_no_marker_exact_passthrough(self, tmp_conv, tmp_path, capsys):
        content = "foo = 1;\nbar = 2;\n"
        f = tmp_path / "test.nix"
        f.write_text(content)
        with patch("aiv.commands.run_turn") as mock_rt:
            cmd_extract_prompt_context(
                ExtractPromptContextCommand(path=str(f)), tmp_conv
            )
            mock_rt.assert_not_called()
        assert capsys.readouterr().out == content

    def test_file_not_found(self, tmp_conv, tmp_path, capsys):
        cmd = ExtractPromptContextCommand(path=str(tmp_path / "missing" / "*.nix"))
        with patch("aiv.commands.run_turn") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
            mock_rt.assert_not_called()
        assert "No files matched" in capsys.readouterr().err

    def test_marker_body_excludes_marker_line(self, tmp_conv, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("## prompt: do it\nfoo = 1\nbar = 2\n")
        with patch("aiv.commands.run_turn", return_value="foo = 1\nbar = 2"):
            cmd_extract_prompt_context(
                ExtractPromptContextCommand(path=str(f)), tmp_conv
            )
        content = _read_conv(tmp_conv)[0]["message"]["content"]
        assert "## prompt:" not in content
        assert "foo = 1" in content

    def test_range_adjusted(self, tmp_conv, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("## prompt: do it\na\nb\nc\n")
        cmd = ExtractPromptContextCommand(path=str(f), ctx_range="1:4")
        with patch("aiv.commands.run_turn", return_value="a\nb\nc"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert "1:3" in _read_conv(tmp_conv)[0]["message"]["content"]


# ---------------------------------------------------------------------------
# cli.py stdin routing — extract list participates in explicit stdin detection
# ---------------------------------------------------------------------------


class TestCliStdinRouting:
    def test_extract_stdin_routed_correctly(self):
        context_files = []
        extract_files = ["stdin,file=flake.nix,range=3:7"]
        has_explicit_stdin_context = any(
            c == "-" or c.startswith("-,") or c == "stdin" or c.startswith("stdin,")
            for c in context_files + extract_files
        )
        assert has_explicit_stdin_context is True

    def test_context_stdin_still_detected(self):
        context_files = ["stdin,file=foo.py,range=1:10"]
        extract_files = []
        has_explicit_stdin_context = any(
            c == "-" or c.startswith("-,") or c == "stdin" or c.startswith("stdin,")
            for c in context_files + extract_files
        )
        assert has_explicit_stdin_context is True

    def test_no_stdin_flag(self):
        context_files = ["src/**/*.py"]
        extract_files = ["src/main.py"]
        has_explicit_stdin_context = any(
            c == "-" or c.startswith("-,") or c == "stdin" or c.startswith("stdin,")
            for c in context_files + extract_files
        )
        assert has_explicit_stdin_context is False

    def test_extract_dash_stdin(self):
        context_files = []
        extract_files = ["-"]
        has_explicit_stdin_context = any(
            c == "-" or c.startswith("-,") or c == "stdin" or c.startswith("stdin,")
            for c in context_files + extract_files
        )
        assert has_explicit_stdin_context is True

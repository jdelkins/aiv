from __future__ import annotations
import os

import argparse
import pytest
from pathlib import Path
from unittest.mock import patch

from aiv.models import (
    PipelineContext,
    InteractionMode,
    PromptCommand,
    HistoryCommand,
    ShowCommand,
    ContextCommand,
    SetModeCommand,
    SetPromptSuffixCommand,
    ResetCommand,
    ReplCommand,
    ShowVersionCommand,
    SetModelCommand,
    SetMaxTokensCommand,
    SetSysPromptCommand,
)
from aiv.commands import commands_from_args, render_output


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_conv_path(tmp_path) -> Path:
    return tmp_path / "conversation.json"


@pytest.fixture
def ctx(tmp_conv_path) -> PipelineContext:
    # Pass conv_path_override so tests never trigger the lazy git subprocess
    ctx = PipelineContext(api_key="test")
    ctx.conv_path = tmp_conv_path
    return ctx


@pytest.fixture(autouse=True)
def restore_cwd():
    original = os.getcwd()
    yield
    os.chdir(original)


def make_args(**kwargs) -> argparse.Namespace:
    """
    Build a minimal argparse Namespace for commands_from_args.
    Defaults mirror what build_parser() would produce for a no-op invocation.
    """
    defaults = dict(
        prompt=[],
        reset=False,
        model=None,
        max_tokens=None,
        sys_prompt=None,
        chat=False,
        code=False,
        context=[],
        history=None,
        show=None,
        help=False,
        repl=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# commands_from_args
# ---------------------------------------------------------------------------


class TestCommandsFromArgs:
    def test_no_args_produces_repl(self):
        args = make_args()
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ReplCommand)

    def test_version_flag(self):
        args = make_args(version=True)
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ShowVersionCommand)

    def test_prompt_only(self):
        args = make_args(prompt=["hello", "world"])
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], PromptCommand)
        assert cmds[0].text == "hello world"

    def test_chat_flag(self):
        args = make_args(chat=True)
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], SetModeCommand)
        assert cmds[0].mode == InteractionMode.CHAT

    def test_code_flag(self):
        args = make_args(code=True)
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], SetModeCommand)
        assert cmds[0].mode == InteractionMode.CODE

    def test_reset_flag(self):
        args = make_args(reset=True)
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ResetCommand)

    def test_repl_flag(self):
        args = make_args(repl=True)
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ReplCommand)

    def test_single_context(self):
        args = make_args(context=["foo.py"])
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ContextCommand)
        assert cmds[0].path == "foo.py"

    def test_multiple_context_flags(self):
        args = make_args(context=["foo.py", "bar.py"])
        cmds = commands_from_args(args)
        assert len(cmds) == 2
        assert all(isinstance(c, ContextCommand) for c in cmds)
        first, second = cmds[0], cmds[1]
        assert isinstance(first, ContextCommand)
        assert isinstance(second, ContextCommand)
        assert first.path == "foo.py"
        assert second.path == "bar.py"

    def test_history_no_arg(self):
        # val=True is the const when --history is given with no argument;
        # must produce HistoryCommand(range=None) not HistoryCommand(range="True")
        args = make_args(history=True)
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], HistoryCommand)
        assert cmds[0].range is None

    def test_history_with_range(self):
        args = make_args(history="3-7")
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], HistoryCommand)
        assert cmds[0].range == "3-7"

    def test_show_no_arg(self):
        # Same nargs="?" / const=True pattern as --history
        args = make_args(show=True)
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ShowCommand)
        assert cmds[0].args == ""

    def test_show_with_arg(self):
        args = make_args(show="2 user")
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ShowCommand)
        assert cmds[0].args == "2 user"

    def test_precedence_ordering(self):
        # reset (10) < chat (20) < context (30) < prompt (40)
        args = make_args(
            reset=True,
            chat=True,
            context=["foo.py"],
            prompt=["hello"],
        )
        cmds = commands_from_args(args)
        assert isinstance(cmds[0], ResetCommand)
        assert isinstance(cmds[1], SetModeCommand)
        assert isinstance(cmds[2], ContextCommand)
        assert isinstance(cmds[3], PromptCommand)

    def test_repl_comes_last(self):
        # repl precedence=90 must always be last
        args = make_args(prompt=["hello"], repl=True)
        cmds = commands_from_args(args)
        assert isinstance(cmds[-1], ReplCommand)


# ---------------------------------------------------------------------------
# render_output
# ---------------------------------------------------------------------------

# A string that reliably triggers looks_like_markdown
MARKDOWN_TEXT = "```python\nprint('hello')\n```"
PLAIN_TEXT = "just some plain text with no markdown"


class TestRenderOutput:
    def test_plain_text_prints_directly(self, ctx, capsys):
        render_output(PLAIN_TEXT, InteractionMode.DEFAULT, ctx)
        out = capsys.readouterr().out
        assert PLAIN_TEXT in out

    def test_code_mode_always_prints_directly(self, ctx, capsys):
        ctx.mode = InteractionMode.CODE
        render_output(MARKDOWN_TEXT, InteractionMode.CODE, ctx)
        assert MARKDOWN_TEXT in capsys.readouterr().out

    def test_markdown_rendered_in_chat_mode(self, ctx):
        # rich.console.Console.print should be called for markdown in chat mode
        ctx.mode = InteractionMode.CHAT
        with patch("aiv.commands.console") as mock_console:
            render_output(MARKDOWN_TEXT, InteractionMode.CHAT, ctx)
            mock_console.print.assert_called_once()

    def test_markdown_rendered_in_default_mode(self, ctx):
        # DEFAULT mode should also use rich for markdown
        assert ctx.mode == InteractionMode.DEFAULT
        with patch("aiv.commands.console") as mock_console:
            render_output(MARKDOWN_TEXT, InteractionMode.DEFAULT, ctx)
            mock_console.print.assert_called_once()

    def test_markdown_rendered_in_custom_mode(self, ctx):
        # CUSTOM mode should still use rich for markdown
        ctx.mode_suffix = "respond tersely"
        assert ctx.mode == InteractionMode.CUSTOM
        with patch("aiv.commands.console") as mock_console:
            render_output(MARKDOWN_TEXT, InteractionMode.CUSTOM, ctx)
            mock_console.print.assert_called_once()


# ---------------------------------------------------------------------------
# PipelineContext mode / mode_suffix interaction
# ---------------------------------------------------------------------------


class TestPipelineContextMode:
    def test_default_mode_suffix_is_empty(self, ctx):
        # DEFAULT mode — no config available in tests, but suffix should be ""
        # without hitting get_config() since DEFAULT returns "" directly
        assert ctx.mode == InteractionMode.DEFAULT
        assert ctx.mode_suffix == ""

    def test_setting_mode_suffix_sets_custom_mode(self, ctx):
        ctx.mode_suffix = "be concise"
        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == "be concise"

    def test_setting_mode_clears_custom_suffix(self, ctx):
        ctx.mode_suffix = "be concise"
        assert ctx.mode == InteractionMode.CUSTOM
        # Switching back to DEFAULT must clear the override
        ctx.mode = InteractionMode.DEFAULT
        assert ctx.mode == InteractionMode.DEFAULT
        assert ctx.mode_suffix == ""

    def test_setting_mode_to_custom_clears_suffix(self, ctx):
        ctx.mode_suffix = "be concise"
        # Explicitly setting mode to CUSTOM (not via mode_suffix setter) clears suffix
        ctx.mode = InteractionMode.CUSTOM
        assert ctx.mode_suffix == ""

    def test_mode_suffix_setter_prepends_newlines_via_cmd(self, ctx):
        # cmd_set_prompt_suffix prepends "\n\n" before storing
        from aiv.commands import cmd_set_prompt_suffix
        from aiv.models import SetPromptSuffixCommand

        cmd = SetPromptSuffixCommand(suffix="respond in bullet points")
        cmd_set_prompt_suffix(cmd, ctx)
        assert ctx.mode_suffix == "\n\nrespond in bullet points"
        assert ctx.mode == InteractionMode.CUSTOM

    def test_mode_suffix_none_suffix_is_noop(self, ctx):
        # SetPromptSuffixCommand with suffix=None must not change anything
        from aiv.commands import cmd_set_prompt_suffix
        from aiv.models import SetPromptSuffixCommand

        original_mode = ctx.mode
        original_suffix = ctx.mode_suffix
        cmd = SetPromptSuffixCommand(suffix=None)
        cmd_set_prompt_suffix(cmd, ctx)
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
        # Changing unrelated fields must not disturb mode or suffix
        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == "custom instructions"

    def test_overwriting_suffix_stays_custom(self, ctx):
        ctx.mode_suffix = "first suffix"
        ctx.mode_suffix = "second suffix"
        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == "second suffix"

    def test_clearing_suffix_with_empty_string(self, ctx):
        ctx.mode_suffix = "something"
        # Setting to "" explicitly — mode becomes CUSTOM but suffix is empty string
        ctx.mode_suffix = ""
        assert ctx.mode == InteractionMode.CUSTOM
        assert ctx.mode_suffix == ""

    def test_code_mode_suffix_lazy_via_config(self, ctx):
        # CODE mode suffix is derived lazily from config; mock get_config so
        # tests don't require a real config file on disk
        with patch(
            "aiv.models.get_config", return_value={"mode_code_suffix": "# code only"}
        ):
            ctx.mode = InteractionMode.CODE
            assert ctx.mode_suffix == "# code only"

    def test_chat_mode_suffix_lazy_via_config(self, ctx):
        with patch(
            "aiv.models.get_config", return_value={"mode_chat_suffix": "be friendly"}
        ):
            ctx.mode = InteractionMode.CHAT
            assert ctx.mode_suffix == "be friendly"

    def test_code_mode_suffix_missing_key_returns_empty(self, ctx):
        # If the config key is absent, fall back to ""
        with patch("aiv.models.get_config", return_value={}):
            ctx.mode = InteractionMode.CODE
            assert ctx.mode_suffix == ""

    def test_chat_mode_suffix_missing_key_returns_empty(self, ctx):
        with patch("aiv.models.get_config", return_value={}):
            ctx.mode = InteractionMode.CHAT
            assert ctx.mode_suffix == ""


# ---------------------------------------------------------------------------
# cmd_set_mode
# ---------------------------------------------------------------------------


class TestCmdSetMode:
    def test_set_mode_updates_ctx(self, ctx):
        from aiv.commands import cmd_set_mode
        from aiv.models import SetModeCommand

        cmd = SetModeCommand(mode=InteractionMode.CODE)
        cmd_set_mode(cmd, ctx)
        assert ctx.mode == InteractionMode.CODE

    def test_set_mode_none_is_noop(self, ctx):
        from aiv.commands import cmd_set_mode
        from aiv.models import SetModeCommand

        cmd = SetModeCommand(mode=None)
        cmd_set_mode(cmd, ctx)
        assert ctx.mode == InteractionMode.DEFAULT

    def test_set_mode_clears_prior_custom_suffix(self, ctx):
        from aiv.commands import cmd_set_mode
        from aiv.models import SetModeCommand

        ctx.mode_suffix = "custom stuff"
        cmd = SetModeCommand(mode=InteractionMode.DEFAULT)
        cmd_set_mode(cmd, ctx)
        assert ctx.mode == InteractionMode.DEFAULT
        assert ctx.mode_suffix == ""


# ---------------------------------------------------------------------------
# cmd_set_model / cmd_set_max_tokens / cmd_set_sys_prompt
# ---------------------------------------------------------------------------


class TestCmdSetters:
    def test_set_model(self, ctx):
        from aiv.commands import cmd_set_model
        from aiv.models import SetModelCommand

        cmd = SetModelCommand(model="claude-3-5-haiku-latest")
        cmd_set_model(cmd, ctx)
        assert ctx.model == "claude-3-5-haiku-latest"

    def test_set_model_none_is_noop(self, ctx):
        from aiv.commands import cmd_set_model
        from aiv.models import SetModelCommand

        original = ctx.model
        cmd = SetModelCommand(model=None)
        cmd_set_model(cmd, ctx)
        assert ctx.model == original

    def test_set_max_tokens(self, ctx):
        from aiv.commands import cmd_set_max_tokens
        from aiv.models import SetMaxTokensCommand

        cmd = SetMaxTokensCommand(max_tokens=1024)
        cmd_set_max_tokens(cmd, ctx)
        assert ctx.max_tokens == 1024

    def test_set_max_tokens_none_is_noop(self, ctx):
        from aiv.commands import cmd_set_max_tokens
        from aiv.models import SetMaxTokensCommand

        original = ctx.max_tokens
        cmd = SetMaxTokensCommand(max_tokens=None)
        cmd_set_max_tokens(cmd, ctx)
        assert ctx.max_tokens == original

    def test_set_sys_prompt(self, ctx):
        from aiv.commands import cmd_set_sys_prompt
        from aiv.models import SetSysPromptCommand

        cmd = SetSysPromptCommand(sys_prompt="you are a pirate")
        cmd_set_sys_prompt(cmd, ctx)
        assert ctx.sys_prompt == "you are a pirate"

    def test_set_sys_prompt_none_is_noop(self, ctx):
        from aiv.commands import cmd_set_sys_prompt
        from aiv.models import SetSysPromptCommand

        original = ctx.sys_prompt
        cmd = SetSysPromptCommand(sys_prompt=None)
        cmd_set_sys_prompt(cmd, ctx)
        assert ctx.sys_prompt == original


# ---------------------------------------------------------------------------
# test working directory semantics
# ---------------------------------------------------------------------------


class TestWorkingDirectory:
    def test_getter_reflects_cwd(self, ctx, tmp_path):
        os.chdir(tmp_path)
        assert ctx.working_directory == str(tmp_path)

    def test_setter_changes_cwd(self, ctx, tmp_path):
        ctx.working_directory = tmp_path
        assert os.getcwd() == str(tmp_path)

    def test_setter_invalidates_conv_path_cache(self, ctx, tmp_path):
        # Prime the cache
        _ = ctx.conv_path
        assert ctx._conv_path is not None
        # Changing directory must clear it
        ctx.working_directory = tmp_path
        assert ctx._conv_path is None

    def test_conv_path_reresolved_after_directory_change(self, tmp_path):
        # Core regression test for the lru_cache bug on _resolve_git_root:
        # conv_path must be re-resolved after working_directory changes, not
        # served from a stale cache that reflects the old directory.
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        ctx = PipelineContext(api_key="test")

        # Mock _resolve_git_root so the test is not sensitive to whether the
        # test suite runs inside a real git repo
        with patch("aiv.conversation._resolve_git_root", return_value=None):
            os.chdir(dir_a)
            ctx._conv_path = None
            path_a = ctx.conv_path

            ctx.working_directory = dir_b
            # _conv_path must have been cleared by the setter
            assert ctx._conv_path is None
            path_b = ctx.conv_path

        # Both resolve to the fallback; the important assertion is that
        # _conv_path was None between the two reads (checked above)
        assert path_a == path_b

    def test_explicit_conv_path_cleared_by_directory_change(self, ctx, tmp_path):
        # An explicitly set conv_path is treated as a cache entry — changing
        # working_directory invalidates it so the next read re-resolves
        explicit = tmp_path / "explicit.json"
        ctx.conv_path = explicit
        assert ctx._conv_path == explicit
        ctx.working_directory = tmp_path
        assert ctx._conv_path is None

    def test_working_directory_returns_string(self, ctx):
        assert isinstance(ctx.working_directory, str)

    # --- cmd_working_directory integration ---

    def test_cmd_changes_cwd(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        cmd = WorkingDirectoryCommand(dir=tmp_path)
        cmd_working_directory(cmd, ctx)
        assert os.getcwd() == str(tmp_path)

    def test_cmd_invalidates_conv_path_cache(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        _ = ctx.conv_path
        assert ctx._conv_path is not None
        cmd = WorkingDirectoryCommand(dir=tmp_path)
        cmd_working_directory(cmd, ctx)
        assert ctx._conv_path is None

    def test_cmd_none_dir_is_noop(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        original_cwd = os.getcwd()
        ctx.conv_path = tmp_path / "conversation.json"
        original_conv = ctx._conv_path
        cmd = WorkingDirectoryCommand(dir=None)
        cmd_working_directory(cmd, ctx)
        assert os.getcwd() == original_cwd
        assert ctx._conv_path == original_conv

    def test_cmd_prints_in_interactive_mode(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        ctx.interactive = True
        cmd = WorkingDirectoryCommand(dir=tmp_path)
        # Should not raise; output goes to info console — just verify no crash
        # and cwd was updated
        cmd_working_directory(cmd, ctx)
        assert os.getcwd() == str(tmp_path)

    def test_cmd_silent_in_non_interactive_mode(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        ctx.interactive = False
        cmd = WorkingDirectoryCommand(dir=tmp_path)
        with patch("aiv.commands.info") as mock_info:
            cmd_working_directory(cmd, ctx)
            mock_info.print.assert_not_called()

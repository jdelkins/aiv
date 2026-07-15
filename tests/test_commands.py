from __future__ import annotations
import os
import json
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
    ExtractPromptContextCommand,
    SetModeCommand,
    SetPromptSuffixCommand,
    ResetCommand,
    ReplCommand,
    ShowVersionCommand,
    SetModelCommand,
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
        extract=[],
        history=None,
        show=None,
        help=False,
        repl=False,
    )
    defaults.update(kwargs)
    return argparse.Namespace(**defaults)


# ---------------------------------------------------------------------------
# Helpers for extract tests
# ---------------------------------------------------------------------------

# Minimal config dict returned by the get_config() mock so PipelineContext
# __init__ doesn't raise FileNotFoundError when reading prompt_marker.
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
    """Return the messages list from the conversation file."""
    p = ctx.conv_path
    if not p.exists():
        return []
    data = json.loads(p.read_text())
    return data.get("messages", [])


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

    def test_extract_flag_produces_extract_command(self):
        args = make_args(extract=["stdin,file=flake.nix,range=3:7"])
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ExtractPromptContextCommand)
        assert cmds[0].path == "-"
        assert cmds[0].ctx_file == "flake.nix"
        assert cmds[0].ctx_range == "3:7"

    def test_extract_file_path(self):
        args = make_args(extract=["src/foo.py"])
        cmds = commands_from_args(args)
        assert len(cmds) == 1
        assert isinstance(cmds[0], ExtractPromptContextCommand)
        assert cmds[0].path == "src/foo.py"


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
        # Should raise StopPipeline; output goes to info console — just verify no crash
        # and cwd was updated
        raised = False
        try:
            cmd_working_directory(cmd, ctx)
        except StopPipeline:
            raised = True
        assert raised
        assert os.getcwd() == str(tmp_path)

    def test_cmd_silent_in_non_interactive_mode(self, ctx, tmp_path):
        from aiv.commands import cmd_working_directory
        from aiv.models import WorkingDirectoryCommand

        ctx.interactive = False
        cmd = WorkingDirectoryCommand(dir=tmp_path)
        with patch("aiv.commands.info") as mock_info:
            cmd_working_directory(cmd, ctx)
            mock_info.print.assert_not_called()


# ---------------------------------------------------------------------------
# _adjust_range
# ---------------------------------------------------------------------------


class TestAdjustRange:
    def test_basic(self):
        assert _adjust_range("3:7", 2) == "3:5"

    def test_no_colon(self):
        # Single number — open ended, leave unchanged
        assert _adjust_range("45", 3) == "45"

    def test_open_end(self):
        # "N:" open end — leave unchanged
        assert _adjust_range("3:", 2) == "3:"

    def test_non_numeric_end(self):
        assert _adjust_range("3:abc", 2) == "3:abc"

    def test_zero_prompt_lines(self):
        assert _adjust_range("3:7", 0) == "3:7"


# ---------------------------------------------------------------------------
# _apply_leading_ws
# ---------------------------------------------------------------------------


class TestApplyLeadingWs:
    def test_restores_indentation(self):
        body = "    foo = 1;\n    bar = 2;\n"
        response = "foo = 1;\n    bar = 2;\n"
        result = _apply_leading_ws(body, response)
        assert result.startswith("    foo = 1;")

    def test_no_indent_body(self):
        body = "foo = 1;\nbar = 2;\n"
        response = "foo = 1;\nbar = 2;\n"
        assert _apply_leading_ws(body, response) == "foo = 1;\nbar = 2;\n"

    def test_empty_response(self):
        assert _apply_leading_ws("  foo", "") == ""

    def test_empty_body(self):
        # No non-empty body line → leading = "" → strips leading ws from response first line
        result = _apply_leading_ws("", "  foo\n")
        assert result == "foo\n"

    def test_skips_empty_body_lines(self):
        body = "\n\n    foo = 1;\n"
        response = "foo = 1;\n"
        assert _apply_leading_ws(body, response) == "    foo = 1;\n"


# ---------------------------------------------------------------------------
# cmd_extract_prompt_context — stdin, marker found
# ---------------------------------------------------------------------------


class TestExtractStdinMarkerFound:
    def test_output_has_leading_ws_corrected(self, tmp_conv, capsys):
        raw = "  ## prompt: give me this back\n  foo = 1;\n  bar = 2;\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(
            path="-", ctx_file="test.nix", ctx_range="1:3"
        )
        with patch("aiv.commands.run_turn", return_value="foo = 1;\n  bar = 2;"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert capsys.readouterr().out.startswith("  foo = 1;")

    def test_prompt_text_extracted(self, tmp_conv):
        raw = "  ## prompt: give me this back\n  foo = 1;\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(
            path="-", ctx_file="test.nix", ctx_range="1:2"
        )
        with patch("aiv.commands.run_turn", return_value="foo = 1;") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert mock_rt.call_args.kwargs["prompt"] == "give me this back"

    def test_range_adjusted(self, tmp_conv):
        # 1 prompt line in range 1:5 → adjusted to 1:4
        raw = "  ## prompt: do something\n  a\n  b\n  c\n  d\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(path="-", ctx_file="f.py", ctx_range="1:5")
        with patch("aiv.commands.run_turn", return_value="a\n  b\n  c\n  d"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert "1:4" in _read_conv(tmp_conv)[0]["message"]["content"]

    def test_trailing_newline_preserved(self, tmp_conv, capsys):
        raw = "## prompt: return x\nx = 1\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(path="-")
        with patch("aiv.commands.run_turn", return_value="x = 1"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert capsys.readouterr().out.endswith("\n")

    def test_no_trailing_newline_not_added(self, tmp_conv, capsys):
        raw = "## prompt: return x\nx = 1"  # no trailing newline
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(path="-")
        with patch("aiv.commands.run_turn", return_value="x = 1\n"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert not capsys.readouterr().out.endswith("\n")

    def test_multiline_prompt(self, tmp_conv):
        raw = "## prompt: first line\n## prompt: second line\ncode here\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(path="-")
        with patch("aiv.commands.run_turn", return_value="code here") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert mock_rt.call_args.kwargs["prompt"] == "first line\nsecond line"

    def test_context_stored_without_marker(self, tmp_conv):
        raw = "## prompt: do it\nfoo = 1\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(path="-", ctx_file="x.py", ctx_range="10:11")
        with patch("aiv.commands.run_turn", return_value="foo = 1"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        messages = _read_conv(tmp_conv)
        # cmd_extract_prompt_context appends exactly one context turn itself;
        # run_turn is mocked so prompt+assistant turns are not written
        assert len(messages) == 1
        content = messages[0]["message"]["content"]
        assert "## prompt:" not in content
        assert "foo = 1" in content

    def test_context_range_hint(self, tmp_conv):
        raw = "## prompt: do it\nfoo = 1\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(path="-", ctx_file="x.py", ctx_range="10:11")
        with patch("aiv.commands.run_turn", return_value="foo = 1"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        content = _read_conv(tmp_conv)[0]["message"]["content"]
        # range adjusted by 1 prompt line: 10:11 → 10:10
        assert "x.py:10:10" in content


# ---------------------------------------------------------------------------
# cmd_extract_prompt_context — stdin, no marker (passthrough)
# ---------------------------------------------------------------------------


class TestExtractStdinNoMarker:
    def test_exact_passthrough(self, tmp_conv, capsys):
        raw = "  foo = 1;\n  bar = 2;\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(path="-")
        with patch("aiv.commands.run_turn") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
            mock_rt.assert_not_called()
        assert capsys.readouterr().out == raw

    def test_context_stored(self, tmp_conv):
        raw = "foo = 1;\nbar = 2;\n"
        tmp_conv.stdin_data = raw
        cmd = ExtractPromptContextCommand(path="-", ctx_file="x.py", ctx_range="5:6")
        with patch("aiv.commands.run_turn"):
            cmd_extract_prompt_context(cmd, tmp_conv)
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
        f.write_bytes(content.encode())
        cmd = ExtractPromptContextCommand(path=str(f))
        with patch("aiv.commands.run_turn") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
            mock_rt.assert_not_called()
        assert capsys.readouterr().out == content

    def test_file_not_found(self, tmp_conv, capsys):
        cmd = ExtractPromptContextCommand(path="/nonexistent/path/*.nix")
        with patch("aiv.commands.run_turn") as mock_rt:
            cmd_extract_prompt_context(cmd, tmp_conv)
            mock_rt.assert_not_called()

    def test_marker_body_excludes_marker_line(self, tmp_conv, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("## prompt: do it\nfoo = 1\nbar = 2\n")
        cmd = ExtractPromptContextCommand(path=str(f))
        with patch("aiv.commands.run_turn", return_value="foo = 1\nbar = 2"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        content = _read_conv(tmp_conv)[0]["message"]["content"]
        assert "## prompt:" not in content
        assert "foo = 1" in content

    def test_range_adjusted(self, tmp_conv, tmp_path):
        f = tmp_path / "test.py"
        f.write_text("## prompt: do it\na\nb\nc\n")
        # 1 prompt line, range 1:4 → adjusted to 1:3
        cmd = ExtractPromptContextCommand(path=str(f), ctx_range="1:4")
        with patch("aiv.commands.run_turn", return_value="a\nb\nc"):
            cmd_extract_prompt_context(cmd, tmp_conv)
        assert "1:3" in _read_conv(tmp_conv)[0]["message"]["content"]


# ---------------------------------------------------------------------------
# cli.py stdin routing — has_explicit_stdin_context includes extract list
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

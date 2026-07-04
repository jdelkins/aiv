from __future__ import annotations

import argparse
import pytest
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

from aiv.models import (
    PipelineContext,
    InteractionMode,
    PromptCommand,
    HistoryCommand,
    ShowCommand,
    ContextCommand,
    SetModeCommand,
    ResetCommand,
    ReplCommand,
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
    return PipelineContext(
        api_key="test",
        conv_path=tmp_conv_path,
    )


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
    def test_no_args_produces_empty_pipeline(self):
        args = make_args()
        assert commands_from_args(args) == []

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
# render_output — glow fallback
# ---------------------------------------------------------------------------

# A string that reliably triggers looks_like_markdown
MARKDOWN_TEXT = "```python\nprint('hello')\n```"
PLAIN_TEXT = "just some plain text with no markdown"


class TestRenderOutput:
    def test_plain_text_prints_directly(self, ctx, capsys):
        render_output(PLAIN_TEXT, ctx)
        out = capsys.readouterr().out
        assert PLAIN_TEXT in out

    def test_code_mode_always_prints_directly(self, ctx, capsys):
        ctx.mode = InteractionMode.CODE
        # Even markdown-looking text should bypass glow in code mode
        with patch("subprocess.run") as mock_run:
            render_output(MARKDOWN_TEXT, ctx)
            mock_run.assert_not_called()
        assert MARKDOWN_TEXT in capsys.readouterr().out

    def test_glow_called_for_markdown_in_chat_mode(self, ctx):
        ctx.mode = InteractionMode.CHAT
        with patch("subprocess.run") as mock_run:
            render_output(MARKDOWN_TEXT, ctx)
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            assert call_args[0][0][0] == "glow"

    def test_glow_missing_sets_flag_and_warns(self, ctx, capsys):
        ctx.mode = InteractionMode.CHAT
        ctx.glow_available = True
        with patch("subprocess.run", side_effect=FileNotFoundError):
            render_output(MARKDOWN_TEXT, ctx)
        assert getattr(ctx, "glow_available") is False
        assert "glow" in capsys.readouterr().err.lower()

    def test_glow_missing_falls_back_to_print(self, ctx, capsys):
        ctx.mode = InteractionMode.CHAT
        ctx.glow_available = True
        with patch("subprocess.run", side_effect=FileNotFoundError):
            render_output(MARKDOWN_TEXT, ctx)
        assert MARKDOWN_TEXT in capsys.readouterr().out

    def test_glow_warning_emitted_only_once(self, ctx, capsys):
        ctx.mode = InteractionMode.CHAT
        ctx.glow_available = True
        with patch("subprocess.run", side_effect=FileNotFoundError):
            render_output(MARKDOWN_TEXT, ctx)
            render_output(MARKDOWN_TEXT, ctx)
        err = capsys.readouterr().err
        # Warning should appear exactly once across both calls
        assert err.lower().count("glow not found") == 1

    def test_glow_skipped_when_already_marked_unavailable(self, ctx, capsys):
        ctx.mode = InteractionMode.CHAT
        ctx.glow_available = False
        with patch("subprocess.run") as mock_run:
            render_output(MARKDOWN_TEXT, ctx)
            mock_run.assert_not_called()
        assert MARKDOWN_TEXT in capsys.readouterr().out

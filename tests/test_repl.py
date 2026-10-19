import io
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from rich.markup import escape

import aiv.repl as repl
from aiv.models import InteractionMode, PipelineContext, ShowCommand


@pytest.fixture
def repl_env(tmp_path, monkeypatch):
    terminal = MagicMock()
    terminal.isatty.return_value = True
    monkeypatch.setattr("sys.stdin", terminal)

    with patch("aiv.models.get_config", return_value={}):
        ctx = PipelineContext(
            api_key="synthetic-key",
            mode=InteractionMode.CHAT,
        )
    ctx.conv_path = tmp_path / "conversation.json"

    with (
        patch("aiv.repl.PromptSession") as session_factory,
        patch("aiv.repl.threading.Thread") as thread_factory,
        patch("aiv.repl.cmd_intro") as intro,
        patch("aiv.repl.cmd_set_mode") as set_mode,
        patch("aiv.repl.apply_session_state") as reload_state,
        patch("aiv.repl.get_interaction_count", return_value=2) as count,
        patch("aiv.repl.run_command") as run_command,
        patch("aiv.repl.print_info") as info,
    ):
        session = session_factory.return_value
        session.prompt.side_effect = EOFError

        yield SimpleNamespace(
            ctx=ctx,
            terminal=terminal,
            session=session,
            session_factory=session_factory,
            thread_factory=thread_factory,
            intro=intro,
            set_mode=set_mode,
            reload_state=reload_state,
            count=count,
            run_command=run_command,
            info=info,
        )


def external_change(env, text="unfinished prompt"):
    # The watcher is mocked, so trigger its event synchronously from prompt().
    def prompt(*args, **kwargs):
        watcher_args = env.thread_factory.call_args.kwargs["args"]
        file_changed = watcher_args[4]
        file_changed.set()
        return text

    return prompt


def prompt_sequence(*steps):
    iterator = iter(steps)

    def prompt(*args, **kwargs):
        step = next(iterator)
        if isinstance(step, BaseException):
            raise step
        if callable(step):
            return step(*args, **kwargs)
        return step

    return prompt


def assert_watcher_stopped(env):
    watcher_args = env.thread_factory.call_args.kwargs["args"]
    assert watcher_args[1].is_set()


def test_eof_exits_and_stops_watcher(repl_env):
    repl.run_repl_loop(repl_env.ctx)

    assert repl_env.ctx.interactive is True
    repl_env.intro.assert_called_once_with()
    repl_env.thread_factory.return_value.start.assert_called_once_with()
    repl_env.reload_state.assert_not_called()
    repl_env.run_command.assert_not_called()
    assert_watcher_stopped(repl_env)


def test_keyboard_interrupt_exits_and_stops_watcher(repl_env):
    repl_env.session.prompt.side_effect = KeyboardInterrupt

    repl.run_repl_loop(repl_env.ctx)

    assert_watcher_stopped(repl_env)


def test_default_mode_enters_chat(repl_env):
    repl_env.ctx.mode = InteractionMode.DEFAULT

    repl.run_repl_loop(repl_env.ctx)

    repl_env.set_mode.assert_called_once()
    command, context = repl_env.set_mode.call_args.args
    assert command.mode == InteractionMode.CHAT
    assert context is repl_env.ctx


def test_code_mode_is_preserved(repl_env):
    repl_env.ctx.mode = InteractionMode.CODE

    repl.run_repl_loop(repl_env.ctx)

    repl_env.set_mode.assert_not_called()


def test_history_is_scoped_to_conversation_directory(repl_env):
    repl.run_repl_loop(repl_env.ctx)

    arguments = repl_env.session_factory.call_args.kwargs
    expected = str(repl_env.ctx.conv_path.parent / ".aiv-history")
    assert arguments["history"].filename == expected
    assert arguments["complete_while_typing"] is False


def test_external_settings_change_reloads_without_showing_old_turns(repl_env):
    repl_env.count.side_effect = [2, 2]
    repl_env.session.prompt.side_effect = prompt_sequence(
        external_change(repl_env),
        EOFError(),
    )

    repl.run_repl_loop(repl_env.ctx)

    repl_env.reload_state.assert_called_once_with(repl_env.ctx)
    repl_env.run_command.assert_not_called()
    assert repl_env.session.prompt.call_args_list[1].kwargs["default"] == (
        "unfinished prompt"
    )
    assert_watcher_stopped(repl_env)


def test_external_profile_change_updates_runtime_fields(repl_env):
    def reload_state(ctx):
        ctx.provider = "deep"
        ctx.provider_type = "openai-reasoning"
        ctx.provider_options = {"reasoning_effort": "high"}
        ctx.model = "reasoning-model"

    repl_env.reload_state.side_effect = reload_state
    repl_env.count.side_effect = [2, 2]
    repl_env.session.prompt.side_effect = prompt_sequence(
        external_change(repl_env),
        EOFError(),
    )

    repl.run_repl_loop(repl_env.ctx)

    assert repl_env.ctx.provider == "deep"
    assert repl_env.ctx.provider_type == "openai-reasoning"
    assert repl_env.ctx.provider_options == {"reasoning_effort": "high"}
    assert repl_env.ctx.model == "reasoning-model"
    repl_env.run_command.assert_not_called()


@pytest.mark.parametrize(
    "error",
    [
        ValueError("unknown provider '[bold]removed[/bold]'"),
        FileNotFoundError("missing key file [red]secret[/red]"),
        PermissionError("cannot read key file"),
    ],
)
def test_reload_error_is_escaped_and_exits(repl_env, error):
    repl_env.reload_state.side_effect = error
    repl_env.count.side_effect = [2, 2]
    repl_env.session.prompt.side_effect = external_change(repl_env)

    repl.run_repl_loop(repl_env.ctx)

    repl_env.info.assert_called_once_with(f"[red]{escape(str(error))}[/red]")
    repl_env.session.prompt.assert_called_once()
    repl_env.run_command.assert_not_called()
    assert_watcher_stopped(repl_env)


def test_external_new_turns_are_displayed(repl_env):
    repl_env.count.side_effect = [2, 4]
    repl_env.session.prompt.side_effect = prompt_sequence(
        external_change(repl_env),
        EOFError(),
    )

    repl.run_repl_loop(repl_env.ctx)

    repl_env.reload_state.assert_called_once_with(repl_env.ctx)
    repl_env.run_command.assert_called_once_with(ShowCommand(args="3-"), repl_env.ctx)


def test_first_external_turn_is_displayed(repl_env):
    repl_env.count.side_effect = [0, 1]
    repl_env.session.prompt.side_effect = prompt_sequence(
        external_change(repl_env),
        EOFError(),
    )

    repl.run_repl_loop(repl_env.ctx)

    repl_env.run_command.assert_called_once_with(ShowCommand(args="1-"), repl_env.ctx)


@pytest.mark.parametrize(
    ("new_count", "message"),
    [(0, "cleared externally"), (1, "modified externally")],
)
def test_external_history_removal_is_reported(repl_env, new_count, message):
    repl_env.count.side_effect = [2, new_count]
    repl_env.session.prompt.side_effect = prompt_sequence(
        external_change(repl_env),
        EOFError(),
    )

    repl.run_repl_loop(repl_env.ctx)

    repl_env.reload_state.assert_called_once_with(repl_env.ctx)
    repl_env.run_command.assert_not_called()
    assert message in repl_env.info.call_args.args[0]


def test_empty_history_settings_change_does_not_show_turn_zero(repl_env):
    repl_env.count.side_effect = [0, 0]
    repl_env.session.prompt.side_effect = prompt_sequence(
        external_change(repl_env),
        EOFError(),
    )

    repl.run_repl_loop(repl_env.ctx)

    repl_env.reload_state.assert_called_once_with(repl_env.ctx)
    repl_env.run_command.assert_not_called()


def test_unreadable_external_history_is_reported(repl_env):
    repl_env.count.side_effect = [2, None]
    repl_env.session.prompt.side_effect = prompt_sequence(
        external_change(repl_env),
        EOFError(),
    )

    repl.run_repl_loop(repl_env.ctx)

    repl_env.reload_state.assert_not_called()
    repl_env.run_command.assert_not_called()
    assert "unreadable or malformed" in repl_env.info.call_args.args[0]


def test_normal_submission_runs_command(repl_env):
    repl_env.session.prompt.side_effect = prompt_sequence("Question", EOFError())

    repl.run_repl_loop(repl_env.ctx)

    repl_env.run_command.assert_called_once()
    command, context = repl_env.run_command.call_args.args
    assert command.text == "Question"
    assert context is repl_env.ctx
    repl_env.reload_state.assert_not_called()
    assert_watcher_stopped(repl_env)


def test_quit_stops_watcher(repl_env):
    repl_env.session.prompt.return_value = "!quit"
    repl_env.session.prompt.side_effect = None
    repl_env.run_command.side_effect = repl.QuitPipeline

    repl.run_repl_loop(repl_env.ctx)

    repl_env.run_command.assert_called_once()
    assert_watcher_stopped(repl_env)


def test_blank_submission_does_not_run_command(repl_env):
    repl_env.session.prompt.side_effect = prompt_sequence(" \n ", EOFError())

    repl.run_repl_loop(repl_env.ctx)

    repl_env.run_command.assert_not_called()


def test_piped_stdin_is_reattached_to_terminal(repl_env):
    repl_env.terminal.isatty.return_value = False
    with patch("builtins.open", return_value=io.StringIO()) as open_terminal:
        repl.run_repl_loop(repl_env.ctx)

    open_terminal.assert_called_once_with("/dev/tty", "r")


def test_missing_controlling_terminal_exits_cleanly(repl_env):
    repl_env.terminal.isatty.return_value = False
    with patch("builtins.open", side_effect=OSError("No terminal")):
        repl.run_repl_loop(repl_env.ctx)

    repl_env.session_factory.assert_not_called()
    repl_env.thread_factory.assert_not_called()
    assert "Cannot open /dev/tty" in repl_env.info.call_args.args[0]


def test_stop_pipeline_restarts_prompt_and_preserves_settings(repl_env):
    from copy import deepcopy

    from aiv.models import ExitCommand, SetProviderCommand

    repl_env.ctx.interactive = True
    original_context = deepcopy(vars(repl_env.ctx))
    repl_env.session.prompt.side_effect = prompt_sequence(
        "!provider typo",
        "!quit",
    )
    repl_env.run_command.side_effect = [
        repl.StopPipeline(),
        repl.QuitPipeline(),
    ]

    repl.run_repl_loop(repl_env.ctx)

    assert repl_env.run_command.call_count == 2
    first_call, second_call = repl_env.run_command.call_args_list
    assert first_call.args == (
        SetProviderCommand(provider="typo"),
        repl_env.ctx,
    )
    assert isinstance(second_call.args[0], ExitCommand)
    assert second_call.args[1] is repl_env.ctx
    assert repl_env.session_factory.call_count == 2
    assert repl_env.thread_factory.call_count == 2
    stop_events = [
        call.kwargs["args"][1] for call in repl_env.thread_factory.call_args_list
    ]
    assert stop_events[0] is not stop_events[1]
    assert all(event.is_set() for event in stop_events)
    assert vars(repl_env.ctx) == original_context
    repl_env.reload_state.assert_not_called()

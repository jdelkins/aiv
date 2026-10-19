import io
from unittest.mock import patch

import pytest

import aiv.cli as cli
import aiv.commands as commands
import aiv.config as config
from aiv.conversation import load_session_state, save_session_state
from aiv.models import InteractionMode


class TerminalInput(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    config_path = tmp_path / "config.toml"
    conv_path = tmp_path / "conversation.json"
    monkeypatch.setattr(config, "CONFIG_FILE", config_path)
    monkeypatch.setattr("aiv.conversation.get_conversation_file", lambda: conv_path)
    monkeypatch.setattr("sys.stdin", TerminalInput())
    config.get_config.cache_clear()

    def write_config(text):
        config_path.write_text(text, encoding="utf-8")
        config.get_config.cache_clear()

    with (
        patch("aiv.cli.run_pipeline", wraps=commands.run_pipeline) as pipeline,
        patch("aiv.commands.run_turn", return_value="Synthetic answer") as turn,
    ):
        yield {
            "write_config": write_config,
            "config_path": config_path,
            "conv_path": conv_path,
            "pipeline": pipeline,
            "turn": turn,
        }

    config.get_config.cache_clear()


def invoke(monkeypatch, *arguments):
    monkeypatch.setattr("sys.argv", ["aiv", *arguments])
    cli.main()


def runtime_context(env):
    env["pipeline"].assert_called_once()
    return env["pipeline"].call_args.args[1]


def test_initializes_custom_profile(cli_env, monkeypatch):
    cli_env["write_config"](
        """
provider = "deep"

[providers.deep]
type = "openai-reasoning"
api_key = "synthetic-key"
model = "test-model"
max_tokens = 16384
options.reasoning_effort = "high"
"""
    )

    invoke(monkeypatch, "Question")

    ctx = runtime_context(cli_env)
    assert ctx.provider == "deep"
    assert ctx.provider_type == "openai-reasoning"
    assert ctx.provider_options == {"reasoning_effort": "high"}
    assert ctx.model == "test-model"
    assert ctx.api_key == "synthetic-key"
    assert ctx.max_tokens == 16384
    arguments = cli_env["turn"].call_args.kwargs
    assert arguments["provider_type"] == "openai-reasoning"
    assert arguments["provider_options"] == {"reasoning_effort": "high"}


def test_profile_flag_supplies_key_when_default_has_none(cli_env, monkeypatch):
    cli_env["write_config"](
        """
[providers.deep]
type = "openai-reasoning"
api_key = "profile-key"
model = "profile-model"
"""
    )

    invoke(monkeypatch, "-P", "deep", "Question")

    ctx = runtime_context(cli_env)
    assert ctx.provider == "deep"
    assert ctx.api_key == "profile-key"
    assert ctx.model == "profile-model"
    cli_env["turn"].assert_called_once()
    assert load_session_state(cli_env["conv_path"]) == {"provider": "deep"}


def test_key_file_flag_supplies_missing_key(cli_env, monkeypatch, tmp_path):
    cli_env["write_config"]('model = "test-model"\n')
    key_file = tmp_path / "override.key"
    key_file.write_text("  synthetic-key\n", encoding="utf-8")

    invoke(monkeypatch, "--api-key-file", str(key_file), "Question")

    ctx = runtime_context(cli_env)
    assert ctx.api_key == "synthetic-key"
    assert ctx.api_key_file == key_file
    assert cli_env["turn"].call_args.kwargs["api_key"] == "synthetic-key"
    assert load_session_state(cli_env["conv_path"]) == {"api_key_file": str(key_file)}


def test_explicit_flags_override_session_and_profile_defaults(
    cli_env, monkeypatch, tmp_path
):
    cli_env["write_config"](
        """
[providers.deep]
type = "openai-reasoning"
api_key = "profile-key"
model = "profile-model"
max_tokens = 16384
options.reasoning_effort = "high"
"""
    )
    save_session_state(
        {"model": "persisted-model", "max_tokens": 1234},
        cli_env["conv_path"],
    )
    key_file = tmp_path / "override.key"
    key_file.write_text("override-key\n", encoding="utf-8")

    # Provider selection runs before model/token/key overrides regardless of
    # the order in which flags appear on the command line.
    invoke(
        monkeypatch,
        "-m",
        "explicit-model",
        "--max-tokens",
        "9000",
        "--api-key-file",
        str(key_file),
        "-P",
        "deep",
        "Question",
    )

    ctx = runtime_context(cli_env)
    assert ctx.provider == "deep"
    assert ctx.model == "explicit-model"
    assert ctx.max_tokens == 9000
    assert ctx.api_key == "override-key"
    assert ctx.provider_options == {"reasoning_effort": "high"}


def test_restores_custom_profile_from_session(cli_env, monkeypatch):
    cli_env["write_config"](
        """
[providers.deep]
type = "openai-reasoning"
api_key = "profile-key"
model = "profile-model"
options.reasoning_effort = "high"
"""
    )
    save_session_state({"provider": "deep"}, cli_env["conv_path"])

    invoke(monkeypatch, "Question")

    ctx = runtime_context(cli_env)
    assert ctx.provider == "deep"
    assert ctx.provider_type == "openai-reasoning"
    assert ctx.provider_options == {"reasoning_effort": "high"}
    assert ctx.api_key == "profile-key"


def test_no_hard_coded_model_fallback(cli_env, monkeypatch):
    cli_env["write_config"]("")

    invoke(monkeypatch, "-H")

    ctx = runtime_context(cli_env)
    assert ctx.model == ""
    assert ctx.api_key == ""
    cli_env["turn"].assert_not_called()


def test_context_only_does_not_require_credentials(cli_env, monkeypatch, tmp_path):
    cli_env["write_config"]("")
    context_file = tmp_path / "context.py"
    context_file.write_text("x = 1\n", encoding="utf-8")

    invoke(monkeypatch, "-c", str(context_file))

    cli_env["turn"].assert_not_called()
    assert cli_env["conv_path"].exists()


def test_help_does_not_require_config(cli_env, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, "--help")

    assert exc.value.code == 0
    assert "Usage" in capsys.readouterr().err
    cli_env["pipeline"].assert_not_called()


def test_conflicting_modes_fail_before_config_loading(cli_env, monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, "-C", "-X")

    assert exc.value.code == 1
    assert "mutually exclusive" in capsys.readouterr().err
    cli_env["pipeline"].assert_not_called()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (None, "config file not found"),
        ('provider = "removed"\n', "unknown provider"),
        ('[providers.deep]\nmodel = "test"\n', "requires a type"),
        ("provider = [\n", ""),
    ],
)
def test_configuration_errors_exit_cleanly(cli_env, monkeypatch, capsys, text, message):
    if text is not None:
        cli_env["write_config"](text)

    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, "-H")

    assert exc.value.code == 1
    error = capsys.readouterr().err
    assert error
    assert message in error
    assert "Traceback" not in error
    cli_env["pipeline"].assert_not_called()


def test_unknown_persisted_profile_exits_cleanly(cli_env, monkeypatch, capsys):
    cli_env["write_config"]("")
    save_session_state({"provider": "removed"}, cli_env["conv_path"])

    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, "-H")

    assert exc.value.code == 1
    assert "unknown provider" in capsys.readouterr().err
    cli_env["pipeline"].assert_not_called()


def test_missing_persisted_key_file_exits_cleanly(
    cli_env, monkeypatch, capsys, tmp_path
):
    cli_env["write_config"]("")
    save_session_state(
        {"api_key_file": str(tmp_path / "missing.key")},
        cli_env["conv_path"],
    )

    with pytest.raises(SystemExit) as exc:
        invoke(monkeypatch, "-H")

    assert exc.value.code == 1
    assert "api_key_file not found" in capsys.readouterr().err
    cli_env["pipeline"].assert_not_called()


@pytest.mark.parametrize(
    ("flag", "mode"),
    [("-C", InteractionMode.CHAT), ("-X", InteractionMode.CODE)],
)
def test_output_mode_flags(cli_env, monkeypatch, flag, mode):
    cli_env["write_config"]('api_key = "test-key"\nmodel = "test-model"\n')

    invoke(monkeypatch, flag, "Question")

    assert runtime_context(cli_env).mode == mode
    assert cli_env["turn"].call_args.kwargs["mode"] == mode


def test_piped_input_supplies_prompt(cli_env, monkeypatch):
    cli_env["write_config"]('api_key = "test-key"\nmodel = "test-model"\n')
    monkeypatch.setattr("sys.stdin", io.StringIO("Piped question\n"))

    invoke(monkeypatch)

    arguments = cli_env["turn"].call_args.kwargs
    assert arguments["prompt"] == "Piped question"
    assert arguments["stdin_data"] is None
    assert runtime_context(cli_env).piped_stdin is True


def test_piped_input_with_prompt_supplies_context(cli_env, monkeypatch):
    cli_env["write_config"]('api_key = "test-key"\nmodel = "test-model"\n')
    monkeypatch.setattr("sys.stdin", io.StringIO("Piped context\n"))

    invoke(monkeypatch, "Question")

    arguments = cli_env["turn"].call_args.kwargs
    assert arguments["prompt"] == "Question"
    assert arguments["stdin_data"] == "Piped context\n"


def test_explicit_stdin_context_does_not_send_request(cli_env, monkeypatch):
    cli_env["write_config"]("")
    monkeypatch.setattr("sys.stdin", io.StringIO("Context only\n"))

    invoke(monkeypatch, "-c", "-")

    cli_env["turn"].assert_not_called()
    assert cli_env["conv_path"].exists()

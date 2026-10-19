from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

from aiv.api import run_turn
from aiv.conversation import (
    load_conversation,
    load_session_state,
    save_conversation,
    save_session_state,
    StoredMessage,
)
from aiv.models import InteractionMode


@pytest.fixture
def turn_kwargs(tmp_path):
    return {
        "prompt": "Test question",
        "context_files": [],
        "stdin_data": None,
        "mode": InteractionMode.CHAT,
        "mode_suffix": "\n\nTest formatting instructions",
        "api_key": "not-a-real-key",
        "model": "test-model",
        "provider_type": "openai-reasoning",
        "max_tokens": 8192,
        "sys_prompt": "Test system prompt",
        "conv_path": tmp_path / "conversation.json",
        "provider_options": {"reasoning_effort": "high"},
    }


@pytest.fixture
def provider_factory():
    # Mock the factory boundary: no SDK imports, credentials, or network access.
    implementation = MagicMock()
    implementation.call.return_value = ("Test answer", "stop")

    with patch("aiv.api.get_provider", return_value=implementation) as factory:
        yield factory


def test_dispatches_by_implementation_type(turn_kwargs, provider_factory):
    result = run_turn(**turn_kwargs)

    assert result == "Test answer"
    provider_factory.assert_called_once_with("openai-reasoning")
    provider_factory.return_value.call.assert_called_once()

    arguments = provider_factory.return_value.call.call_args.kwargs
    assert arguments["model"] == "test-model"
    assert arguments["max_tokens"] == 8192
    assert arguments["sys_prompt"] == "Test system prompt"
    assert arguments["api_key"] == "not-a-real-key"
    assert arguments["options"] == {"reasoning_effort": "high"}
    assert arguments["messages"] == [
        {
            "role": "user",
            "content": "Test question\n\nTest formatting instructions",
        }
    ]


@pytest.mark.parametrize("options", [None, {}])
def test_forwards_empty_options(turn_kwargs, provider_factory, options):
    turn_kwargs["provider_options"] = options

    run_turn(**turn_kwargs)

    arguments = provider_factory.return_value.call.call_args.kwargs
    assert arguments["options"] == options


def test_options_argument_is_optional(turn_kwargs, provider_factory):
    del turn_kwargs["provider_options"]

    run_turn(**turn_kwargs)

    arguments = provider_factory.return_value.call.call_args.kwargs
    assert arguments["options"] is None


def test_persists_user_and_assistant_messages(turn_kwargs, provider_factory):
    run_turn(**turn_kwargs)

    messages = load_conversation(turn_kwargs["conv_path"])
    assert len(messages) == 2
    assert messages[0]["mode"] == InteractionMode.CHAT
    assert messages[0]["message"] == {
        "role": "user",
        "content": "Test question\n\nTest formatting instructions",
    }
    assert messages[1]["mode"] == InteractionMode.CHAT
    assert messages[1]["message"] == {
        "role": "assistant",
        "content": "Test answer",
    }


def test_includes_existing_history(turn_kwargs, provider_factory):
    history: list[StoredMessage] = [
        {
            "mode": InteractionMode.CHAT,
            "message": {"role": "user", "content": "Earlier question"},
        },
        {
            "mode": InteractionMode.CHAT,
            "message": {"role": "assistant", "content": "Earlier answer"},
        },
    ]
    save_conversation(history, turn_kwargs["conv_path"])

    run_turn(**turn_kwargs)

    sent = provider_factory.return_value.call.call_args.kwargs["messages"]
    assert sent[:2] == [entry["message"] for entry in history]
    assert len(sent) == 3
    assert sent[-1]["role"] == "user"
    assert "Test question" in sent[-1]["content"]

    stored = load_conversation(turn_kwargs["conv_path"])
    assert len(stored) == 4
    assert stored[:2] == history
    assert stored[-1]["message"]["content"] == "Test answer"


def test_preserves_session_state(turn_kwargs, provider_factory):
    state = {"provider": "deep", "model": "test-model"}
    save_session_state(state, turn_kwargs["conv_path"])

    run_turn(**turn_kwargs)

    assert load_session_state(turn_kwargs["conv_path"]) == state


def test_includes_stdin_context(turn_kwargs, provider_factory):
    turn_kwargs["stdin_data"] = "Context supplied through stdin"

    run_turn(**turn_kwargs)

    sent = provider_factory.return_value.call.call_args.kwargs["messages"]
    content = sent[-1]["content"]
    assert "Context supplied through stdin" in content
    assert "Test question" in content
    assert content.endswith(turn_kwargs["mode_suffix"])


def test_includes_file_context(turn_kwargs, provider_factory, tmp_path):
    context_file = tmp_path / "example.py"
    context_file.write_text("print('context example')\n", encoding="utf-8")
    turn_kwargs["context_files"] = [str(context_file)]

    run_turn(**turn_kwargs)

    sent = provider_factory.return_value.call.call_args.kwargs["messages"]
    content = sent[-1]["content"]
    assert "print('context example')" in content
    assert "Test question" in content


def test_truncation_warning_is_returned_and_persisted(turn_kwargs, provider_factory):
    provider_factory.return_value.call.return_value = ("Partial answer", "max_tokens")
    expected = (
        "Partial answer" "\n\n[aiv: WARNING: response truncated - max_tokens too low]"
    )

    result = run_turn(**turn_kwargs)

    assert result == expected
    messages = load_conversation(turn_kwargs["conv_path"])
    assert messages[-1]["message"]["content"] == expected


@pytest.mark.parametrize("stop_reason", [None, "stop", "end_turn"])
def test_other_stop_reasons_do_not_add_warning(
    turn_kwargs, provider_factory, stop_reason
):
    provider_factory.return_value.call.return_value = ("Complete answer", stop_reason)

    assert run_turn(**turn_kwargs) == "Complete answer"


@pytest.mark.parametrize("field", ["api_key", "model"])
@pytest.mark.parametrize("value", ["", " ", "\n\t"])
@pytest.mark.parametrize("existing_file", [False, True])
def test_missing_request_settings_do_not_mutate_history(
    turn_kwargs, provider_factory, field, value, existing_file
):
    path = turn_kwargs["conv_path"]
    if existing_file:
        save_conversation(
            [
                {
                    "mode": InteractionMode.CHAT,
                    "message": {"role": "user", "content": "Existing context"},
                }
            ],
            path,
        )
        save_session_state({"provider": "deep"}, path)

    original = path.read_bytes() if path.exists() else None
    turn_kwargs[field] = value

    with pytest.raises(ValueError, match=f"{field} not set"):
        run_turn(**turn_kwargs)

    provider_factory.assert_not_called()
    assert (path.read_bytes() if path.exists() else None) == original


def test_invalid_implementation_type_does_not_mutate_history(
    turn_kwargs, provider_factory
):
    path = turn_kwargs["conv_path"]
    save_session_state({"provider": "deep"}, path)
    original = path.read_bytes()
    provider_factory.side_effect = ValueError("aiv: unknown provider type 'invalid'")
    turn_kwargs["provider_type"] = "invalid"

    with pytest.raises(ValueError, match="unknown provider type"):
        run_turn(**turn_kwargs)

    assert path.read_bytes() == original
    provider_factory.return_value.call.assert_not_called()


def test_provider_failure_does_not_store_assistant_response(
    turn_kwargs, provider_factory
):
    provider_factory.return_value.call.side_effect = RuntimeError("Synthetic failure")

    with pytest.raises(RuntimeError, match="Synthetic failure"):
        run_turn(**turn_kwargs)

    messages = load_conversation(turn_kwargs["conv_path"])
    assert not any(entry["message"]["role"] == "assistant" for entry in messages)


def test_empty_response_is_persisted(turn_kwargs, provider_factory):
    provider_factory.return_value.call.return_value = ("", "stop")

    assert run_turn(**turn_kwargs) == ""

    messages = load_conversation(turn_kwargs["conv_path"])
    assert messages[-1]["message"] == {"role": "assistant", "content": ""}


def test_provider_receives_history_snapshot_without_new_response(
    turn_kwargs, provider_factory
):
    sent_messages = []

    def capture_call(**kwargs):
        sent_messages.extend(deepcopy(kwargs["messages"]))
        return "Test answer", "stop"

    provider_factory.return_value.call.side_effect = capture_call

    run_turn(**turn_kwargs)

    assert len(sent_messages) == 1
    assert sent_messages[0]["role"] == "user"
    assert len(load_conversation(turn_kwargs["conv_path"])) == 2

from unittest.mock import patch

import pytest
from prompt_toolkit.completion import CompleteEvent, Completion
from prompt_toolkit.document import Document

from aiv.completion import AivCompleter
from aiv.config import VALID_PROVIDER_TYPES
from aiv.models import InteractionMode


@pytest.fixture
def completer():
    return AivCompleter()


@pytest.fixture
def provider_config():
    with patch(
        "aiv.completion.get_config",
        return_value={
            "providers": {
                "deep": {"type": "openai-reasoning"},
                "deep-fast": {"type": "openai-reasoning"},
                "claude": {"type": "anthropic"},
                "openai": {"type": "openai"},
            }
        },
    ) as mocked:
        yield mocked


def complete(completer, text, cursor_position=None):
    document = Document(
        text,
        cursor_position=len(text) if cursor_position is None else cursor_position,
    )
    return list(
        completer.get_completions(document, CompleteEvent(completion_requested=True))
    )


def completion_texts(completions):
    return [item.text for item in completions]


def test_constructor_does_not_load_config(provider_config):
    AivCompleter()

    provider_config.assert_not_called()


def test_provider_completion_includes_profiles_and_legacy_names(
    completer, provider_config
):
    results = complete(completer, "!provider ")

    expected = sorted(
        set(VALID_PROVIDER_TYPES) | {"deep", "deep-fast", "claude", "openai"}
    )
    assert completion_texts(results) == expected
    assert all(item.start_position == 0 for item in results)
    provider_config.assert_called_once_with()


def test_provider_completion_filters_prefix(completer, provider_config):
    results = complete(completer, "!provider de")

    assert completion_texts(results) == ["deep", "deep-fast"]
    assert all(item.start_position == -2 for item in results)


def test_provider_completion_replaces_entire_argument(completer, provider_config):
    text = "!provider deep-f"
    document = Document(text)
    results = complete(completer, text)

    assert completion_texts(results) == ["deep-fast"]
    result = results[0]
    replacement = text[: document.cursor_position + result.start_position] + result.text
    assert replacement == "!provider deep-fast"


def test_provider_completion_has_no_duplicates(completer, provider_config):
    names = completion_texts(complete(completer, "!provider "))

    assert names.count("openai") == 1
    assert len(names) == len(set(names))


def test_provider_completion_is_case_sensitive(completer, provider_config):
    assert complete(completer, "!provider DE") == []


def test_unknown_provider_prefix_has_no_completions(completer, provider_config):
    assert complete(completer, "!provider missing") == []


def test_provider_names_are_resolved_when_completing(completer, provider_config):
    first = completion_texts(complete(completer, "!provider "))

    provider_config.return_value = {"providers": {"new-profile": {"type": "openai"}}}
    second = completion_texts(complete(completer, "!provider "))

    assert "deep" in first
    assert "deep" not in second
    assert "new-profile" in second
    assert provider_config.call_count == 2


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError("No configuration"),
        PermissionError("Cannot read key"),
        ValueError("Invalid configuration"),
    ],
)
def test_config_errors_fall_back_to_legacy_names(completer, error):
    with patch("aiv.completion.get_config", side_effect=error):
        results = complete(completer, "!provider ")

    assert completion_texts(results) == sorted(VALID_PROVIDER_TYPES)


def test_config_without_profiles_completes_legacy_names(completer):
    with patch("aiv.completion.get_config", return_value={}):
        results = complete(completer, "!provider ")

    assert completion_texts(results) == sorted(VALID_PROVIDER_TYPES)


def test_command_name_completion(completer, provider_config):
    results = complete(completer, "!prov")

    assert completion_texts(results) == ["!provider"]
    assert results[0].start_position == -5
    provider_config.assert_not_called()


def test_command_name_completion_includes_aliases(completer):
    names = completion_texts(complete(completer, "!"))

    assert "!quit" in names
    assert "!exit" in names


@pytest.mark.parametrize("text", ["", "Explain this code", "ordinary text "])
def test_bare_text_has_no_completions(completer, provider_config, text):
    assert complete(completer, text) == []
    provider_config.assert_not_called()


@pytest.mark.parametrize(
    "text",
    [
        "First line\n!provider ",
        "!provider deep\n",
        "First line\n!context ",
    ],
)
def test_multiline_input_has_no_completions(completer, provider_config, text):
    assert complete(completer, text) == []
    provider_config.assert_not_called()


def test_completion_uses_only_text_before_cursor(completer, provider_config):
    text = "!provider de trailing text"
    results = complete(completer, text, cursor_position=len("!provider de"))

    assert completion_texts(results) == ["deep", "deep-fast"]
    assert all(item.start_position == -2 for item in results)


def test_mode_completion_is_unique(completer, provider_config):
    values = completion_texts(complete(completer, "!mode "))

    assert values == list(dict.fromkeys(mode.value for mode in InteractionMode))
    assert values.count("default") == 1
    provider_config.assert_not_called()


def test_mode_completion_filters_prefix(completer):
    results = complete(completer, "!mode co")

    assert completion_texts(results) == ["code"]
    assert results[0].start_position == -2


@pytest.mark.parametrize("command", ["!history", "!show", "!delete"])
def test_range_arguments_have_no_completions(completer, provider_config, command):
    assert complete(completer, command + " ") == []
    assert complete(completer, command + " 3-") == []
    provider_config.assert_not_called()


@pytest.mark.parametrize("command", ["!context", "!extract", "!api-key-file"])
def test_path_commands_delegate_to_path_completer(completer, provider_config, command):
    expected = Completion("example.py", start_position=-2)
    with (
        patch.object(
            completer._path_completer,
            "get_completions",
            return_value=iter([expected]),
        ) as path_completion,
        patch.object(completer._dir_completer, "get_completions") as dir_completion,
    ):
        results = complete(completer, command + " ex")

    assert results == [expected]
    path_completion.assert_called_once()
    document, event = path_completion.call_args.args
    assert document.text == "ex"
    assert document.cursor_position == 2
    assert event.completion_requested
    dir_completion.assert_not_called()
    provider_config.assert_not_called()


def test_directory_command_delegates_to_directory_completer(completer, provider_config):
    expected = Completion("source", start_position=-2)
    with (
        patch.object(
            completer._dir_completer,
            "get_completions",
            return_value=iter([expected]),
        ) as dir_completion,
        patch.object(completer._path_completer, "get_completions") as path_completion,
    ):
        results = complete(completer, "!cd so")

    assert results == [expected]
    dir_completion.assert_called_once()
    document, _ = dir_completion.call_args.args
    assert document.text == "so"
    path_completion.assert_not_called()
    provider_config.assert_not_called()


@pytest.mark.parametrize("command", ["!context", "!extract"])
@pytest.mark.parametrize(
    "argument",
    [
        "-",
        "-,file=example.py",
        "stdin",
        "stdin,file=example.py,range=1:5",
    ],
)
def test_stdin_sentinels_do_not_trigger_path_completion(completer, command, argument):
    with patch.object(completer._path_completer, "get_completions") as path_completion:
        assert complete(completer, command + " " + argument) == []

    path_completion.assert_not_called()


def test_real_path_completion(completer, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "example.py").write_text("x = 1\n", encoding="utf-8")

    results = complete(completer, "!context ex")

    assert "ample.py" in completion_texts(results)


def test_real_directory_completion_excludes_files(completer, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "source").mkdir()
    (tmp_path / "some-file.py").write_text("", encoding="utf-8")

    results = complete(completer, "!cd so")
    names = completion_texts(results)

    assert "urce" in names
    assert "me-file.py" not in names

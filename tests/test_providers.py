from importlib import import_module
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from aiv.providers import get_provider, validate_provider_options


PROVIDER_CASES = (
    ("anthropic", "AnthropicProvider", "anthropic", "Anthropic"),
    ("openai", "OpenAIProvider", "openai", "OpenAI"),
    ("openai-reasoning", "OpenAIReasoningProvider", "openai", "OpenAI"),
)
REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")


@pytest.fixture
def call_kwargs():
    return {
        "messages": [{"role": "user", "content": "Hello"}],
        "model": "test-model",
        "max_tokens": 1024,
        "sys_prompt": "Test system prompt",
        # Client constructors are mocked; this is never sent anywhere.
        "api_key": "not-a-real-key",
    }


@pytest.fixture(params=PROVIDER_CASES, ids=lambda case: case[0])
def adapter(request):
    provider_type, class_name, sdk_name, constructor_name = request.param
    pytest.importorskip(sdk_name)
    module_name = provider_type.replace("-", "_")
    module = import_module(f"aiv.providers.{module_name}")

    with patch.object(getattr(module, sdk_name), constructor_name) as constructor:
        yield SimpleNamespace(
            provider_type=provider_type,
            implementation=getattr(module, class_name)(),
            constructor=constructor,
            client=constructor.return_value,
        )


@pytest.fixture
def anthropic_adapter():
    pytest.importorskip("anthropic")
    module = import_module("aiv.providers.anthropic")

    with patch.object(module.anthropic, "Anthropic") as constructor:
        stream = MagicMock()
        stream.text_stream = iter(["Hello", " ", "world"])
        stream.get_final_message.return_value = SimpleNamespace(stop_reason="end_turn")
        client = constructor.return_value
        client.messages.stream.return_value.__enter__.return_value = stream

        yield SimpleNamespace(
            implementation=module.AnthropicProvider(),
            constructor=constructor,
            client=client,
            stream=stream,
        )


def stream_chunk(content=None, finish_reason=None):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content),
                finish_reason=finish_reason,
            )
        ]
    )


@pytest.fixture
def openai_adapter():
    pytest.importorskip("openai")
    module = import_module("aiv.providers.openai")

    with patch.object(module.openai, "OpenAI") as constructor:
        client = constructor.return_value
        client.chat.completions.create.return_value = iter(
            [
                stream_chunk(),
                stream_chunk("Hello"),
                SimpleNamespace(choices=[]),
                stream_chunk(" world"),
                stream_chunk(finish_reason="stop"),
            ]
        )

        yield SimpleNamespace(
            implementation=module.OpenAIProvider(),
            constructor=constructor,
            client=client,
        )


@pytest.fixture
def reasoning_adapter():
    pytest.importorskip("openai")
    module = import_module("aiv.providers.openai_reasoning")

    with patch.object(module.openai, "OpenAI") as constructor:
        client = constructor.return_value
        choice = SimpleNamespace(
            message=SimpleNamespace(content="Reasoned answer"),
            finish_reason="stop",
        )
        client.chat.completions.create.return_value = SimpleNamespace(choices=[choice])

        yield SimpleNamespace(
            implementation=module.OpenAIReasoningProvider(),
            constructor=constructor,
            client=client,
            choice=choice,
        )


@pytest.mark.parametrize("options", [None, {}])
def test_validate_empty_options(options):
    validate_provider_options(options, provider_type="test")


def test_validate_supported_option():
    validate_provider_options(
        {"reasoning_effort": "high"},
        provider_type="openai-reasoning",
        supported_options=("reasoning_effort",),
    )


@pytest.mark.parametrize("options", [[], "", 123, False])
def test_validate_options_requires_mapping(options):
    with pytest.raises(ValueError, match="must be a mapping"):
        validate_provider_options(options, provider_type="test")


def test_validate_unknown_option():
    with pytest.raises(ValueError, match="unsupported options") as exc:
        validate_provider_options(
            {"typo": "high"},
            provider_type="openai-reasoning",
            supported_options=("reasoning_effort",),
        )

    assert "typo" in str(exc.value)
    assert "reasoning_effort" in str(exc.value)


def test_validate_options_does_not_mutate_input():
    options = {"reasoning_effort": "high"}

    validate_provider_options(
        options,
        provider_type="openai-reasoning",
        supported_options=("reasoning_effort",),
    )

    assert options == {"reasoning_effort": "high"}


def test_factory_rejects_profile_name():
    with pytest.raises(ValueError, match="unknown provider type"):
        get_provider("custom-profile")


def test_factory_selects_implementation(adapter):
    implementation = get_provider(adapter.provider_type)

    assert type(implementation) is type(adapter.implementation)
    adapter.constructor.assert_not_called()


@pytest.mark.parametrize("options", [{"unknown": True}, {"model": "override"}])
def test_adapter_rejects_unknown_options_before_client_creation(
    adapter, call_kwargs, options
):
    with pytest.raises(ValueError, match="unsupported options"):
        adapter.implementation.call(**call_kwargs, options=options)

    adapter.constructor.assert_not_called()


@pytest.mark.parametrize("options", [None, {}])
def test_anthropic_request_and_response(anthropic_adapter, call_kwargs, options):
    result = anthropic_adapter.implementation.call(**call_kwargs, options=options)

    assert result == ("Hello world", "end_turn")
    anthropic_adapter.constructor.assert_called_once_with(
        api_key=call_kwargs["api_key"]
    )
    anthropic_adapter.client.messages.stream.assert_called_once_with(
        model=call_kwargs["model"],
        max_tokens=call_kwargs["max_tokens"],
        messages=call_kwargs["messages"],
        system=call_kwargs["sys_prompt"],
        cache_control={"type": "ephemeral"},
    )
    anthropic_adapter.stream.get_final_message.assert_called_once_with()


def test_anthropic_preserves_truncation_reason(anthropic_adapter, call_kwargs):
    anthropic_adapter.stream.get_final_message.return_value.stop_reason = "max_tokens"

    _, stop_reason = anthropic_adapter.implementation.call(**call_kwargs)

    assert stop_reason == "max_tokens"


@pytest.mark.parametrize("options", [None, {}])
def test_openai_request_and_response(openai_adapter, call_kwargs, options):
    result = openai_adapter.implementation.call(**call_kwargs, options=options)

    assert result == ("Hello world", "stop")
    openai_adapter.constructor.assert_called_once_with(api_key=call_kwargs["api_key"])
    openai_adapter.client.chat.completions.create.assert_called_once_with(
        model=call_kwargs["model"],
        max_tokens=call_kwargs["max_tokens"],
        messages=[
            {"role": "system", "content": call_kwargs["sys_prompt"]},
            *call_kwargs["messages"],
        ],
        stream=True,
    )


def test_openai_normalizes_truncation(openai_adapter, call_kwargs):
    openai_adapter.client.chat.completions.create.return_value = iter(
        [stream_chunk("Partial", finish_reason="length")]
    )

    assert openai_adapter.implementation.call(**call_kwargs) == (
        "Partial",
        "max_tokens",
    )


def test_openai_empty_stream(openai_adapter, call_kwargs):
    openai_adapter.client.chat.completions.create.return_value = iter([])

    assert openai_adapter.implementation.call(**call_kwargs) == ("", None)


@pytest.mark.parametrize("options", [None, {}])
def test_reasoning_request_omits_unspecified_effort(
    reasoning_adapter, call_kwargs, options
):
    result = reasoning_adapter.implementation.call(**call_kwargs, options=options)

    assert result == ("Reasoned answer", "stop")
    reasoning_adapter.constructor.assert_called_once_with(
        api_key=call_kwargs["api_key"]
    )
    reasoning_adapter.client.chat.completions.create.assert_called_once_with(
        model=call_kwargs["model"],
        max_completion_tokens=call_kwargs["max_tokens"],
        messages=[
            {"role": "developer", "content": call_kwargs["sys_prompt"]},
            *call_kwargs["messages"],
        ],
    )


@pytest.mark.parametrize("effort", REASONING_EFFORTS)
def test_reasoning_forwards_effort(reasoning_adapter, call_kwargs, effort):
    options = {"reasoning_effort": effort}

    reasoning_adapter.implementation.call(**call_kwargs, options=options)

    reasoning_adapter.client.chat.completions.create.assert_called_once_with(
        model=call_kwargs["model"],
        max_completion_tokens=call_kwargs["max_tokens"],
        messages=[
            {"role": "developer", "content": call_kwargs["sys_prompt"]},
            *call_kwargs["messages"],
        ],
        reasoning_effort=effort,
    )
    assert options == {"reasoning_effort": effort}


@pytest.mark.parametrize(
    "effort",
    ["", "HIGH", "unsupported", None, 1, True, [], {}],
)
def test_reasoning_rejects_invalid_effort_before_client_creation(
    reasoning_adapter, call_kwargs, effort
):
    with pytest.raises(ValueError, match="reasoning_effort"):
        reasoning_adapter.implementation.call(
            **call_kwargs,
            options={"reasoning_effort": effort},
        )

    reasoning_adapter.constructor.assert_not_called()


def test_reasoning_normalizes_truncation(reasoning_adapter, call_kwargs):
    reasoning_adapter.choice.finish_reason = "length"

    assert reasoning_adapter.implementation.call(**call_kwargs) == (
        "Reasoned answer",
        "max_tokens",
    )


def test_reasoning_empty_content(reasoning_adapter, call_kwargs):
    reasoning_adapter.choice.message.content = None

    assert reasoning_adapter.implementation.call(**call_kwargs) == ("", "stop")

# Save as aiv/providers/openai_reasoning.py (underscore), matching the factory import.
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Literal, TypedDict, cast

import openai
from openai.types.chat import ChatCompletionMessageParam

from aiv.conversation import GenericMessageParam
from aiv.providers import validate_provider_options


ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]
VALID_REASONING_EFFORTS = ("none", "minimal", "low", "medium", "high", "xhigh")


class ReasoningOptions(TypedDict, total=False):
    reasoning_effort: ReasoningEffort


class OpenAIReasoningProvider:
    def call(
        self,
        messages: list[GenericMessageParam],
        model: str,
        max_tokens: int,
        sys_prompt: str,
        api_key: str,
        options: Mapping[str, object] | None = None,
    ) -> tuple[str, str | None]:
        """Return a blocking Chat Completions response and normalized stop reason.

        Uses a developer message and max_completion_tokens for reasoning models.
        Supported effort values depend on the model; the API validates model
        compatibility. Unspecified effort is omitted to preserve API defaults.
        """
        validate_provider_options(
            options,
            provider_type="openai-reasoning",
            supported_options=("reasoning_effort",),
        )

        request_options: ReasoningOptions = {}
        if options is not None and "reasoning_effort" in options:
            effort = options["reasoning_effort"]
            if not isinstance(effort, str) or effort not in VALID_REASONING_EFFORTS:
                raise ValueError(
                    "aiv: reasoning_effort for provider type 'openai-reasoning' "
                    f"must be one of {VALID_REASONING_EFFORTS}; got {effort!r}"
                )
            request_options["reasoning_effort"] = cast(ReasoningEffort, effort)

        client = openai.OpenAI(api_key=api_key)
        full_messages = cast(
            Iterable[ChatCompletionMessageParam],
            [{"role": "developer", "content": sys_prompt}, *messages],
        )

        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=full_messages,
            **request_options,
        )

        choice = response.choices[0]
        response_text = choice.message.content or ""
        finish_reason = choice.finish_reason
        stop_reason = "max_tokens" if finish_reason == "length" else finish_reason

        return response_text, stop_reason

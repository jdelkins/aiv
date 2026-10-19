from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

import openai
from openai.types.chat import ChatCompletionMessageParam

from aiv.conversation import GenericMessageParam
from aiv.providers import validate_provider_options


class OpenAIProvider:
    def call(
        self,
        messages: list[GenericMessageParam],
        model: str,
        max_tokens: int,
        sys_prompt: str,
        api_key: str,
        options: Mapping[str, object] | None = None,
    ) -> tuple[str, str | None]:
        """Stream a Chat Completions response and normalize its stop reason.

        No provider-specific options are currently supported. Models requiring
        a developer message or max_completion_tokens should use the
        openai-reasoning implementation instead.
        """
        validate_provider_options(options, provider_type="openai")

        client = openai.OpenAI(api_key=api_key)
        full_messages = cast(
            Iterable[ChatCompletionMessageParam],
            [{"role": "system", "content": sys_prompt}, *messages],
        )

        stream = client.chat.completions.create(
            model=model,
            max_tokens=max_tokens,
            messages=full_messages,
            stream=True,
        )

        response_parts: list[str] = []
        finish_reason: str | None = None
        for chunk in stream:
            # Usage-only chunks may contain no choices.
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            if choice.delta.content is not None:
                response_parts.append(choice.delta.content)
            if choice.finish_reason is not None:
                finish_reason = choice.finish_reason

        stop_reason = "max_tokens" if finish_reason == "length" else finish_reason
        return "".join(response_parts), stop_reason

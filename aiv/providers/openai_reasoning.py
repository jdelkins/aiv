from __future__ import annotations
from typing import cast, Iterable

import openai
from openai.types.chat import ChatCompletionMessageParam
from aiv.conversation import GenericMessageParam


class OpenAIReasoningProvider:
    def call(
        self,
        messages: list[GenericMessageParam],
        model: str,
        max_tokens: int,
        sys_prompt: str,
        api_key: str,
    ) -> tuple[str, str | None]:
        """
        Call the OpenAI Chat Completions API for reasoning-tier models (o1/o3/
        gpt-5-thinking-style). Non-streaming by design — select this provider
        explicitly in config for such models rather than relying on name-sniffing,
        since streaming support and parameter names have shifted across releases
        within this model family and aiv has no streaming-dependent UX to lose.

        Differences from OpenAIProvider:
        - sys_prompt is injected under the "developer" role rather than "system".
        - token limit is passed as max_completion_tokens rather than max_tokens.
        - no stream=True; response is read back as a single completed message.

        Caveat: if a future reasoning model reintroduces "system" role support or
        reverts to max_tokens, this module may need a per-model branch at that point;
        not anticipated here since the user opts into this provider explicitly.
        """
        client = openai.OpenAI(api_key=api_key)
        full_messages = cast(
            Iterable[ChatCompletionMessageParam],
            [{"role": "developer", "content": sys_prompt}, *messages],
        )

        response = client.chat.completions.create(
            model=model,
            max_completion_tokens=max_tokens,
            messages=full_messages,
        )

        choice = response.choices[0]
        response_text = choice.message.content or ""
        finish_reason = choice.finish_reason
        stop_reason = "max_tokens" if finish_reason == "length" else finish_reason

        return response_text, stop_reason

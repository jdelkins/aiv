from __future__ import annotations
from typing import cast, Iterable

import anthropic
from anthropic.types import MessageParam
from aiv.conversation import GenericMessageParam


class AnthropicProvider:
    def call(
        self,
        messages: list[GenericMessageParam],
        model: str,
        max_tokens: int,
        sys_prompt: str,
        api_key: str,
    ) -> tuple[str, str | None]:
        """
        Call the Anthropic API with the given messages and return
        (response_text, stop_reason).
        Streams the response for lower latency on long outputs.
        stop_reason is Optional in the SDK's types (None while streaming/incomplete
        states), hence the str | None return type rather than str.

        cache_control is passed as-is per existing working usage (automatic/implicit
        caching against the stable prefix of system + prior turns) — not altered here.

        The Provider protocol types `messages` as list[GenericMessageParam] so the
        abstraction stays provider-agnostic; this module is the one place allowed to
        know the dicts are also shaped like Anthropic's MessageParam, so the cast
        below is a type-only assertion, not a runtime conversion.
        """
        client = anthropic.Anthropic(api_key=api_key)
        msgparams = cast(Iterable[MessageParam], messages)

        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            messages=msgparams,
            system=sys_prompt,
            cache_control={"type": "ephemeral"},
        ) as stream:
            response_text = ""
            for text in stream.text_stream:
                response_text += text
            final_message = stream.get_final_message()

        return response_text, final_message.stop_reason

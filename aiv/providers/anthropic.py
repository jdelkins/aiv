from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import cast

import anthropic
from anthropic.types import MessageParam

from aiv.conversation import GenericMessageParam
from aiv.providers import validate_provider_options


class AnthropicProvider:
    def call(
        self,
        messages: list[GenericMessageParam],
        model: str,
        max_tokens: int,
        sys_prompt: str,
        api_key: str,
        options: Mapping[str, object] | None = None,
    ) -> tuple[str, str | None]:
        """Stream a response and return (response_text, stop_reason).

        No provider-specific options are currently supported. Preserve automatic
        prompt caching against the stable prefix of system and prior turns.
        """
        validate_provider_options(options, provider_type="anthropic")

        client = anthropic.Anthropic(api_key=api_key)
        msgparams = cast(Iterable[MessageParam], messages)

        with client.messages.stream(
            model=model,
            max_tokens=max_tokens,
            messages=msgparams,
            system=sys_prompt,
            cache_control={"type": "ephemeral"},
        ) as stream:
            response_text = "".join(stream.text_stream)
            final_message = stream.get_final_message()

        return response_text, final_message.stop_reason

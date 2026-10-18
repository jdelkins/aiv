from __future__ import annotations
from typing import cast, Iterable

import openai
from openai.types.chat import ChatCompletionMessageParam
from aiv.conversation import GenericMessageParam


class OpenAIProvider:
    def call(
        self,
        messages: list[GenericMessageParam],
        model: str,
        max_tokens: int,
        sys_prompt: str,
        api_key: str,
    ) -> tuple[str, str | None]:
        """
        Call the OpenAI Chat Completions API with the given messages and return
        (response_text, stop_reason), normalized to match AnthropicProvider's
        contract — i.e. "max_tokens" rather than OpenAI's native "length" — so
        aiv.api.run_turn can check for truncation uniformly across providers.

        Caveats:
        - Uses the Chat Completions API (client.chat.completions.create), not the
          newer Responses API; sys_prompt is injected as a leading {"role": "system"}
          message since Chat Completions has no separate top-level system param.
        - Newer reasoning-tuned models (o1/o3/gpt-5-thinking-style) may reject the
          "system" role in favor of "developer", and may reject `max_tokens` in favor
          of `max_completion_tokens`. Not handled here; use the openai-reasoning
          provider for such models instead.
        - No prompt-caching parameter is passed or needed — OpenAI caches eligible
          prompt prefixes (>=1024 tokens) automatically server-side.
        - Unlike AnthropicProvider, stream chunks may have `delta.content is None`
          (e.g. on role-only or finish chunks), hence the explicit None check below.
        """
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

        response_text = ""
        finish_reason: str | None = None
        for chunk in stream:
            choice = chunk.choices[0]
            if choice.delta.content is not None:
                response_text += choice.delta.content
            if choice.finish_reason is not None:
                finish_reason = choice.finish_reason

        stop_reason = "max_tokens" if finish_reason == "length" else finish_reason
        return response_text, stop_reason

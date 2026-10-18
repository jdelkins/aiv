from __future__ import annotations
from typing import Protocol
from aiv.conversation import GenericMessageParam


class Provider(Protocol):
    def call(
        self,
        messages: list[GenericMessageParam],
        model: str,
        max_tokens: int,
        sys_prompt: str,
        api_key: str,
    ) -> tuple[str, str | None]:
        """Call the provider's API and return (response_text, normalized_stop_reason).

        normalized_stop_reason should be the literal string "max_tokens" when the
        response was truncated due to the token limit, regardless of what the
        underlying SDK calls it (e.g. OpenAI's "length"), so that aiv.api.run_turn
        can check for it uniformly. Otherwise, the raw provider-native reason may be
        returned as-is since nothing else currently inspects it.
        """
        ...


# Caveat: needs `from aiv.conversation import GenericMessageParam` added to the
# imports at the top of this file. Also, per the earlier note, the concrete
# implementations (AnthropicProvider.call, OpenAIProvider.call,
# OpenAIReasoningProvider.call) should update their `messages: list[dict]`
# parameter annotations to `list[GenericMessageParam]` too, to stay consistent
# with the Protocol they're structurally implementing — not strictly required at
# runtime since Protocol satisfaction here is duck-typed, but worth doing for
# type-checker agreement across the whole boundary.
def get_provider(name: str) -> Provider:
    # Imports are deferred into each branch so that selecting one provider never
    # requires another provider's SDK to be installed (all are optional
    # dependencies from the package's point of view).
    if name == "anthropic":
        from aiv.providers.anthropic import AnthropicProvider

        return AnthropicProvider()
    if name == "openai":
        from aiv.providers.openai import OpenAIProvider

        return OpenAIProvider()
    if name == "openai-reasoning":
        from aiv.providers.openai_reasoning import OpenAIReasoningProvider

        return OpenAIReasoningProvider()
    raise ValueError(f"aiv: unknown provider {name!r}")

from __future__ import annotations

from collections.abc import Collection, Mapping
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
        options: Mapping[str, object] | None = None,
    ) -> tuple[str, str | None]:
        """Return (response_text, normalized_stop_reason).

        Normalize token-limit truncation to "max_tokens"; other stop reasons
        may retain their provider-native values.

        Validate options before creating a client or making an API request.
        None and an empty mapping both preserve the API's default behavior.
        """
        ...


def validate_provider_options(
    options: object,
    *,
    provider_type: str,
    supported_options: Collection[str] = (),
) -> None:
    """Reject unsupported option names; adapters validate supported values."""
    if options is None:
        return
    if not isinstance(options, Mapping):
        raise ValueError(
            f"aiv: options for provider type {provider_type!r} must be a mapping"
        )

    unknown = [name for name in options if name not in supported_options]
    if unknown:
        names = ", ".join(sorted(repr(name) for name in unknown))
        supported = ", ".join(sorted(supported_options)) or "(none)"
        raise ValueError(
            f"aiv: unsupported options for provider type {provider_type!r}: "
            f"{names}; supported options: {supported}"
        )


def get_provider(provider_type: str) -> Provider:
    """Instantiate an implementation by type, not by configured profile name."""
    # Deferred imports keep SDK dependencies isolated to the selected type.
    if provider_type == "anthropic":
        from aiv.providers.anthropic import AnthropicProvider

        return AnthropicProvider()
    if provider_type == "openai":
        from aiv.providers.openai import OpenAIProvider

        return OpenAIProvider()
    if provider_type == "openai-reasoning":
        from aiv.providers.openai_reasoning import OpenAIReasoningProvider

        return OpenAIReasoningProvider()
    raise ValueError(f"aiv: unknown provider type {provider_type!r}")

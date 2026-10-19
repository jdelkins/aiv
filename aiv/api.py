from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from aiv.content import build_user_content
from aiv.conversation import append_user_turn, save_conversation, GenericMessageParam
from aiv.models import InteractionMode
from aiv.providers import get_provider


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------


def run_turn(
    prompt: str,
    context_files: list[str],
    stdin_data: str | None,
    mode: InteractionMode,
    mode_suffix: str,
    api_key: str,
    model: str,
    provider_type: str,
    max_tokens: int,
    sys_prompt: str,
    conv_path: Path,
    provider_options: Mapping[str, object] | None = None,
) -> str:
    """Build a user turn, call the resolved implementation, and save its response.

    provider_type is an implementation type, not a configured profile name.
    Credential and model checks occur before modifying conversation history.
    Provider-specific options are validated by the selected adapter.
    """
    if not api_key or not api_key.strip():
        raise ValueError("aiv: api_key not set")
    if not model or not model.strip():
        raise ValueError("aiv: model not set")

    impl = get_provider(provider_type)

    content = build_user_content(prompt, context_files, stdin_data, mode_suffix)
    messages = append_user_turn(mode, content, conv_path)
    msgparams: list[GenericMessageParam] = [m["message"] for m in messages]

    response_text, stop_reason = impl.call(
        messages=msgparams,
        model=model,
        max_tokens=max_tokens,
        sys_prompt=sys_prompt,
        api_key=api_key,
        options=provider_options,
    )

    if stop_reason == "max_tokens":
        response_text += "\n\n[aiv: WARNING: response truncated - max_tokens too low]"

    messages.append(
        {"mode": mode, "message": {"role": "assistant", "content": response_text}}
    )
    save_conversation(messages, conv_path)

    return response_text

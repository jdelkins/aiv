from __future__ import annotations
from aiv.models import InteractionMode

import anthropic
from pathlib import Path

from aiv.content import build_user_content
from aiv.conversation import append_user_turn, save_conversation


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _call_api(
    messages: list,
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
    """
    client = anthropic.Anthropic(api_key=api_key)

    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        system=sys_prompt,
        cache_control={"type": "ephemeral"},
    ) as stream:
        response_text = ""
        for text in stream.text_stream:
            response_text += text
        final_message = stream.get_final_message()

    return response_text, final_message.stop_reason


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
    max_tokens: int,
    sys_prompt: str,
    conv_path: Path,
) -> str:
    """
    Build a user turn, append it to the conversation, call the Anthropic API,
    append the assistant response, save, and return the response text.

    conv_path is now an explicit parameter (resolved once in PipelineContext)
    rather than being re-resolved on every call.

    Appends a warning to the returned text if the response was truncated by
    max_tokens so the user is never silently given an incomplete answer.
    """
    content = build_user_content(prompt, context_files, stdin_data, mode_suffix)
    messages = append_user_turn(mode, content, conv_path)
    msgparams = [m["message"] for m in messages]

    response_text, stop_reason = _call_api(
        messages=msgparams,
        model=model,
        max_tokens=max_tokens,
        sys_prompt=sys_prompt,
        api_key=api_key,
    )

    if stop_reason == "max_tokens":
        response_text += "\n\n[aiv: WARNING: response truncated - max_tokens too low]"

    messages.append(
        {"mode": mode, "message": {"role": "assistant", "content": response_text}}
    )
    save_conversation(messages, conv_path)

    return response_text

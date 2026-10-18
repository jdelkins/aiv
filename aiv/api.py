from __future__ import annotations
from aiv.models import InteractionMode

from pathlib import Path

from aiv.content import build_user_content
from aiv.conversation import append_user_turn, save_conversation, GenericMessageParam
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
    provider: str,
    max_tokens: int,
    sys_prompt: str,
    conv_path: Path,
) -> str:
    """
    Build a user turn, append it to the conversation, call the selected
    provider's API, append the assistant response, save, and return the
    response text.

    conv_path is now an explicit parameter (resolved once in PipelineContext)
    rather than being re-resolved on every call.

    Appends a warning to the returned text if the response was truncated by
    max_tokens so the user is never silently given an incomplete answer.
    """
    content = build_user_content(prompt, context_files, stdin_data, mode_suffix)
    messages = append_user_turn(mode, content, conv_path)
    msgparams: list[GenericMessageParam] = [m["message"] for m in messages]

    impl = get_provider(provider)
    response_text, stop_reason = impl.call(
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

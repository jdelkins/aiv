from __future__ import annotations
from aiv.models import InteractionMode, ConversationError
import subprocess
from typing import TypedDict


import json
import sys
from pathlib import Path

from anthropic.types import MessageParam
from filelock import BaseFileLock, FileLock

from aiv.config import FALLBACK_CONVERSATION_FILE


class StoredMessage(TypedDict):
    message: MessageParam
    mode: InteractionMode


# ---------------------------------------------------------------------------
# Format helpers (live here because they operate on conversation content)
# ---------------------------------------------------------------------------


def format_bytes(n: int) -> str:
    if n < 1024:
        return f"{n}B"
    elif n < 1024 * 1024:
        return f"{n / 1024:.1f}KB"
    else:
        return f"{n / (1024 * 1024):.1f}MB"


def parse_range(range_str: str, max_num: int) -> tuple[int, int] | None:
    """
    Parse a range string like '3', '3-7', '3-' into (start, end) 1-indexed inclusive.
    Returns None on parse failure or out-of-bounds start.
    End is clamped to max_num.
    """
    range_str = range_str.strip()
    if "-" in range_str:
        parts = range_str.split("-", 1)
        try:
            start = int(parts[0])
        except ValueError:
            return None
        end_str = parts[1].strip()
        if end_str == "":
            end = max_num
        else:
            try:
                end = int(end_str)
            except ValueError:
                return None
    else:
        try:
            start = end = int(range_str)
        except ValueError:
            return None

    if start < 1 or end < start or start > max_num:
        return None
    end = min(end, max_num)
    return (start, end)


def first_line(content: str) -> str:
    """Return the first non-empty line of content after stripping context blocks."""
    stripped = strip_context_blocks(content).strip()
    if not stripped:
        for line in content.splitlines():
            line = line.strip()
            if line:
                return line[:80]
    for line in stripped.splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return ""


def strip_context_blocks(content: str) -> str:
    """Remove ---CONTEXT_FILE:--- and ---CONTEXT_TXT:--- blocks, return remaining text."""
    lines = content.splitlines()
    out = []
    in_block = False
    for line in lines:
        if line.startswith("---CONTEXT_FILE:") or line.startswith("---CONTEXT_TXT:"):
            in_block = True
            continue
        if in_block:
            if line.strip() == "---END---":
                in_block = False
            continue
        out.append(line)
    return "\n".join(out)


def count_context_blocks(content: str) -> int:
    count = 0
    for line in content.splitlines():
        if line.startswith("---CONTEXT_FILE:") or line.startswith("---CONTEXT_TXT:"):
            count += 1
    return count


# ---------------------------------------------------------------------------
# Conversation file path resolution
# ---------------------------------------------------------------------------


def _resolve_git_root() -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        return Path(result.stdout.strip()) if result.returncode == 0 else None
    except Exception:
        return None


def get_conversation_file() -> Path:
    """
    Resolve the default conversation file path.
    Prefers a .aiv-conversation.json at the git repo root if inside a repo;
    falls back to ~/.config/aiv/conversation.json.
    Callers that have a PipelineContext should use ctx.conv_path instead of
    calling this directly — this is used during startup before ctx exists.
    The git subprocess result is cached in _git_root so repeated calls
    (e.g. from content.py) pay the cost at most once per process.
    """
    root = _resolve_git_root()
    return (
        root / ".aiv-conversation.json"
        if root is not None
        else FALLBACK_CONVERSATION_FILE
    )


# ---------------------------------------------------------------------------
# Locking
# ---------------------------------------------------------------------------


def _conv_lock(path: Path, lock: BaseFileLock | None) -> BaseFileLock:
    """Return the provided lock if given, otherwise create a new one for path."""
    return lock if lock is not None else FileLock(path.with_suffix(".lock"))


# ---------------------------------------------------------------------------
# Load / save / reset
# ---------------------------------------------------------------------------


def load_conversation(
    path: Path, lock: BaseFileLock | None = None
) -> list[StoredMessage]:
    """
    Read conversation JSON from disk. Returns [] if the file does not exist.
    Raises SystemExit on malformed JSON — callers should treat this as fatal
    since we never want to silently overwrite a user's conversation file.
    If lock is provided (and already acquired by the caller) it is re-acquired
    via filelock's reentrant counter rather than creating a new lock object.
    """
    with _conv_lock(path, lock):
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(
                f"aiv: conversation file is not valid JSON: {path}\n  {e}",
                file=sys.stderr,
            )
            sys.exit(1)

        if not isinstance(data, dict):
            print(
                f"aiv: conversation file must be a JSON object: {path}", file=sys.stderr
            )
            sys.exit(1)

        if "messages" not in data:
            # Tolerate an empty/keyless object — treat as empty conversation
            print(
                f"aiv: warning: conversation file has no 'messages' key, treating as empty: {path}",
                file=sys.stderr,
            )
            return []

        messages = data["messages"]
        if not isinstance(messages, list):
            print(
                f"aiv: conversation file 'messages' must be a list: {path}",
                file=sys.stderr,
            )
            sys.exit(1)

        warnings = validate_conversation(messages)
        for w in warnings:
            print(f"aiv: conversation file {path}: {w}", file=sys.stderr)

        return messages


def save_conversation(
    messages: list[StoredMessage], path: Path, lock: BaseFileLock | None = None
) -> None:
    with _conv_lock(path, lock):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"messages": messages}, indent=2))


def reset_conversation(path: Path) -> None:
    save_conversation([], path)


# ---------------------------------------------------------------------------
# Validation (called once at startup after path is resolved)
# ---------------------------------------------------------------------------


# Warning strings are returned so the caller decides how to present them.
def validate_conversation(messages: list[StoredMessage]) -> list[str]:
    """
    Validate the structure of a loaded conversation. Raises ConversationError on
    structural problems that would cause API failures or data loss. Returns a list
    of warning strings for recoverable issues (wrong first role, consecutive
    same-role messages) — the caller is responsible for displaying them.

    Should be called in main() after load_conversation, before the pipeline runs.
    """
    warnings: list[str] = []

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise ConversationError(f"message {i} is not an object")
        if "mode" not in msg:
            raise ConversationError(f"message {i} missing 'mode'")
        if msg["mode"] not in (
            InteractionMode.CHAT,
            InteractionMode.CODE,
            InteractionMode.DEFAULT,
            InteractionMode.CUSTOM,
        ):
            raise ConversationError(f"message {i} has invalid mode {msg['mode']!r}")
        if "message" not in msg:
            raise ConversationError(f"message {i} missing 'message'")
        msgparam = msg["message"]
        if "role" not in msgparam:
            raise ConversationError(f"message {i} missing 'role'")
        if "content" not in msgparam:
            raise ConversationError(f"message {i} missing 'content'")
        if msgparam["role"] not in ("user", "assistant"):
            raise ConversationError(
                f"message {i} has invalid role {msgparam['role']!r}"
            )
        if not isinstance(msgparam["content"], (str, list)):
            raise ConversationError(f"message {i} 'content' must be a string or list")

    if messages and messages[0]["message"]["role"] != "user":
        warnings.append(
            f"first message is not from 'user' — the Anthropic API may reject this"
        )

    for i in range(1, len(messages)):
        if (
            messages[i]["message"]["role"] == "assistant"
            and messages[i - 1]["message"]["role"] == "assistant"
        ):
            warnings.append(
                f"consecutive assistant messages at positions {i - 1} and {i} "
                f"— the Anthropic API may reject this"
            )

    return warnings


# ---------------------------------------------------------------------------
# Conversation mutation helpers
# ---------------------------------------------------------------------------


def append_user_turn(
    mode: InteractionMode, content: str, path: Path
) -> list[StoredMessage]:
    """
    Append a user message to the conversation file and return the updated list.
    Holds a single exclusive lock across the read-modify-write to prevent races.
    """
    lock: BaseFileLock = FileLock(path.with_suffix(".lock"))
    with lock:
        messages = load_conversation(path, lock=lock)
        messages.append({"mode": mode, "message": {"role": "user", "content": content}})
        save_conversation(messages, path, lock=lock)
    return messages


# ---------------------------------------------------------------------------
# Interaction grouping
# ---------------------------------------------------------------------------


def build_interactions(messages: list[StoredMessage]) -> list[list[StoredMessage]]:
    """
    Group messages into interactions. Each interaction starts at a user turn
    and contains all subsequent messages until (but not including) the next
    user turn. Interaction numbers are 1-indexed.
    """
    interactions: list[list[StoredMessage]] = []
    current: list[StoredMessage] | None = None

    for msg in messages:
        if msg["message"]["role"] == "user":
            if current is not None:
                interactions.append(current)
            current = [msg]
        else:
            if current is None:
                current = [msg]
            else:
                current.append(msg)

    if current is not None:
        interactions.append(current)

    return interactions


def flatten_interactions(
    interactions: list[list[StoredMessage]],
) -> list[StoredMessage]:
    return [msg for interaction in interactions for msg in interaction]

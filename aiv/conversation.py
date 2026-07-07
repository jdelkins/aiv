from __future__ import annotations
from functools import lru_cache
import subprocess
from typing import Literal, cast


import json
import sys
from pathlib import Path

from anthropic.types import MessageParam

from aiv.config import FALLBACK_CONVERSATION_FILE


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


@lru_cache(maxsize=None)
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
# Load / save / reset
# ---------------------------------------------------------------------------


def load_conversation(path: Path) -> list[MessageParam]:
    """
    Read conversation JSON from disk. Returns [] if the file does not exist.
    Raises SystemExit on malformed JSON — callers should treat this as fatal
    since we never want to silently overwrite a user's conversation file.
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(
            f"aiv: conversation file is not valid JSON: {path}\n  {e}", file=sys.stderr
        )
        sys.exit(1)

    if not isinstance(data, dict):
        print(f"aiv: conversation file must be a JSON object: {path}", file=sys.stderr)
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
            f"aiv: conversation file 'messages' must be a list: {path}", file=sys.stderr
        )
        sys.exit(1)

    return messages


def save_conversation(messages: list[MessageParam], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"messages": messages}, indent=2))


def reset_conversation(path: Path) -> None:
    save_conversation([], path)


# ---------------------------------------------------------------------------
# Validation (called once at startup after path is resolved)
# ---------------------------------------------------------------------------


def validate_conversation(messages: list[MessageParam], path: Path) -> None:
    """
    Validate the structure of a loaded conversation. Hard-errors on structural
    problems that would cause API failures or data loss. Warns on recoverable
    issues (wrong first role, consecutive same-role messages).

    Should be called in main() after load_conversation, before the pipeline runs.
    """
    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            print(
                f"aiv: conversation file {path}: message {i} is not an object",
                file=sys.stderr,
            )
            sys.exit(1)
        if "role" not in msg:
            print(
                f"aiv: conversation file {path}: message {i} missing 'role'",
                file=sys.stderr,
            )
            sys.exit(1)
        if "content" not in msg:
            print(
                f"aiv: conversation file {path}: message {i} missing 'content'",
                file=sys.stderr,
            )
            sys.exit(1)
        if msg["role"] not in ("user", "assistant"):
            print(
                f"aiv: conversation file {path}: message {i} has invalid role {msg['role']!r}",
                file=sys.stderr,
            )
            sys.exit(1)
        if not isinstance(msg["content"], (str, list)):
            print(
                f"aiv: conversation file {path}: message {i} 'content' must be a string or list",
                file=sys.stderr,
            )
            sys.exit(1)

    if messages and messages[0]["role"] != "user":
        print(
            f"aiv: warning: conversation file {path}: first message is not from 'user' — "
            "the Anthropic API may reject this",
            file=sys.stderr,
        )

    for i in range(1, len(messages)):
        if (
            messages[i]["role"] == "assistant"
            and messages[i - 1]["role"] == "assistant"
        ):
            print(
                f"aiv: warning: conversation file {path}: consecutive assistant messages "
                f"at positions {i - 1} and {i} — the Anthropic API may reject this",
                file=sys.stderr,
            )


# ---------------------------------------------------------------------------
# Conversation mutation helpers
# ---------------------------------------------------------------------------


def append_user_turn(content: str, path: Path) -> list[MessageParam]:
    """
    Append a user message to the conversation file and return the updated list.
    """
    messages = load_conversation(path)
    messages.append({"role": "user", "content": content})
    save_conversation(messages, path)
    return messages


# ---------------------------------------------------------------------------
# Interaction grouping
# ---------------------------------------------------------------------------


def build_interactions(messages: list[MessageParam]) -> list[list[MessageParam]]:
    """
    Group messages into interactions. Each interaction starts at a user turn
    and contains all subsequent messages until (but not including) the next
    user turn. Interaction numbers are 1-indexed.
    """
    interactions: list[list[MessageParam]] = []
    current: list[MessageParam] | None = None

    for msg in messages:
        if msg["role"] == "user":
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


def flatten_interactions(interactions: list[list[MessageParam]]) -> list[MessageParam]:
    return [msg for interaction in interactions for msg in interaction]

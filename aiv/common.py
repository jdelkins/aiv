from anthropic.types import MessageParam
import json
import subprocess
from pathlib import Path
from importlib.metadata import version as pkg_version, PackageNotFoundError

CONFIG_DIR = Path.home() / ".config" / "aiv"
CONFIG_FILE = CONFIG_DIR / "config"
FALLBACK_CONVERSATION_FILE = CONFIG_DIR / "conversation.json"


def get_version() -> str:
    try:
        return pkg_version("aiv")
    except PackageNotFoundError:
        return "unknown"


def find_repo_root() -> Path | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return Path(result.stdout.strip())
    except Exception:
        pass
    return None


def get_conversation_file() -> Path:
    repo_root = find_repo_root()
    if repo_root is not None:
        return repo_root / ".aiv-conversation.json"
    return FALLBACK_CONVERSATION_FILE


def load_config() -> dict:
    config = {}
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"aiv: config file not found: {CONFIG_FILE}")
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip().strip('"')
            if key == "api_key":
                config["api_key"] = value
            elif key == "model":
                config["model"] = value
            elif key == "max_tokens":
                config["max_tokens"] = value
            elif key in ("sys_prompt", "system_prompt"):
                config["sys_prompt"] = value
    return config


def load_conversation(path: Path) -> list[MessageParam]:
    if path.exists():
        try:
            data = json.loads(path.read_text())
            return data.get("messages", [])
        except json.JSONDecodeError:
            pass
    return []


def save_conversation(messages: list[MessageParam], path: Path):
    path.write_text(json.dumps({"messages": messages}, indent=2))


def reset_conversation(path: Path):
    save_conversation([], path)


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
                # Leading assistant turn — treat as its own interaction
                current = [msg]
            else:
                current.append(msg)

    if current is not None:
        interactions.append(current)

    return interactions


def flatten_interactions(interactions: list[list[MessageParam]]) -> list[MessageParam]:
    return [msg for interaction in interactions for msg in interaction]


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


def first_line(content: str) -> str:
    stripped = strip_context_blocks(content).strip()
    for line in stripped.splitlines():
        line = line.strip()
        if line:
            return line[:80]
    return ""


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
    Returns None on parse failure.
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

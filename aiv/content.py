from __future__ import annotations

import glob
import subprocess
from pathlib import Path

from aiv.conversation import strip_context_blocks


# ---------------------------------------------------------------------------
# File location annotation
# ---------------------------------------------------------------------------


def _find_repo_root() -> Path | None:
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


def find_file_location(content: str) -> str:
    """
    Attempt to locate content within the repo (or cwd) using grep.
    Returns a location hint string like '[path/to/file.py:12:34]' or ''.
    Runs on every stdin-bearing prompt — kept as-is per design decision.
    """
    lines = [l for l in content.splitlines() if len(l.strip()) > 5]
    if not lines:
        return ""
    pattern = "\n".join(lines)
    counts: dict[str, int] = {}
    try:
        if _find_repo_root() is not None:
            cmd = ["git", "grep", "-Fnf", "-"]
        else:
            cmd = ["grep", "-rFnf", "-", "."]
        result = subprocess.run(
            cmd,
            input=pattern,
            capture_output=True,
            text=True,
        )
        for line in result.stdout.splitlines():
            fname = line.split(":")[0]
            counts[fname] = counts.get(fname, 0) + 1
    except Exception:
        return ""
    if not counts:
        return ""
    best_file = max(counts, key=lambda k: counts[k])
    first_ln = lines[0]
    try:
        result2 = subprocess.run(
            ["grep", "-Fn", first_ln, best_file], capture_output=True, text=True
        )
        if result2.stdout:
            ln_s = int(result2.stdout.split(":")[0])
            ln_e = ln_s + len(lines) - 1
            return f"[{best_file}:{ln_s}:{ln_e}]"
    except Exception:
        pass
    return f"[{best_file}]"


# ---------------------------------------------------------------------------
# User message content builder
# ---------------------------------------------------------------------------


def build_user_content(
    prompt: str,
    context_files: list[str],
    stdin_data: str | None,
    mode_suffix: str = "",
) -> str:
    """
    Build the user message content string from prompt, context files, and
    optional stdin data.

    Context files are expanded as globs. The '-' sentinel is skipped here
    (stdin is passed explicitly via stdin_data). File blocks use the
    ---CONTEXT_FILE:[path]--- / ---END--- envelope; stdin uses
    ---CONTEXT_TXT:[location_hint]--- / ---END---.
    """
    parts = []

    for pattern in context_files:
        if pattern == "-":
            continue
        for fpath in sorted(glob.glob(pattern, recursive=True)):
            if not Path(fpath).is_file():
                continue
            parts.append(f"---CONTEXT_FILE:[{fpath}]---")
            parts.append(Path(fpath).read_text(errors="replace"))
            parts.append("---END---")

    if stdin_data is not None:
        loc = find_file_location(stdin_data)
        parts.append(f"---CONTEXT_TXT:{loc}---")
        parts.append(stdin_data)
        parts.append("---END---")
        parts.append(prompt + mode_suffix)
    else:
        parts.append(prompt + mode_suffix)

    return "\n".join(parts)

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


# ---------------------------------------------------------------------------
# User message content builder
# ---------------------------------------------------------------------------


def build_user_content(
    prompt: str,
    context_files: list[str],
    stdin_data: str | None,
    mode_suffix: str = "",
    stdin_ctx_file: str | None = None,
    stdin_ctx_range: str | None = None,
) -> str:
    """
    Build the user message content string from prompt, context files, and
    optional stdin data.

    Context files are expanded as globs. The '-' sentinel is skipped here
    (stdin is passed explicitly via stdin_data). File blocks use the
    ---CONTEXT_FILE:[path]--- / ---END--- envelope; stdin uses
    ---CONTEXT_TXT:[location_hint]--- / ---END---.

    If stdin_ctx_file is provided the file/range are used to build the hint,
    if provided.
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
        loc = ""
        if stdin_ctx_file is not None:
            if stdin_ctx_range is not None:
                loc = f":[{stdin_ctx_file}:{stdin_ctx_range}]"
            else:
                loc = f":[{stdin_ctx_file}]"
        parts.append(f"---CONTEXT_TXT{loc}---")
        parts.append(stdin_data)
        parts.append("---END---")
        parts.append(prompt + mode_suffix)
    else:
        parts.append(prompt + mode_suffix)

    return "\n".join(parts)

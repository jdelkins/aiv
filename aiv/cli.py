#!/usr/bin/env python3

import anthropic
import argparse
import glob
import subprocess
import sys
from pathlib import Path
from anthropic.types import MessageParam

from aiv.common import (
    get_conversation_file,
    load_config,
    load_conversation,
    save_conversation,
)

# -C mode: appended to user prompt to nudge toward markdown formatting
MODE_CHAT_SUFFIX = "\n\nRespond using markdown formatting including triple backticks where it aids readability."

# -X mode: appended to user prompt to strongly suppress markdown/backtick wrapping.
MODE_CODE_SUFFIX = (
    "\n\nRespond with raw code only. No markdown, no triple backtick fences. "
    "If you have important caveats or usage nuances, include them as code comments."
)


def find_file_location(content: str) -> str:
    lines = [l for l in content.splitlines() if len(l.strip()) > 5]
    if not lines:
        return ""
    pattern = "\n".join(lines)
    counts: dict[str, int] = {}
    try:
        if find_repo_root() is not None:
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
    first_line = lines[0]
    try:
        result2 = subprocess.run(
            ["grep", "-Fn", first_line, best_file], capture_output=True, text=True
        )
        if result2.stdout:
            ln_s = int(result2.stdout.split(":")[0])
            ln_e = ln_s + len(lines) - 1
            return f"[{best_file}:{ln_s}:{ln_e}]"
    except Exception:
        pass
    return f"[{best_file}]"


# find_file_location references find_repo_root but doesn't import it above —
# importing here to keep it local to cli.py as agreed
from aiv.common import find_repo_root


def build_user_content(
    prompt: str,
    context_files: list,
    stdin_data: str | None,
    mode_suffix: str = "",
) -> str:
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


def main():
    parser = argparse.ArgumentParser(
        prog="aiv",
        description="AI Valve: Pipes for AI",
        add_help=False,
    )
    parser.add_argument(
        "-c", dest="context_files", action="append", default=[], metavar="file_pattern"
    )
    parser.add_argument("--reset", "-R", dest="reset", action="store_true")
    parser.add_argument("-r", dest="repeat_input", action="store_true")
    parser.add_argument("-m", dest="model", default=None)
    parser.add_argument("-s", dest="sys_prompt", default=None)
    parser.add_argument("-C", dest="mode_chat", action="store_true")
    parser.add_argument("-X", dest="mode_code", action="store_true")
    parser.add_argument("-h", "-v", dest="help", action="store_true")
    parser.add_argument("prompt", nargs="*")
    args = parser.parse_args()

    if args.help:
        print(
            """aiv - AI Valve: Pipes for AI
Usage   : aiv [options] [prompt]
Options : -c [file_pattern|-] Add context from files (glob pattern) or stdin (-)
          -r                  Repeat the input before output
          -R, --reset         Reset conversation thread
          -C                  Conversational mode (markdown enabled)
          -X                  Code-only mode (no markdown, caveats as comments)
          -m MODEL            Use specified model
          -h                  Display this help message
          -v                  Display version information
          -s [prompt]         Overwrite system prompt""",
            file=sys.stderr,
        )
        sys.exit(0)

    if args.mode_chat and args.mode_code:
        print("aiv: -C and -X are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    try:
        config = load_config()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    api_key = config.get("api_key", "")
    model = args.model or config.get("model", "claude-3-7-sonnet-latest")
    sys_prompt = args.sys_prompt or config.get("sys_prompt", "")
    max_tokens_raw = config.get("max_tokens", "4096")
    if not max_tokens_raw.isdigit():
        print("aiv: max_tokens must be a positive integer", file=sys.stderr)
        sys.exit(1)
    max_tokens = int(max_tokens_raw)
    if not api_key:
        print("aiv: api_key not set", file=sys.stderr)
        sys.exit(1)

    if args.mode_chat:
        mode_suffix = MODE_CHAT_SUFFIX
    elif args.mode_code:
        mode_suffix = MODE_CODE_SUFFIX
    else:
        mode_suffix = ""

    conversation_file = get_conversation_file()

    prompt = " ".join(args.prompt)

    stdin_data = None
    stdin_is_tty = sys.stdin.isatty()
    has_stdin_context = "-" in args.context_files

    if not stdin_is_tty:
        raw = sys.stdin.read()
        if has_stdin_context:
            stdin_data = raw
        else:
            if not prompt:
                prompt = raw.rstrip("\n")
            else:
                stdin_data = raw

    messages: list[MessageParam] = (
        [] if args.reset else load_conversation(conversation_file)
    )

    # Exit early if no prompt — stage context for future use if provided, then quit
    if not prompt:
        if args.context_files:
            content = build_user_content("", args.context_files, stdin_data)
            messages.append({"role": "user", "content": content})
        save_conversation(messages, conversation_file)
        sys.exit(0)

    content = build_user_content(prompt, args.context_files, stdin_data, mode_suffix)

    if args.repeat_input:
        print(prompt)

    messages.append({"role": "user", "content": content})
    save_conversation(messages, conversation_file)

    client = anthropic.Anthropic(api_key=api_key)

    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        messages=messages,
        **({"system": sys_prompt} if sys_prompt else {}),
    ) as stream:
        response_text = ""
        for text in stream.text_stream:
            print(text, end="", flush=True)
            response_text += text
        print()

    messages.append({"role": "assistant", "content": response_text})
    save_conversation(messages, conversation_file)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import anthropic
import argparse
import glob
import subprocess
import sys
from pathlib import Path
from anthropic.types import MessageParam

from aiv.common import (
    get_version,
    get_conversation_file,
    load_config,
    load_conversation,
    save_conversation,
    reset_conversation,
    find_repo_root,
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
        "--context",
        "-c",
        dest="context_files",
        action="append",
        default=[],
        metavar="file_pattern",
    )
    parser.add_argument("--reset", "-R", dest="reset", action="store_true")
    parser.add_argument("--model", "-m", dest="model", default=None)
    parser.add_argument("--sys-prompt", "-s", dest="sys_prompt", default=None)
    parser.add_argument("--chat", "-C", dest="mode_chat", action="store_true")
    parser.add_argument("--code", "-X", dest="mode_code", action="store_true")
    parser.add_argument("--repl", "-i", dest="repl", action="store_true")
    parser.add_argument("--help", "-h", dest="help", action="store_true")
    parser.add_argument("--version", "-v", dest="version", action="store_true")
    parser.add_argument("prompt", nargs="*")
    args = parser.parse_args()

    if args.help:
        print(
            """aiv - AI Valve: Pipes for AI
Usage   : aiv [options] [prompt]
Options : -c, --context [file_pattern|-]  Add context from files (glob pattern) or stdin (-)
          -R, --reset                     Reset conversation thread
          -C, --chat                      Conversational mode (markdown enabled)
          -X, --code                      Code-only mode (no markdown, caveats as comments)
          -i, --repl                      After processing, launch interactive REPL
          -h, --help                      Display this help message
          -v, --version                   Display version information
          -m, --model MODEL               Override Anthropic model
          -s, --sys-prompt PROMPT         Override system prompt""",
            file=sys.stderr,
        )
        sys.exit(0)

    if args.version:
        print(f"aiv {get_version()}", file=sys.stderr)
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

    # When --repl is given and no explicit mode flag, default to chat mode
    if args.repl and not args.mode_chat and not args.mode_code:
        mode_suffix = MODE_CHAT_SUFFIX
        repl_mode_code = False
    elif args.mode_chat:
        mode_suffix = MODE_CHAT_SUFFIX
        repl_mode_code = False
    elif args.mode_code:
        mode_suffix = MODE_CODE_SUFFIX
        repl_mode_code = True
    else:
        mode_suffix = ""
        repl_mode_code = False

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

    # When --repl is set, hand everything off to the REPL immediately so the
    # initial prompt (if any) is processed through the same glow pipeline as
    # subsequent turns, and the help banner appears before any response.
    if args.repl:
        # Apply reset here before handing off; REPL receives reset=False so it
        # doesn't wipe the conversation a second time after we've already loaded it.
        if args.reset:
            reset_conversation(conversation_file)
        from aiv.repl import run as repl_run

        repl_run(
            model=args.model,
            sys_prompt=args.sys_prompt,
            mode_code=repl_mode_code,
            reset=False,
            initial_prompt=prompt if prompt else None,
            initial_context_files=args.context_files if args.context_files else None,
            initial_stdin_data=stdin_data,
        )
        sys.exit(0)

    # --- Non-repl path below ---

    messages: list[MessageParam] = (
        [] if args.reset else load_conversation(conversation_file)
    )

    if not prompt:
        if args.context_files:
            content = build_user_content("", args.context_files, stdin_data)
            messages.append({"role": "user", "content": content})
        save_conversation(messages, conversation_file)
        sys.exit(0)

    content = build_user_content(prompt, args.context_files, stdin_data, mode_suffix)

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

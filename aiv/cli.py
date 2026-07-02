#!/usr/bin/env python3

import sys
import argparse

from aiv.common import get_version, load_config
from aiv.commands import (
    PipelineContext,
    Command,
    run_pipeline,
    commands_from_args,
)


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
    parser.add_argument(
        "--history", "-H", dest="history", nargs="?", const=True, default=None
    )
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
          -i, --repl                      Enter interactive REPL (after processing any prompt)
          -H, --history [range]           Show conversation history and exit (or combine with -i)
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
    if not api_key:
        print("aiv: api_key not set", file=sys.stderr)
        sys.exit(1)

    max_tokens_raw = config.get("max_tokens", "4096")
    if not max_tokens_raw.isdigit():
        print("aiv: max_tokens must be a positive integer", file=sys.stderr)
        sys.exit(1)

    # ---------------------------------------------------------------------------
    # Stdin handling — must be done before building context or PipelineContext so
    # that ctx.stdin_data is set correctly before commands_from_args runs.
    #
    # Rules:
    #   - If "-" is explicit in context_files: read stdin into ctx.stdin_data;
    #     the ContextCommand("-") in the pipeline will consume it.
    #   - If "-" is NOT explicit and stdin is not a tty:
    #       - No prompt given: stdin becomes the prompt.
    #       - Prompt given: stdin becomes implicit context (ctx.stdin_data),
    #         consumed by the first PromptCommand call.
    # ---------------------------------------------------------------------------
    stdin_is_tty = sys.stdin.isatty()
    has_explicit_stdin_context = "-" in args.context_files
    stdin_data: str | None = None

    if not stdin_is_tty:
        raw = sys.stdin.read()
        if has_explicit_stdin_context:
            stdin_data = raw
        else:
            prompt_text = " ".join(args.prompt) if args.prompt else ""
            if not prompt_text:
                args.prompt = [raw.rstrip("\n")]
            else:
                stdin_data = raw

    ctx = PipelineContext(
        model=args.model or config.get("model", "claude-3-7-sonnet-latest"),
        sys_prompt=args.sys_prompt or config.get("sys_prompt", ""),
        mode_code=args.mode_code,
        api_key=api_key,
        max_tokens=int(max_tokens_raw),
        stdin_data=stdin_data,
        # interactive stays False here; run_repl_loop sets it True if -i is used
    )

    commands: list[Command] = commands_from_args(args)
    run_pipeline(commands, ctx)


if __name__ == "__main__":
    main()

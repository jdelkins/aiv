#!/usr/bin/env python3

import sys
import argparse

from aiv.config import get_config
from aiv.models import PipelineContext, InteractionMode
from aiv.specs import COMMAND_SPECS
from aiv.commands import commands_from_args, run_pipeline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiv",
        description="AI Valve: Pipes for AI",
        add_help=False,
    )

    for spec in COMMAND_SPECS:
        if not spec.long_option or not spec.argparse_kwargs:
            continue
        flags = [spec.long_option]
        if spec.short_option:
            flags.insert(0, spec.short_option)
        dest = spec.long_option.lstrip("-").replace("-", "_")
        parser.add_argument(*flags, dest=dest, **spec.argparse_kwargs)

    parser.add_argument("prompt", nargs="*")
    return parser


def print_cli_help():
    lines = [
        "aiv - AI Valve: Pipes for AI",
        "Usage   : aiv [options] [prompt]",
        "Options :",
    ]
    for spec in COMMAND_SPECS:
        if not spec.long_option:
            continue
        flags = spec.long_option
        if spec.short_option:
            flags = f"{spec.short_option}, {flags}"
        arg_hint = f" {spec.usage.upper()}" if spec.usage else ""
        col = f"  {flags}{arg_hint}"
        lines.append(f"{col:<38} {spec.help}")
    print("\n".join(lines), file=sys.stderr)


def main():
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "help", False):
        print_cli_help()
        sys.exit(0)

    if getattr(args, "chat", False) and getattr(args, "code", False):
        print("aiv: --chat and --code are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    try:
        config = get_config()
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    api_key = config.get("api_key", "")
    if not api_key:
        print("aiv: api_key not set", file=sys.stderr)
        sys.exit(1)

    max_tokens = config.get("max_tokens", 4096)

    # ---------------------------------------------------------------------------
    # Stdin handling — must be done before building PipelineContext so that
    # ctx.stdin_data is set correctly before commands_from_args runs.
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
    context_files = getattr(args, "context", []) or []
    has_explicit_stdin_context = any(
        c == "-" or c.startswith("-,") or c == "stdin" or c.startswith("stdin,")
        for c in context_files
    )
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

    initial_mode: InteractionMode = InteractionMode.DEFAULT
    if getattr(args, "chat", False):
        initial_mode = InteractionMode.CHAT
    elif getattr(args, "code", False):
        initial_mode = InteractionMode.CODE

    ctx = PipelineContext(
        model=config.get("model", "claude-sonnet-4-6"),
        sys_prompt=config.get("sys_prompt", ""),
        mode=initial_mode,
        api_key=api_key,
        max_tokens=int(max_tokens),
        stdin_data=stdin_data,
        piped_stdin=not stdin_is_tty,
        # conv_path resolved lazily on first access — commands that don't need
        # the conversation file (--version, --help, --repl) pay no I/O cost.
    )

    run_pipeline(commands_from_args(args), ctx)


if __name__ == "__main__":
    main()

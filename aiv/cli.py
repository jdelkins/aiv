#!/usr/bin/env python3

import sys
import argparse

from aiv.common import get_version, load_config
from aiv.models import PipelineContext, InteractionMode
from aiv.specs import COMMAND_SPECS, OPTION_LOOKUP
from aiv.commands import commands_from_args, run_pipeline, cmd_help


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aiv",
        description="AI Valve: Pipes for AI",
        add_help=False,
    )

    # Register all CLI-exposed commands from the registry
    for spec in COMMAND_SPECS:
        if not spec.long_option or not spec.argparse_kwargs:
            continue
        flags = [spec.long_option]
        if spec.short_option:
            flags.insert(0, spec.short_option)
        dest = spec.long_option.lstrip("-").replace("-", "_")
        parser.add_argument(*flags, dest=dest, **spec.argparse_kwargs)

    # --version is not a Command (no pipeline action, just print and exit)
    parser.add_argument("--version", "-v", dest="version", action="store_true")

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
        # left-align the flags+hint column at 36 chars
        col = f"  {flags}{arg_hint}"
        lines.append(f"{col:<38} {spec.help}")
    # --version is outside the registry
    lines.append(f"  {'--version, -v':<36} Display version information")
    print("\n".join(lines), file=sys.stderr)


def main():
    parser = build_parser()
    args = parser.parse_args()

    if getattr(args, "help", False):
        print_cli_help()
        sys.exit(0)

    if getattr(args, "version", False):
        print(f"aiv {get_version()}", file=sys.stderr)
        sys.exit(0)

    # Mutual exclusion: --chat and --code map to the same ctx.mode field;
    # both being set is user error. Checked here rather than in argparse
    # (add_mutually_exclusive_group) so the registry-driven add_argument loop
    # stays simple and unconditional.
    if getattr(args, "chat", False) and getattr(args, "code", False):
        print("aiv: --chat and --code are mutually exclusive", file=sys.stderr)
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
    has_explicit_stdin_context = "-" in context_files
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

    # Determine initial mode from CLI flags; SetModeCommand(s) in the pipeline
    # will override this if --chat or --code were passed, but we also set it here
    # so PipelineContext starts in the right state for any pre-prompt commands.
    initial_mode: InteractionMode | None = None
    if getattr(args, "chat", False):
        initial_mode = InteractionMode.CHAT
    elif getattr(args, "code", False):
        initial_mode = InteractionMode.CODE

    ctx = PipelineContext(
        model=config.get("model", "claude-3-7-sonnet-latest"),
        sys_prompt=config.get("sys_prompt", ""),
        mode=initial_mode,
        api_key=api_key,
        max_tokens=int(max_tokens_raw),
        stdin_data=stdin_data,
        piped_stdin=not stdin_is_tty,
    )

    run_pipeline(commands_from_args(args), ctx)


if __name__ == "__main__":
    main()

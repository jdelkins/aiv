#!/usr/bin/env python3

import argparse
import sys
from pathlib import Path

from aiv.config import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_PROVIDER,
    get_config,
    get_provider_settings,
)
from aiv.models import PipelineContext, InteractionMode
from aiv.specs import COMMAND_SPECS
from aiv.commands import commands_from_args, run_pipeline, apply_session_state


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
        default_provider = config.get("provider", DEFAULT_PROVIDER)
        default_settings = get_provider_settings(default_provider)
    except (OSError, ValueError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    # Explicit stdin context is consumed by its context/extraction command.
    # Otherwise piped input supplies the prompt if none was given, or implicit
    # context for the first prompt command.
    stdin_is_tty = sys.stdin.isatty()
    context_files = getattr(args, "context", []) or []
    extract_files = getattr(args, "extract", []) or []
    has_explicit_stdin_context = any(
        c == "-" or c.startswith("-,") or c == "stdin" or c.startswith("stdin,")
        for c in context_files + extract_files
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

    # Resolve config defaults, then persisted session overrides. Explicit CLI
    # settings are applied afterward by the ordered command pipeline.
    # Type and options are derived from configuration, never session_state.
    try:
        key_file = default_settings.get("api_key_file")
        ctx = PipelineContext(
            model=default_settings.get("model") or "",
            provider=default_provider,
            provider_type=default_settings["type"],
            provider_options=default_settings["options"],
            sys_prompt=config.get("sys_prompt", ""),
            mode_chat_suffix=config.get("mode_chat_suffix", ""),
            mode_code_suffix=config.get("mode_code_suffix", ""),
            mode=initial_mode,
            api_key=default_settings.get("api_key") or "",
            api_key_file=(Path(key_file).expanduser().absolute() if key_file else None),
            max_tokens=int(default_settings.get("max_tokens", DEFAULT_MAX_TOKENS)),
            stdin_data=stdin_data,
            piped_stdin=not stdin_is_tty,
        )
        apply_session_state(ctx)
    except (OSError, ValueError) as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    # Requests validate model and credentials in run_turn(), after CLI profile
    # and key-file overrides have executed. Read-only/context-only operations
    # do not require API credentials.
    run_pipeline(commands_from_args(args), ctx)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3

import sys
import argparse

from aiv.config import get_config, get_provider_settings, DEFAULT_PROVIDER
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
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
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

    # Resolution order, per design discussion:
    #   1. config.toml defaults — provider-scoped (provider, model, max_tokens,
    #      api_key/api_key_file via get_provider_settings) and global
    #      (sys_prompt, mode_chat_suffix, mode_code_suffix)
    #   2. session_state from the conversation file, if present
    #   3. explicit CLI flags (-P/-m/--api-key-file/--max-tokens/-s/
    #      --prompt-suffix), applied afterward via the normal command pipeline —
    #      each of which re-derives and persists session_state itself (see
    #      cmd_set_provider/cmd_set_model/cmd_set_api_key_file/
    #      cmd_set_max_tokens/cmd_set_sys_prompt/cmd_set_prompt_suffix in
    #      commands.py), so no special-casing is needed here beyond
    #      constructing ctx with the pre-CLI-flag baseline.
    #
    # ctx.conv_path must be forced to resolve now (rather than lazily) since
    # apply_session_state() needs it immediately, before any pipeline command
    # has run. This does mean --version/--help/--repl-with-nothing-else now pay
    # the conv_path resolution cost unconditionally; see caveat at bottom.
    default_provider = config.get("provider", DEFAULT_PROVIDER)
    default_settings = get_provider_settings(default_provider)

    ctx = PipelineContext(
        model=default_settings.get("model") or "claude-sonnet-4-6",
        provider=default_provider,
        sys_prompt=config.get("sys_prompt", ""),
        mode_chat_suffix=config.get("mode_chat_suffix", ""),
        mode_code_suffix=config.get("mode_code_suffix", ""),
        mode=initial_mode,
        api_key=default_settings.get("api_key") or "",
        max_tokens=int(default_settings.get("max_tokens") or 4096),
        stdin_data=stdin_data,
        piped_stdin=not stdin_is_tty,
    )

    try:
        apply_session_state(ctx)  # layers session_state over the config defaults above
    except FileNotFoundError as e:
        print(e, file=sys.stderr)
        sys.exit(1)

    if not ctx.api_key:
        print("aiv: api_key not set", file=sys.stderr)
        sys.exit(1)

    run_pipeline(commands_from_args(args), ctx)


if __name__ == "__main__":
    main()

# Caveat: ctx.conv_path is resolved eagerly (apply_session_state reads it
# immediately after construction) rather than lazily on first pipeline command,
# unchanged from the prior pass — a bare `aiv --version` or `aiv -i` with no
# other flags will always do a git-root lookup + read the conversation file up
# front. Flagged previously; still true, not addressed here.
#
# Caveat: mode_chat_suffix/mode_code_suffix are now passed explicitly into
# PipelineContext from config.get(...) rather than being read lazily inside the
# mode_suffix property (that property no longer calls get_config() at all, per
# the models.py pass). The "" fallback here is intentionally unreachable in
# practice — get_config() always sets both keys via _normalise_suffix()/
# setdefault() before returning, so config.get(..., "") only matters if
# get_config() itself is somehow bypassed or mocked without those keys, which
# existing tests should be checked against (patch_get_config's _MOCK_CONFIG in
# test_commands.py already includes both keys, so should be unaffected).
#
# Caveat: api_key emptiness check remains positioned AFTER apply_session_state,
# unchanged from before — a session_state api_key_file override can supply the
# key even when config has none configured at all for the default provider.

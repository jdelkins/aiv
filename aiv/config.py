from pathlib import Path
from importlib.metadata import version as pkg_version, PackageNotFoundError
from functools import lru_cache
import tomllib

CONFIG_DIR = Path.home() / ".config" / "aiv"
CONFIG_FILE = CONFIG_DIR / "config.toml"
FALLBACK_CONVERSATION_FILE = CONFIG_DIR / "conversation.json"

DEFAULT_SYS_PROMPT = (
    "You are an expert programmer, shell master, and support engineer who values "
    "code efficiency and clarity above all else. "
    "CONVERSATIONAL responses may use markdown, including triple backticks, where it aids readability. "
    'When told to provide "CODE ONLY", the output is piped directly into a CLI program: '
    "preserve the input's formatting, skip explanations an expert would already know, "
    "emit plain code with no markdown or triple-backtick fences, and place any important "
    "caveats, assumptions, requests for context, or usage nuances in code comments instead."
)
DEFAULT_MODE_CHAT_SUFFIX = "This is a CONVERSATIONAL message. Respond using markdown formatting including triple backticks where it aids readability."
DEFAULT_MODE_CODE_SUFFIX = (
    "Respond with raw CODE ONLY. No markdown, no triple backtick code fences. Preserve input formatting and, especially, line-leading whitespace. "
    "If you have important caveats, assumptions, clarification requests, or usage nuances, include them as code comments."
)
DEFAULT_PROMPT_MARKER = "## prompt:"
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MAX_TOKENS = 4096
VALID_PROVIDERS = ("anthropic", "openai", "openai-reasoning")


def _normalise_suffix(value: str) -> str:
    if not value.startswith("\n\n"):
        value = "\n\n" + value.lstrip("\n")
    return value


def get_version() -> str:
    try:
        return pkg_version("aiv")
    except PackageNotFoundError:
        return "unknown"


def _resolve_api_key_file(conf: dict, label: str) -> None:
    """
    Resolve conf["api_key"] from either an inline api_key or api_key_file,
    mutating conf in place. api_key_file is retained (normalised to an expanded
    absolute Path str), not popped, so get_provider_settings() can expose it for
    session_state diffing. label is used only in error messages for context.
    """
    if "api_key" in conf:
        # inline key takes precedence; drop api_key_file to avoid ambiguity
        conf.pop("api_key_file", None)
        return
    if "api_key_file" in conf:
        key_file = Path(conf["api_key_file"]).expanduser()
        if not key_file.exists():
            raise FileNotFoundError(
                f"aiv: api_key_file not found for {label}: {key_file}"
            )
        conf["api_key_file"] = str(key_file)
        conf["api_key"] = key_file.read_text().strip()


@lru_cache(maxsize=None)
def get_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"aiv: config file not found: {CONFIG_FILE}")
    with open(CONFIG_FILE, "rb") as f:
        config = tomllib.load(f)

    _resolve_api_key_file(config, label="top-level")

    if "system_prompt" in config and "sys_prompt" not in config:
        config["sys_prompt"] = config.pop("system_prompt")
    config.setdefault("sys_prompt", DEFAULT_SYS_PROMPT)
    config["mode_chat_suffix"] = _normalise_suffix(
        config.get("mode_chat_suffix", DEFAULT_MODE_CHAT_SUFFIX)
    )
    config["mode_code_suffix"] = _normalise_suffix(
        config.get("mode_code_suffix", DEFAULT_MODE_CODE_SUFFIX)
    )
    config.setdefault("prompt_marker", DEFAULT_PROMPT_MARKER)
    config.setdefault("provider", DEFAULT_PROVIDER)
    config.setdefault("max_tokens", DEFAULT_MAX_TOKENS)
    if config["provider"] not in VALID_PROVIDERS:
        raise ValueError(
            f"aiv: invalid provider {config['provider']!r} in {CONFIG_FILE}; "
            f"must be one of {VALID_PROVIDERS}"
        )

    providers_table = config.get("providers", {})
    if not isinstance(providers_table, dict):
        raise ValueError(f"aiv: 'providers' must be a table in {CONFIG_FILE}")
    for name, conf in providers_table.items():
        if name not in VALID_PROVIDERS:
            raise ValueError(
                f"aiv: unknown provider {name!r} in [providers] table of "
                f"{CONFIG_FILE}; must be one of {VALID_PROVIDERS}"
            )
        if not isinstance(conf, dict):
            raise ValueError(f"aiv: providers.{name} must be a table in {CONFIG_FILE}")
        _resolve_api_key_file(conf, label=f"providers.{name}")
    config["providers"] = providers_table

    return config


def get_provider_settings(provider: str) -> dict:
    """
    Resolve {"api_key": ..., "api_key_file": ..., "model": ..., "max_tokens": ...}
    for the given provider name. Prefers a [providers.<name>] table entry; falls
    back to legacy top-level api_key/api_key_file/model/max_tokens fields so
    pre-existing single-provider configs keep working unchanged. Any value may
    be None (api_key/api_key_file/model) if nothing is configured for it;
    max_tokens falls back to DEFAULT_MAX_TOKENS rather than None, since every
    caller needs a concrete int for the API call.

    api_key_file is the resolved, expanded absolute path as a string (not the
    raw config value) — callers diffing against session_state overrides should
    normalise their own comparison value the same way (Path(...).expanduser()).
    """
    config = get_config()
    entry = config.get("providers", {}).get(provider)
    if entry is not None:
        return {
            "api_key": entry.get("api_key"),
            "api_key_file": entry.get("api_key_file"),
            "model": entry.get("model"),
            "max_tokens": entry.get("max_tokens", config.get("max_tokens", DEFAULT_MAX_TOKENS)),
        }
    return {
        "api_key": config.get("api_key"),
        "api_key_file": config.get("api_key_file"),
        "model": config.get("model"),
        "max_tokens": config.get("max_tokens", DEFAULT_MAX_TOKENS),
    }

# Caveat: get_config() is @lru_cache'd, so the dict it returns is the SAME object
# across calls within a process — get_provider_settings() reads from it but never
# mutates it, consistent with that caching contract. If you later need per-call
# overrides, don't mutate this dict in place; copy first.
#
# Caveat: _resolve_api_key_file deliberately keeps api_key_file in conf (unlike
# the old top-level-only logic, which popped it). This is required for
# get_provider_settings() to expose the configured default path for diffing
# against an explicit !api-key-file session_state override, per earlier design
# discussion.
#
# Caveat: max_tokens in get_provider_settings() falls back through THREE levels
# (per-provider entry -> flat top-level config -> DEFAULT_MAX_TOKENS) rather than
# the two levels used by api_key/api_key_file/model. This is intentional: unlike
# those three fields, max_tokens always needs a concrete usable int for the API
# call, so there's no "None means nothing configured, caller decides" case to
# preserve here. sys_prompt/mode_chat_suffix/mode_code_suffix remain pure
# top-level config fields (no provider-table involvement) per the design
# discussion — this file's existing top-level handling of those three is already
# sufficient and is NOT changed here.

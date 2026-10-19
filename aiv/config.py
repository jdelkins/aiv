from copy import deepcopy
from functools import lru_cache
from importlib.metadata import version as pkg_version, PackageNotFoundError
from pathlib import Path
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
    "emit plain code, and place any important caveats, assumptions, requests for context, "
    "or usage nuances in code comments instead."
)
DEFAULT_MODE_CHAT_SUFFIX = "This is a CONVERSATIONAL message. Respond using markdown formatting including wrapping code in triple backticks where it aids readability."
DEFAULT_MODE_CODE_SUFFIX = (
    "Respond with raw CODE ONLY for piping into a code editor or text processing pipeline. "
    "Don't contextualize code responses in markdown. "
    "(Markdown responses are fine if the language being requested is itself markdown.) "
    "Preserve input formatting and, especially, line-leading whitespace. "
    "If you have important caveats, assumptions, clarification requests, or usage nuances, include them as code comments."
)
DEFAULT_PROMPT_MARKER = "## prompt:"
DEFAULT_PROVIDER = "anthropic"
DEFAULT_MAX_TOKENS = 4096
VALID_PROVIDER_TYPES = ("anthropic", "openai", "openai-reasoning")


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
    """Resolve credentials in place, retaining the expanded key-file path."""
    if "api_key" in conf:
        # Preserve legacy precedence when both credential fields are present.
        conf.pop("api_key_file", None)
        return

    if "api_key_file" in conf:
        key_file = Path(conf["api_key_file"]).expanduser().absolute()
        if not key_file.exists():
            raise FileNotFoundError(
                f"aiv: api_key_file not found for {label}: {key_file}"
            )
        conf["api_key_file"] = str(key_file)
        conf["api_key"] = key_file.read_text().strip()


def _validate_provider_name(provider: str, providers: dict) -> None:
    if not isinstance(provider, str) or not provider:
        raise ValueError("aiv: provider must be a non-empty string")

    if provider not in providers and provider not in VALID_PROVIDER_TYPES:
        available = ", ".join(sorted(set(providers) | set(VALID_PROVIDER_TYPES)))
        raise ValueError(
            f"aiv: unknown provider {provider!r}; " f"available providers: {available}"
        )


@lru_cache(maxsize=None)
def get_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"aiv: config file not found: {CONFIG_FILE}")

    with CONFIG_FILE.open("rb") as f:
        config = tomllib.load(f)

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

    providers = config.get("providers", {})
    if not isinstance(providers, dict):
        raise ValueError(f"aiv: 'providers' must be a table in {CONFIG_FILE}")

    for name, entry in providers.items():
        if not name:
            raise ValueError("aiv: provider names must be non-empty strings")
        if not isinstance(entry, dict):
            raise ValueError(f"aiv: providers.{name} must be a table in {CONFIG_FILE}")

        provider_type = entry.get("type")
        if provider_type is None:
            if name not in VALID_PROVIDER_TYPES:
                raise ValueError(f"aiv: provider {name!r} requires a type")
            provider_type = name

        if provider_type not in VALID_PROVIDER_TYPES:
            raise ValueError(
                f"aiv: invalid type {provider_type!r} for provider {name!r}; "
                f"must be one of {VALID_PROVIDER_TYPES}"
            )
        entry["type"] = provider_type

        options = entry.setdefault("options", {})
        if not isinstance(options, dict):
            raise ValueError(f"aiv: options for provider {name!r} must be a table")

    config["providers"] = providers
    _validate_provider_name(config["provider"], providers)

    # Preserve eager credential resolution for existing callers.
    _resolve_api_key_file(config, label="top-level")
    for name, entry in providers.items():
        _resolve_api_key_file(entry, label=f"providers.{name}")

    return config


def get_provider_settings(provider: str) -> dict:
    """Resolve a named profile without mutating the cached configuration.

    Built-in names remain selectable without a table for legacy compatibility.
    Custom names must have a configured entry with an explicit implementation
    type. Model and token budget fall back independently to top-level settings;
    credentials fall back as a pair. Options never inherit from the top level.
    """
    config = get_config()
    providers = config["providers"]
    _validate_provider_name(provider, providers)
    entry = providers.get(provider, {})

    credentials = entry if "api_key" in entry or "api_key_file" in entry else config

    return {
        "type": entry.get("type", provider),
        "api_key": credentials.get("api_key"),
        "api_key_file": credentials.get("api_key_file"),
        "model": entry.get("model", config.get("model")),
        "max_tokens": entry.get("max_tokens", config["max_tokens"]),
        # Callers must not be able to mutate cached options, including nested ones.
        "options": deepcopy(entry.get("options", {})),
    }

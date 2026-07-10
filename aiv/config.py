from pathlib import Path
from importlib.metadata import version as pkg_version, PackageNotFoundError
from functools import lru_cache
import tomllib

CONFIG_DIR = Path.home() / ".config" / "aiv"
CONFIG_FILE = CONFIG_DIR / "config.toml"
FALLBACK_CONVERSATION_FILE = CONFIG_DIR / "conversation.json"

DEFAULT_SYS_PROMPT = (
    "You are an expert programmer and a shell master and an expert support engineer. "
    "You value code efficiency and clarity above all things. "
    "In conversational responses, you may use markdown formatting including triple backticks where it aids readability. "
    'If I tell you to provide "CODE ONLY", the output will be piped out to a CLI program, '
    "so preserve the formatting of the prompt or context, "
    "do not explain anything an expert programmer would be able to figure out (and only in code comments, if at all), "
    "and provide only plain code responses without wrapping them in markdown (do not use triple backtick code fences); "
    "however, in this case, if you have important information, requests for additional context, assumptions, caveats, or usage nuances, "
    "feel free to include that information in a code comment."
)
DEFAULT_MODE_CHAT_SUFFIX = "This is a conversational message. Respond using markdown formatting including triple backticks where it aids readability."
DEFAULT_MODE_CODE_SUFFIX = (
    "Respond with raw CODE ONLY. No markdown, no triple backtick code fences. Preserve input formatting. "
    "If you have important caveats, assumptions, clarification requests, or usage nuances, include them as code comments."
)


def _normalise_suffix(value: str) -> str:
    if not value.startswith("\n\n"):
        value = "\n\n" + value.lstrip("\n")
    return value


def get_version() -> str:
    try:
        return pkg_version("aiv")
    except PackageNotFoundError:
        return "unknown"


@lru_cache(maxsize=None)
def get_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"aiv: config file not found: {CONFIG_FILE}")
    # tomllib requires binary mode; available stdlib Python 3.11+
    with open(CONFIG_FILE, "rb") as f:
        config = tomllib.load(f)
    # resolve api_key from api_key_file if api_key is not directly provided
    if "api_key" not in config and "api_key_file" in config:
        key_file = Path(config.pop("api_key_file")).expanduser()
        if not key_file.exists():
            raise FileNotFoundError(f"aiv: api_key_file not found: {key_file}")
        config["api_key"] = key_file.read_text().strip()
    elif "api_key_file" in config:
        config.pop("api_key_file")
    # normalise sys_prompt alias
    if "system_prompt" in config and "sys_prompt" not in config:
        config["sys_prompt"] = config.pop("system_prompt")
    config.setdefault("sys_prompt", DEFAULT_SYS_PROMPT)
    # apply defaults and normalise mode suffixes (ensure \n\n prefix)
    config["mode_chat_suffix"] = _normalise_suffix(
        config.get("mode_chat_suffix", DEFAULT_MODE_CHAT_SUFFIX)
    )
    config["mode_code_suffix"] = _normalise_suffix(
        config.get("mode_code_suffix", DEFAULT_MODE_CODE_SUFFIX)
    )
    return config

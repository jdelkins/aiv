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
    "What you write will be piped in and out of CLI programs, so do not explain anything unless explicitly asked to. "
    "In conversational responses, you may use markdown formatting including triple backticks where it aids readability. "
    "When providing direct output intended for piping, avoid triple backticks and provide only the raw result. "
    "Preserve input formatting. "
    'If I say "code only" or similar, please provide only code responses, without wrapping them in markdown; '
    "however, in this case, if you have important information, caveats, or usage nuances, feel free to include that information in a code comment."
)
DEFAULT_MODE_CHAT_SUFFIX = "Respond using markdown formatting including triple backticks where it aids readability."
DEFAULT_MODE_CODE_SUFFIX = (
    "Respond with raw code only. No markdown, no triple backtick fences. "
    "Preserve all leading whitespace exactly as it appears — do not strip indentation from any line, including the first. "
    "If you have important caveats or usage nuances, include them as code comments."
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

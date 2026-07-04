from pathlib import Path
from importlib.metadata import version as pkg_version, PackageNotFoundError

CONFIG_DIR = Path.home() / ".config" / "aiv"
CONFIG_FILE = CONFIG_DIR / "config"
FALLBACK_CONVERSATION_FILE = CONFIG_DIR / "conversation.json"
MODE_CHAT_SUFFIX = "\n\nRespond using markdown formatting including triple backticks where it aids readability."
MODE_CODE_SUFFIX = (
    "\n\nRespond with raw code only. No markdown, no triple backtick fences. "
    "If you have important caveats or usage nuances, include them as code comments."
)


def get_version() -> str:
    try:
        return pkg_version("aiv")
    except PackageNotFoundError:
        return "unknown"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"aiv: config file not found: {CONFIG_FILE}")
    config = {}
    with open(CONFIG_FILE) as f:
        for line in f:
            line = line.split("#")[0].strip()
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip().lower()
            value = value.strip().strip('"')
            if key == "api_key":
                config["api_key"] = value
            elif key == "model":
                config["model"] = value
            elif key == "max_tokens":
                config["max_tokens"] = value
            elif key in ("sys_prompt", "system_prompt"):
                config["sys_prompt"] = value
    return config

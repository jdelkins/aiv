from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document

from aiv.config import VALID_PROVIDER_TYPES, get_config
from aiv.models import InteractionMode
from aiv.specs import COMMAND_SPECS

_ALL_NAMES: list[str] = [name for spec in COMMAND_SPECS for name in spec.names]

_PATH_PREFIXES: list[str] = [
    name + " " for spec in COMMAND_SPECS if spec.takes_path for name in spec.names
]

_DIR_PREFIXES: list[str] = [
    name + " " for spec in COMMAND_SPECS if spec.takes_dir for name in spec.names
]

_RANGE_PREFIXES: list[str] = [
    name + " "
    for spec in COMMAND_SPECS
    if any(token in spec.usage for token in ("<range>", "[range]"))
    for name in spec.names
]

_PROVIDER_PREFIXES: list[str] = [
    name + " "
    for spec in COMMAND_SPECS
    if spec.long_option == "--provider"
    for name in spec.names
]

_MODE_VALUES: list[str] = list(dict.fromkeys(m.value for m in InteractionMode))


def _provider_names() -> list[str]:
    # Resolve lazily so importing completion never requires configuration or
    # credentials. get_config() retains its existing process-local cache.
    names = set(VALID_PROVIDER_TYPES)
    try:
        names.update(get_config().get("providers", {}))
    except (OSError, ValueError):
        # Completion must not crash the prompt if configuration cannot be read.
        # Selecting a profile still uses normal runtime validation.
        pass
    return sorted(names)


class AivCompleter(Completer):
    def __init__(self):
        self._path_completer = PathCompleter(expanduser=True)
        self._dir_completer = PathCompleter(only_directories=True, expanduser=True)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Subsequent lines of a multiline prompt are free-form text.
        if "\n" in text:
            return

        for prefix in _PATH_PREFIXES:
            if text.startswith(prefix):
                remainder = text[len(prefix) :]
                if (
                    remainder == "-"
                    or remainder.startswith("-,")
                    or remainder == "stdin"
                    or remainder.startswith("stdin,")
                ):
                    return
                sub_doc = Document(remainder, cursor_position=len(remainder))
                yield from self._path_completer.get_completions(sub_doc, complete_event)
                return

        for prefix in _DIR_PREFIXES:
            if text.startswith(prefix):
                remainder = text[len(prefix) :]
                sub_doc = Document(remainder, cursor_position=len(remainder))
                yield from self._dir_completer.get_completions(sub_doc, complete_event)
                return

        for prefix in _PROVIDER_PREFIXES:
            if text.startswith(prefix):
                remainder = text[len(prefix) :]
                for name in _provider_names():
                    if name.startswith(remainder):
                        yield Completion(name, start_position=-len(remainder))
                return

        for prefix in _RANGE_PREFIXES:
            if text.startswith(prefix):
                return

        if text.startswith("!mode "):
            remainder = text[len("!mode ") :]
            for value in _MODE_VALUES:
                if value.startswith(remainder):
                    yield Completion(value, start_position=-len(remainder))
            return

        # Only complete command names while typing the first token.
        if text.startswith("!") and " " not in text:
            for name in _ALL_NAMES:
                if name.startswith(text):
                    yield Completion(name, start_position=-len(text))
            return

        # Bare text is a free-form prompt and receives no completions.

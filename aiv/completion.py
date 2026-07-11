from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document

from aiv.specs import COMMAND_SPECS, COMMAND_LOOKUP

# All REPL-dispatchable command name strings, e.g. ["!history", "!show", ...]
_ALL_NAMES: list[str] = [name for spec in COMMAND_SPECS for name in spec.names]

# Prefixes that should trigger path completion, e.g. "!context "
_PATH_PREFIXES: list[str] = [
    name + " " for spec in COMMAND_SPECS if spec.takes_path for name in spec.names
]

# Prefixes that should trigger dir completion, e.g. "!cd "
_DIR_PREFIXES: list[str] = [
    name + " " for spec in COMMAND_SPECS if spec.takes_dir for name in spec.names
]

# Commands that accept an optional range argument — once past command+space,
# yield nothing rather than polluting with unrelated name completions.
_RANGE_PREFIXES: list[str] = [
    name + " "
    for spec in COMMAND_SPECS
    if any(token in spec.usage for token in ("<range>", "[range]"))
    for name in spec.names
]

# Mode values are derived from InteractionMode rather than hardcoded so that
# adding a new mode in the future automatically appears in completion.
from aiv.models import InteractionMode

_MODE_VALUES: list[str] = [m.value for m in InteractionMode] + ["default"]


class AivCompleter(Completer):
    def __init__(self):
        self._path_completer = PathCompleter(expanduser=True)
        self._dir_completer = PathCompleter(only_directories=True, expanduser=True)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Only attempt completion on the first line of a multiline prompt;
        # subsequent lines are free-form prompt text, not commands.
        if "\n" in text:
            return

        # Path completion for commands that take a filesystem argument
        for prefix in _PATH_PREFIXES:
            if text.startswith(prefix):
                remainder = text[len(prefix) :]
                # Skip path completion for stdin sentinels:
                #   "stdin"        — bare stdin, no metadata
                #   "stdin,..."    — stdin with file=/range= metadata
                #   "-"            — legacy bare stdin sentinel
                #   "-,"           — would be argparse-hostile but guard anyway
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

        # Path completion for commands that take a filesystem argument
        for prefix in _DIR_PREFIXES:
            if text.startswith(prefix):
                remainder = text[len(prefix) :]
                sub_doc = Document(remainder, cursor_position=len(remainder))
                yield from self._dir_completer.get_completions(sub_doc, complete_event)
                return

        # Range-taking commands: no useful completions beyond the command name
        for prefix in _RANGE_PREFIXES:
            if text.startswith(prefix):
                return

        # Mode argument completion for !mode — derived from InteractionMode enum
        if text.startswith("!mode "):
            remainder = text[len("!mode ") :]
            for value in _MODE_VALUES:
                if value.startswith(remainder):
                    yield Completion(value, start_position=-len(remainder))
            return

        # Command name completion: only while still typing the first token
        if text.startswith("!") and " " not in text:
            for name in _ALL_NAMES:
                if name.startswith(text):
                    yield Completion(name, start_position=-len(text))
            return

        # Bare text (no "!"): no completions — it's a free-form prompt

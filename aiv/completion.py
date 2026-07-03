from __future__ import annotations

from prompt_toolkit.completion import Completer, Completion, PathCompleter
from prompt_toolkit.document import Document

from aiv.specs import COMMAND_SPECS, COMMAND_LOOKUP

# All REPL-dispatchable command name strings, e.g. ["!history", "!show", ...]
_ALL_NAMES: list[str] = [name for spec in COMMAND_SPECS for name in spec.names]

# Prefixes that should trigger path completion, e.g. "!context "
# Built from specs with takes_path=True so it stays in sync automatically.
_PATH_PREFIXES: list[str] = [
    name + " "
    for spec in COMMAND_SPECS
    if spec.takes_path
    for name in spec.names
]

# Commands that accept an optional range argument — offer digit completion hint.
# Not full completion (ranges are dynamic) but we can at least not offer names.
_RANGE_PREFIXES: list[str] = [
    name + " "
    for spec in COMMAND_SPECS
    if any(token in spec.usage for token in ("<range>", "[range]"))
    for name in spec.names
]


class AivCompleter(Completer):
    def __init__(self):
        self._path_completer = PathCompleter(expanduser=True)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor

        # Only attempt completion on the first line of a multiline prompt;
        # subsequent lines are free-form prompt text, not commands.
        if "\n" in text:
            return

        # Path completion for commands that take a filesystem argument (e.g. !context)
        for prefix in _PATH_PREFIXES:
            if text.startswith(prefix):
                remainder = text[len(prefix):]
                sub_doc = Document(remainder, cursor_position=len(remainder))
                # PathCompleter yields Completions with negative start_positions
                # relative to the sub-document; they transfer correctly as-is.
                yield from self._path_completer.get_completions(sub_doc, complete_event)
                return

        # Range-taking commands: no useful completions to offer beyond the command
        # name itself, so once we're past the command+space, yield nothing rather
        # than polluting with unrelated name completions.
        for prefix in _RANGE_PREFIXES:
            if text.startswith(prefix):
                return

        # Mode argument completion for !mode
        if text.startswith("!mode "):
            remainder = text[len("!mode "):]
            for value in ("chat", "code", "default"):
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

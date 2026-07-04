from __future__ import annotations

import json
import pytest
from pathlib import Path
from typing import cast, Any
from anthropic.types import MessageParam

from aiv.conversation import (
    parse_range,
    build_interactions,
    flatten_interactions,
    strip_context_blocks,
    count_context_blocks,
    first_line,
    format_bytes,
    validate_conversation,
    load_conversation,
    save_conversation,
)


# ---------------------------------------------------------------------------
# parse_range
# ---------------------------------------------------------------------------


class TestParseRange:
    def test_single(self):
        assert parse_range("3", 5) == (3, 3)

    def test_range(self):
        assert parse_range("2-4", 5) == (2, 4)

    def test_open_ended(self):
        assert parse_range("3-", 5) == (3, 5)

    def test_clamps_end(self):
        assert parse_range("2-99", 5) == (2, 5)

    def test_start_equals_max(self):
        assert parse_range("5", 5) == (5, 5)

    def test_start_zero(self):
        assert parse_range("0", 5) is None

    def test_start_exceeds_max(self):
        assert parse_range("6", 5) is None

    def test_end_before_start(self):
        assert parse_range("4-2", 5) is None

    def test_non_numeric(self):
        assert parse_range("abc", 5) is None

    def test_bad_range_start(self):
        assert parse_range("a-3", 5) is None

    def test_bad_range_end(self):
        assert parse_range("1-b", 5) is None

    def test_whitespace_stripped(self):
        assert parse_range("  2-4  ", 5) == (2, 4)


# ---------------------------------------------------------------------------
# build_interactions / flatten_interactions
# ---------------------------------------------------------------------------


class TestBuildInteractions:
    def test_empty(self):
        assert build_interactions([]) == []

    def test_single_user_turn(self):
        msgs: list[MessageParam] = [{"role": "user", "content": "hi"}]
        assert build_interactions(msgs) == [[{"role": "user", "content": "hi"}]]

    def test_user_assistant_pair(self):
        msgs: list[MessageParam] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        result = build_interactions(msgs)
        assert len(result) == 1
        assert result[0] == msgs

    def test_multiple_interactions(self):
        msgs: list[MessageParam] = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        result = build_interactions(msgs)
        assert len(result) == 2
        assert result[0] == msgs[:2]
        assert result[1] == msgs[2:]

    def test_orphaned_assistant_turn(self):
        # Assistant message with no preceding user turn is grouped alone
        msgs: list[MessageParam] = [{"role": "assistant", "content": "stray"}]
        result = build_interactions(msgs)
        assert len(result) == 1
        assert result[0] == msgs

    def test_consecutive_user_turns(self):
        msgs: list[MessageParam] = [
            {"role": "user", "content": "q1"},
            {"role": "user", "content": "q2"},
        ]
        result = build_interactions(msgs)
        assert len(result) == 2


class TestFlattenInteractions:
    def test_round_trips(self):
        msgs: list[MessageParam] = [
            {"role": "user", "content": "q1"},
            {"role": "assistant", "content": "a1"},
            {"role": "user", "content": "q2"},
            {"role": "assistant", "content": "a2"},
        ]
        interactions = build_interactions(msgs)
        assert flatten_interactions(interactions) == msgs

    def test_empty(self):
        assert flatten_interactions([]) == []


# ---------------------------------------------------------------------------
# strip_context_blocks
# ---------------------------------------------------------------------------


class TestStripContextBlocks:
    def test_no_blocks(self):
        text = "hello\nworld"
        assert strip_context_blocks(text) == "hello\nworld"

    def test_single_file_block(self):
        text = "---CONTEXT_FILE:[foo.py]---\nsome code\n---END---\nafter"
        assert strip_context_blocks(text) == "after"

    def test_single_txt_block(self):
        text = "---CONTEXT_TXT:[foo.py:1:5]---\nsome text\n---END---\nafter"
        assert strip_context_blocks(text) == "after"

    def test_multiple_blocks(self):
        text = (
            "---CONTEXT_FILE:[a.py]---\ncode a\n---END---\n"
            "---CONTEXT_FILE:[b.py]---\ncode b\n---END---\n"
            "prompt text"
        )
        assert strip_context_blocks(text) == "prompt text"

    def test_text_before_block(self):
        text = "before\n---CONTEXT_FILE:[x.py]---\nstuff\n---END---"
        assert strip_context_blocks(text) == "before"

    def test_empty_string(self):
        assert strip_context_blocks("") == ""


# ---------------------------------------------------------------------------
# count_context_blocks
# ---------------------------------------------------------------------------


class TestCountContextBlocks:
    def test_zero(self):
        assert count_context_blocks("no blocks here") == 0

    def test_one_file(self):
        text = "---CONTEXT_FILE:[foo.py]---\ncode\n---END---"
        assert count_context_blocks(text) == 1

    def test_one_txt(self):
        text = "---CONTEXT_TXT:---\ndata\n---END---"
        assert count_context_blocks(text) == 1

    def test_mixed(self):
        text = (
            "---CONTEXT_FILE:[a.py]---\ncode\n---END---\n"
            "---CONTEXT_TXT:---\ndata\n---END---"
        )
        assert count_context_blocks(text) == 2


# ---------------------------------------------------------------------------
# first_line
# ---------------------------------------------------------------------------


class TestFirstLine:
    def test_plain_text(self):
        assert first_line("hello\nworld") == "hello"

    def test_skips_blank_lines(self):
        assert first_line("\n\nhello") == "hello"

    def test_skips_context_blocks(self):
        text = "---CONTEXT_FILE:[foo.py]---\ncode\n---END---\nactual prompt"
        assert first_line(text) == "actual prompt"

    def test_truncates_at_80(self):
        long = "x" * 100
        assert first_line(long) == "x" * 80

    def test_empty(self):
        assert first_line("") == ""

    def test_only_context_blocks(self):
        text = "---CONTEXT_FILE:[foo.py]---\ncode\n---END---"
        assert first_line(text) == ""


# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------


class TestFormatBytes:
    def test_bytes(self):
        assert format_bytes(512) == "512B"

    def test_exact_kb_boundary(self):
        assert format_bytes(1024) == "1.0KB"

    def test_kb(self):
        assert format_bytes(2048) == "2.0KB"

    def test_mb(self):
        assert format_bytes(1024 * 1024) == "1.0MB"

    def test_zero(self):
        assert format_bytes(0) == "0B"


# ---------------------------------------------------------------------------
# validate_conversation
# ---------------------------------------------------------------------------


class TestValidateConversation:
    def test_valid_empty(self, tmp_path):
        # Empty list is always valid
        validate_conversation([], tmp_path / "conv.json")

    def test_valid_pair(self, tmp_path):
        msgs: list[MessageParam] = [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
        validate_conversation(msgs, tmp_path / "conv.json")

    def test_non_dict_message_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            validate_conversation(cast(Any, ["not a dict"]), tmp_path / "conv.json")

    def test_missing_role_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            validate_conversation(
                cast(Any, [{"content": "hi"}]), tmp_path / "conv.json"
            )

    def test_missing_content_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            validate_conversation(cast(Any, [{"role": "user"}]), tmp_path / "conv.json")

    def test_invalid_role_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            validate_conversation(
                [{"role": "system", "content": "hi"}], tmp_path / "conv.json"
            )

    def test_invalid_content_type_exits(self, tmp_path):
        with pytest.raises(SystemExit):
            validate_conversation(
                cast(Any, [{"role": "user", "content": 42}]), tmp_path / "conv.json"
            )

    def test_first_message_not_user_warns(self, tmp_path, capsys):
        msgs: list[MessageParam] = [{"role": "assistant", "content": "hi"}]
        validate_conversation(msgs, tmp_path / "conv.json")
        assert "warning" in capsys.readouterr().err.lower()

    def test_consecutive_assistant_warns(self, tmp_path, capsys):
        msgs: list[MessageParam] = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a1"},
            {"role": "assistant", "content": "a2"},
        ]
        validate_conversation(msgs, tmp_path / "conv.json")
        assert "warning" in capsys.readouterr().err.lower()

    def test_consecutive_user_does_not_warn(self, tmp_path, capsys):
        msgs: list[MessageParam] = [
            {"role": "user", "content": "q1"},
            {"role": "user", "content": "q2"},
        ]
        validate_conversation(msgs, tmp_path / "conv.json")
        assert "warning" not in capsys.readouterr().err.lower()

    def test_content_as_list_is_valid(self, tmp_path):
        # Anthropic supports list content blocks (e.g. tool use)
        msgs: list[MessageParam] = [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]}
        ]
        validate_conversation(msgs, tmp_path / "conv.json")


# ---------------------------------------------------------------------------
# load_conversation (structural / error path tests)
# ---------------------------------------------------------------------------


class TestLoadConversation:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_conversation(tmp_path / "nope.json") == []

    def test_valid_file(self, tmp_path):
        p = tmp_path / "conv.json"
        msgs: list[MessageParam] = [{"role": "user", "content": "hi"}]
        save_conversation(msgs, p)
        assert load_conversation(p) == msgs

    def test_invalid_json_exits(self, tmp_path):
        p = tmp_path / "conv.json"
        p.write_text("not json{{{")
        with pytest.raises(SystemExit):
            load_conversation(p)

    def test_non_object_json_exits(self, tmp_path):
        p = tmp_path / "conv.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(SystemExit):
            load_conversation(p)

    def test_missing_messages_key_warns(self, tmp_path, capsys):
        p = tmp_path / "conv.json"
        p.write_text("{}")
        result = load_conversation(p)
        assert result == []
        assert "warning" in capsys.readouterr().err.lower()

    def test_messages_not_list_exits(self, tmp_path):
        p = tmp_path / "conv.json"
        p.write_text(json.dumps({"messages": "oops"}))
        with pytest.raises(SystemExit):
            load_conversation(p)

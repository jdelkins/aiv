from __future__ import annotations
from aiv.models import InteractionMode, ConversationError

import json
import pytest
from typing import cast, Any

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
    reset_conversation,
    load_session_state,
    save_session_state,
    StoredMessage,
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
        msgs: list[StoredMessage] = [
            {"mode": InteractionMode.CHAT, "message": {"role": "user", "content": "hi"}}
        ]
        assert build_interactions(msgs) == [
            [
                {
                    "mode": InteractionMode.CHAT,
                    "message": {"role": "user", "content": "hi"},
                }
            ]
        ]

    def test_user_assistant_pair(self):
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "hi"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "hello"},
            },
        ]
        result = build_interactions(msgs)
        assert len(result) == 1
        assert result[0] == msgs

    def test_multiple_interactions(self):
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "q1"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "a1"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "q2"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "a2"},
            },
        ]
        result = build_interactions(msgs)
        assert len(result) == 2
        assert result[0] == msgs[:2]
        assert result[1] == msgs[2:]

    def test_orphaned_assistant_turn(self):
        # Assistant message with no preceding user turn is grouped alone
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "stray"},
            }
        ]
        result = build_interactions(msgs)
        assert len(result) == 1
        assert result[0] == msgs

    def test_consecutive_user_turns(self):
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "q1"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "q2"},
            },
        ]
        result = build_interactions(msgs)
        assert len(result) == 2


class TestFlattenInteractions:
    def test_round_trips(self):
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "q1"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "a1"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "q2"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "a2"},
            },
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
        assert first_line(text) == "---CONTEXT_FILE:[foo.py]---"


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
    def test_valid_empty(self):
        assert validate_conversation([]) == []

    def test_valid_pair(self):
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "hi"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "hello"},
            },
        ]
        assert validate_conversation(msgs) == []

    def test_non_dict_message_raises(self):
        with pytest.raises(ConversationError, match="not an object"):
            validate_conversation(cast(Any, ["not a dict"]))

    def test_missing_mode_raises(self):
        with pytest.raises(ConversationError, match="missing 'mode'"):
            validate_conversation(
                cast(Any, [{"message": {"role": "user", "content": "hi"}}])
            )

    def test_invalid_mode_raises(self):
        with pytest.raises(ConversationError, match="invalid mode"):
            validate_conversation(
                cast(
                    Any,
                    [{"mode": "bogus", "message": {"role": "user", "content": "hi"}}],
                )
            )

    def test_missing_message_raises(self):
        with pytest.raises(ConversationError, match="missing 'message'"):
            validate_conversation(cast(Any, [{"mode": InteractionMode.CHAT}]))

    def test_missing_role_raises(self):
        with pytest.raises(ConversationError, match="missing 'role'"):
            validate_conversation(
                cast(
                    Any, [{"mode": InteractionMode.CHAT, "message": {"content": "hi"}}]
                )
            )

    def test_missing_content_raises(self):
        with pytest.raises(ConversationError, match="missing 'content'"):
            validate_conversation(
                cast(Any, [{"mode": InteractionMode.CHAT, "message": {"role": "user"}}])
            )

    def test_invalid_role_raises(self):
        with pytest.raises(ConversationError, match="invalid role"):
            validate_conversation(
                [
                    {
                        "mode": InteractionMode.CHAT,
                        "message": {"role": "system", "content": "hi"},
                    }
                ]
            )

    def test_invalid_content_type_raises(self):
        with pytest.raises(ConversationError, match="must be a string or list"):
            validate_conversation(
                cast(
                    Any,
                    [
                        {
                            "mode": InteractionMode.CHAT,
                            "message": {"role": "user", "content": 42},
                        }
                    ],
                )
            )

    def test_first_message_not_user_warns(self):
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "hi"},
            }
        ]
        warnings = validate_conversation(msgs)
        assert any("first message" in w for w in warnings)

    def test_consecutive_assistant_warns(self):
        msgs: list[StoredMessage] = [
            {"mode": InteractionMode.CHAT, "message": {"role": "user", "content": "q"}},
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "a1"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "assistant", "content": "a2"},
            },
        ]
        warnings = validate_conversation(msgs)
        assert any("consecutive" in w for w in warnings)

    def test_consecutive_user_does_not_warn(self):
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "q1"},
            },
            {
                "mode": InteractionMode.CHAT,
                "message": {"role": "user", "content": "q2"},
            },
        ]
        warnings = validate_conversation(msgs)
        assert warnings == []

    def test_content_as_list_is_valid(self):
        # Anthropic supports list content blocks (e.g. tool use)
        msgs: list[StoredMessage] = [
            {
                "mode": InteractionMode.CHAT,
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "hi"}],
                },
            }
        ]
        assert validate_conversation(msgs) == []


# ---------------------------------------------------------------------------
# load_conversation (structural / error path tests)
# ---------------------------------------------------------------------------


class TestLoadConversation:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_conversation(tmp_path / "nope.json") == []

    def test_valid_file(self, tmp_path):
        p = tmp_path / "conv.json"
        msgs: list[StoredMessage] = [
            {"mode": InteractionMode.CHAT, "message": {"role": "user", "content": "hi"}}
        ]
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

    def test_empty_object_returns_empty_no_warning(self, tmp_path, capsys):
        # A bare {} (no messages key, no other keys) is now treated as an
        # empty conversation silently — _read_raw returning {} is a legitimate
        # "file has nothing in it yet" state, not a malformed-file warning.
        p = tmp_path / "conv.json"
        p.write_text("{}")
        result = load_conversation(p)
        assert result == []

    def test_session_state_only_file_returns_empty_messages(self, tmp_path):
        # A file containing only session_state (no messages key at all) is a
        # legitimate shape — e.g. produced by cmd_set_provider before any
        # prompt has ever been sent. Must not warn or exit.
        p = tmp_path / "conv.json"
        p.write_text(json.dumps({"session_state": {"provider": "openai"}}))
        assert load_conversation(p) == []

    def test_messages_not_list_exits(self, tmp_path):
        p = tmp_path / "conv.json"
        p.write_text(json.dumps({"messages": "oops"}))
        with pytest.raises(SystemExit):
            load_conversation(p)


# ---------------------------------------------------------------------------
# save_conversation — preserves session_state (read-modify-write contract)
# ---------------------------------------------------------------------------


class TestSaveConversationPreservesSessionState:
    def test_save_does_not_clobber_existing_session_state(self, tmp_path):
        p = tmp_path / "conv.json"
        save_session_state({"provider": "openai"}, p)

        msgs: list[StoredMessage] = [
            {"mode": InteractionMode.CHAT, "message": {"role": "user", "content": "hi"}}
        ]
        save_conversation(msgs, p)

        data = json.loads(p.read_text())
        assert data["session_state"] == {"provider": "openai"}
        assert data["messages"] == msgs

    def test_reset_conversation_preserves_session_state(self, tmp_path):
        # reset_conversation only clears messages; session_state is orthogonal
        # and must survive a reset (per design discussion).
        p = tmp_path / "conv.json"
        save_session_state({"provider": "openai", "model": "custom"}, p)
        msgs: list[StoredMessage] = [
            {"mode": InteractionMode.CHAT, "message": {"role": "user", "content": "hi"}}
        ]
        save_conversation(msgs, p)

        reset_conversation(p)

        data = json.loads(p.read_text())
        assert data["messages"] == []
        assert data["session_state"] == {"provider": "openai", "model": "custom"}


# ---------------------------------------------------------------------------
# load_session_state / save_session_state
# ---------------------------------------------------------------------------


class TestSessionState:
    def test_missing_file_returns_empty(self, tmp_path):
        assert load_session_state(tmp_path / "nope.json") == {}

    def test_no_session_state_key_returns_empty(self, tmp_path):
        p = tmp_path / "conv.json"
        save_conversation([], p)
        assert load_session_state(p) == {}

    def test_round_trip(self, tmp_path):
        p = tmp_path / "conv.json"
        state = {"provider": "openai", "model": "custom-model"}
        save_session_state(state, p)
        assert load_session_state(p) == state

    def test_falsy_state_removes_key(self, tmp_path):
        p = tmp_path / "conv.json"
        save_session_state({"provider": "openai"}, p)
        save_session_state(None, p)
        data = json.loads(p.read_text())
        assert "session_state" not in data

    def test_empty_dict_removes_key(self, tmp_path):
        p = tmp_path / "conv.json"
        save_session_state({"provider": "openai"}, p)
        save_session_state({}, p)
        data = json.loads(p.read_text())
        assert "session_state" not in data

    def test_malformed_session_state_warns_and_returns_empty(self, tmp_path, capsys):
        p = tmp_path / "conv.json"
        p.write_text(json.dumps({"session_state": "not-an-object"}))
        result = load_session_state(p)
        assert result == {}
        assert "session_state" in capsys.readouterr().err.lower()

    def test_preserves_messages_alongside_session_state(self, tmp_path):
        p = tmp_path / "conv.json"
        msgs: list[StoredMessage] = [
            {"mode": InteractionMode.CHAT, "message": {"role": "user", "content": "hi"}}
        ]
        save_conversation(msgs, p)
        save_session_state({"provider": "openai"}, p)

        data = json.loads(p.read_text())
        assert data["messages"] == msgs
        assert data["session_state"] == {"provider": "openai"}

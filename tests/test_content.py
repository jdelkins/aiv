from __future__ import annotations

import pytest
from pathlib import Path
from unittest.mock import patch

from aiv.content import build_user_content


# ---------------------------------------------------------------------------
# build_user_content
# ---------------------------------------------------------------------------


class TestBuildUserContent:
    def test_prompt_only(self):
        result = build_user_content("hello", [], None)
        assert result == "hello"

    def test_prompt_with_mode_suffix(self):
        result = build_user_content("hello", [], None, mode_suffix=" [code]")
        assert result == "hello [code]"

    def test_stdin_data_adds_context_block(self):
        with patch("aiv.content.find_file_location", return_value=""):
            result = build_user_content("my prompt", [], "some stdin")
        assert "---CONTEXT_TXT:---" in result
        assert "some stdin" in result
        assert "my prompt" in result

    def test_stdin_data_location_hint(self):
        with patch("aiv.content.find_file_location", return_value="[foo.py:1:5]"):
            result = build_user_content("prompt", [], "data")
        assert "---CONTEXT_TXT:[foo.py:1:5]---" in result

    def test_stdin_data_prompt_appears_after_block(self):
        with patch("aiv.content.find_file_location", return_value=""):
            result = build_user_content("my prompt", [], "stdin content")
        # prompt must appear after the ---END--- closing the stdin block
        end_pos = result.index("---END---")
        prompt_pos = result.index("my prompt")
        assert prompt_pos > end_pos

    def test_dash_sentinel_skipped_in_context_files(self):
        # "-" in context_files should be ignored; stdin_data is the mechanism
        with patch("aiv.content.find_file_location", return_value=""):
            result = build_user_content("prompt", ["-"], None)
        assert "---CONTEXT_FILE:" not in result
        assert result == "prompt"

    def test_file_context_block(self, tmp_path):
        f = tmp_path / "hello.txt"
        f.write_text("file contents")
        result = build_user_content("prompt", [str(f)], None)
        assert f"---CONTEXT_FILE:[{f}]---" in result
        assert "file contents" in result
        assert "---END---" in result

    def test_nonexistent_glob_produces_no_block(self, tmp_path):
        pattern = str(tmp_path / "*.nonexistent")
        result = build_user_content("prompt", [pattern], None)
        assert "---CONTEXT_FILE:" not in result
        assert result == "prompt"

    def test_directories_skipped_in_glob(self, tmp_path):
        # glob may match directories; they should be silently skipped
        subdir = tmp_path / "subdir"
        subdir.mkdir()
        result = build_user_content("prompt", [str(tmp_path / "*")], None)
        assert "---CONTEXT_FILE:" not in result

    def test_multiple_files_sorted(self, tmp_path):
        # Files should appear in sorted glob order
        (tmp_path / "b.txt").write_text("b")
        (tmp_path / "a.txt").write_text("a")
        result = build_user_content("prompt", [str(tmp_path / "*.txt")], None)
        a_pos = result.index("a.txt")
        b_pos = result.index("b.txt")
        assert a_pos < b_pos

    def test_mode_suffix_appended_to_prompt_with_stdin(self):
        with patch("aiv.content.find_file_location", return_value=""):
            result = build_user_content("prompt", [], "stdin", mode_suffix=" SUFFIX")
        assert result.endswith("prompt SUFFIX")

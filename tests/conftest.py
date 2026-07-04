from __future__ import annotations

import pytest
from pathlib import Path

from aiv.models import PipelineContext


@pytest.fixture
def tmp_conv_path(tmp_path) -> Path:
    return tmp_path / "conversation.json"


@pytest.fixture
def minimal_ctx(tmp_conv_path) -> PipelineContext:
    """
    A PipelineContext with no real credentials and a throwaway conversation
    file. Suitable for any test that needs a ctx without making API calls.
    """
    return PipelineContext(
        api_key="test-key",
        conv_path=tmp_conv_path,
    )

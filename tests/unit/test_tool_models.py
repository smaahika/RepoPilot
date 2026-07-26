"""Tests for strict tool request schemas and result invariants."""

import pytest
from pydantic import ValidationError

from repopilot.tool_models import (
    ListFilesData,
    ListFilesRequest,
    ReadFileRequest,
    RunCommandRequest,
    ToolName,
    ToolResult,
    WritePatchRequest,
)


def test_requests_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ListFilesRequest.model_validate({"root": ".", "unexpected": True})


def test_read_request_rejects_reversed_line_range() -> None:
    with pytest.raises(ValidationError, match="end_line must be"):
        ReadFileRequest(path="file.txt", start_line=5, end_line=4)


def test_command_request_rejects_nul_argument() -> None:
    with pytest.raises(ValidationError, match="cannot contain NUL"):
        RunCommandRequest(argv=("pytest", "bad\x00argument"))


def test_patch_request_enforces_utf8_byte_limit() -> None:
    with pytest.raises(ValidationError, match="UTF-8 bytes"):
        WritePatchRequest(patch="é" * 600_000)


def test_tool_result_requires_exactly_one_payload() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        ToolResult[ListFilesData](tool_name=ToolName.LIST_FILES, duration_ms=0)

"""Factories for consistently timed tool results."""

from __future__ import annotations

import time

from repopilot.tool_models import ToolError, ToolErrorCode, ToolName, ToolResult


def started_at() -> int:
    return time.monotonic_ns()


def succeeded[ResultData](
    tool_name: ToolName,
    started: int,
    data: ResultData,
) -> ToolResult[ResultData]:
    return ToolResult(
        tool_name=tool_name,
        duration_ms=_elapsed_ms(started),
        data=data,
    )


def failed[ResultData](
    tool_name: ToolName,
    started: int,
    code: ToolErrorCode,
    message: str,
) -> ToolResult[ResultData]:
    return ToolResult(
        tool_name=tool_name,
        duration_ms=_elapsed_ms(started),
        error=ToolError(code=code, message=message),
    )


def _elapsed_ms(started: int) -> int:
    return (time.monotonic_ns() - started) // 1_000_000

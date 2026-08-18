"""Tests for normalized verification outcomes."""

import pytest

from repopilot.tool_models import (
    RunCommandData,
    ToolError,
    ToolErrorCode,
    ToolName,
    ToolResult,
)
from repopilot.verification import (
    CheckKind,
    VerificationStatus,
    normalize_command,
    verify_diff,
)


def test_normalizes_nonzero_test_exit_as_failed_check() -> None:
    result = ToolResult(
        tool_name=ToolName.RUN_COMMAND,
        duration_ms=12,
        data=RunCommandData(
            argv=("pytest", "-q"),
            cwd=".",
            exit_code=1,
            stdout="one failed",
            stderr="",
        ),
    )

    verification = normalize_command(result)

    assert verification.status is VerificationStatus.FAILED
    assert verification.check_kind is CheckKind.TEST
    assert verification.exit_code == 1
    assert verification.stdout == "one failed"
    assert verification.retryable


def test_normalizes_tool_timeout_separately_from_failed_check() -> None:
    result: ToolResult[RunCommandData] = ToolResult(
        tool_name=ToolName.RUN_COMMAND,
        duration_ms=120_000,
        error=ToolError(code=ToolErrorCode.TIMEOUT, message="command timed out"),
    )

    verification = normalize_command(result, ("pytest", "-q"))

    assert verification.status is VerificationStatus.TIMEOUT
    assert verification.check_kind is CheckKind.TEST
    assert verification.exit_code is None
    assert verification.retryable


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (("ruff", "check", "."), CheckKind.LINT),
        (("npm", "run", "lint"), CheckKind.LINT),
        (("mypy",), CheckKind.TYPE_CHECK),
        (("npm", "test"), CheckKind.TEST),
    ],
)
def test_classifies_supported_verification_commands(
    argv: tuple[str, ...],
    expected: CheckKind,
) -> None:
    result = ToolResult(
        tool_name=ToolName.RUN_COMMAND,
        duration_ms=1,
        data=RunCommandData(
            argv=argv,
            cwd=".",
            exit_code=0,
            stdout="",
            stderr="",
        ),
    )

    assert normalize_command(result).check_kind is expected


def test_diff_verification_requires_visible_change() -> None:
    assert verify_diff("diff --git a/a b/a").passed
    assert verify_diff("").status is VerificationStatus.FAILED

"""Stable interpretation of diff and command verification outcomes."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from repopilot.tool_models import RunCommandData, ToolErrorCode, ToolResult


class VerificationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"


class CheckKind(StrEnum):
    DIFF = "diff"
    TEST = "test"
    LINT = "lint"
    TYPE_CHECK = "type_check"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class VerificationResult:
    status: VerificationStatus
    check_kind: CheckKind
    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int
    message: str
    retryable: bool

    @property
    def passed(self) -> bool:
        return self.status is VerificationStatus.PASSED


def verify_diff(patch: str) -> VerificationResult:
    if patch:
        return VerificationResult(
            status=VerificationStatus.PASSED,
            check_kind=CheckKind.DIFF,
            argv=(),
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=0,
            message="Repository diff is non-empty.",
            retryable=False,
        )
    return VerificationResult(
        status=VerificationStatus.FAILED,
        check_kind=CheckKind.DIFF,
        argv=(),
        exit_code=None,
        stdout="",
        stderr="",
        duration_ms=0,
        message="Repository diff is empty.",
        retryable=True,
    )


def normalize_command(
    result: ToolResult[RunCommandData],
    requested_argv: tuple[str, ...] = (),
) -> VerificationResult:
    if result.error is not None:
        status = (
            VerificationStatus.TIMEOUT
            if result.error.code is ToolErrorCode.TIMEOUT
            else VerificationStatus.ERROR
        )
        return VerificationResult(
            status=status,
            check_kind=_check_kind(requested_argv),
            argv=requested_argv,
            exit_code=None,
            stdout="",
            stderr="",
            duration_ms=result.duration_ms,
            message=result.error.message,
            retryable=status is VerificationStatus.TIMEOUT,
        )

    assert result.data is not None
    status = VerificationStatus.PASSED if result.data.exit_code == 0 else VerificationStatus.FAILED
    return VerificationResult(
        status=status,
        check_kind=_check_kind(result.data.argv),
        argv=result.data.argv,
        exit_code=result.data.exit_code,
        stdout=result.data.stdout,
        stderr=result.data.stderr,
        duration_ms=result.duration_ms,
        message=(
            "Verification command passed."
            if status is VerificationStatus.PASSED
            else f"Verification command exited with code {result.data.exit_code}."
        ),
        retryable=status is VerificationStatus.FAILED,
    )


def _check_kind(argv: tuple[str, ...]) -> CheckKind:
    if not argv:
        return CheckKind.OTHER
    if argv[0] == "pytest" or argv[:3] in (
        ("python", "-m", "pytest"),
        ("python3", "-m", "pytest"),
    ):
        return CheckKind.TEST
    if argv[0] == "ruff" or argv[:3] in (("npm", "run", "lint"),):
        return CheckKind.LINT
    if argv[0] == "mypy":
        return CheckKind.TYPE_CHECK
    if argv[:2] == ("npm", "test") or argv[:3] == ("npm", "run", "test"):
        return CheckKind.TEST
    return CheckKind.OTHER

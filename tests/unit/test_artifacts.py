"""Tests for bounded, atomic terminal artifact persistence."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from repopilot.artifacts import FilesystemArtifactWriter
from repopilot.errors import ArtifactPersistenceError
from repopilot.model_models import ImplementationPlan, ModelUsage, PlanStep, Reflection
from repopilot.run_models import (
    ContextMetric,
    LocalRepositorySource,
    RunCounters,
    RunRequest,
    RunResult,
    TerminationReason,
    TransitionRecord,
)
from repopilot.state_machine import RunEvent, RunPhase
from repopilot.verification import CheckKind, VerificationResult, VerificationStatus

_SECRET = "provider-secret-value"


def _request() -> RunRequest:
    return RunRequest(
        source=LocalRepositorySource(path=Path("/source")),
        task=f"Update the greeting without exposing {_SECRET}.",
        run_id="artifact-test",
    )


def _result(artifact_path: Path, *, success: bool = True) -> RunResult:
    phase = RunPhase.COMPLETE if success else RunPhase.FAILED
    reason = TerminationReason.SUCCESS if success else TerminationReason.VERIFICATION_FAILED
    return RunResult(
        run_id="artifact-test",
        phase=phase,
        termination_reason=reason,
        plan=ImplementationPlan(
            summary="Update the greeting.",
            steps=(
                PlanStep(
                    id="update",
                    objective="Change greeting.py.",
                    files=("greeting.py",),
                    verification=("pytest -q",),
                ),
            ),
            assumptions=(),
        ),
        patch=f"diff --git a/greeting.py b/greeting.py\n+{_SECRET}\n" if success else "",
        verifications=(
            VerificationResult(
                status=VerificationStatus.PASSED,
                check_kind=CheckKind.DIFF,
                argv=(),
                exit_code=None,
                stdout="",
                stderr="",
                duration_ms=0,
                message="Repository diff is non-empty.",
                retryable=False,
            ),
            VerificationResult(
                status=VerificationStatus.PASSED if success else VerificationStatus.FAILED,
                check_kind=CheckKind.TEST,
                argv=("pytest", "-q"),
                exit_code=0 if success else 1,
                stdout=f"output containing {_SECRET}",
                stderr="",
                duration_ms=12,
                message="Verification command passed." if success else "Tests failed.",
                retryable=not success,
            ),
        ),
        reflections=(Reflection(diagnosis="A test failed.", next_step="Fix it."),),
        counters=RunCounters(model_calls=3, tool_calls=4, iterations=1, elapsed_ms=50),
        usage=ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        transitions=(
            TransitionRecord(
                run_id="artifact-test",
                sequence=1,
                previous_phase=RunPhase.INITIALIZE,
                event=RunEvent.WORKSPACE_READY,
                next_phase=RunPhase.INSPECT,
                elapsed_ms=1,
            ),
            TransitionRecord(
                run_id="artifact-test",
                sequence=2,
                previous_phase=RunPhase.VERIFY,
                event=RunEvent.VERIFICATION_PASSED if success else RunEvent.FAILED,
                next_phase=phase,
                elapsed_ms=50,
            ),
        ),
        failure_message=None if success else f"Verification failed with {_SECRET}.",
        artifact_path=artifact_path,
        context_metrics=(
            ContextMetric(
                operation="create_plan",
                original_chars=1_000,
                selected_chars=400,
                compacted_items=8,
            ),
        ),
    )


def _artifact_path(run_root: Path) -> Path:
    path = run_root / "runs" / "artifact-test"
    path.mkdir(parents=True)
    return path


def test_writes_complete_artifact_set_and_redacts_known_secret(tmp_path: Path) -> None:
    artifact_path = _artifact_path(tmp_path)
    writer = FilesystemArtifactWriter(tmp_path, redactions=(_SECRET,))

    writer.write(_request(), _result(artifact_path))

    assert {path.relative_to(artifact_path).as_posix() for path in artifact_path.rglob("*")} == {
        "commands",
        "commands/001-test.log",
        "events.jsonl",
        "patch.diff",
        "report.md",
    }
    report = (artifact_path / "report.md").read_text(encoding="utf-8")
    assert "Status: `success`" in report
    assert "Total tokens: 15" in report
    assert "Character reduction: 60%" in report
    assert "commands/001-test.log" in report
    assert _SECRET not in report
    assert _SECRET not in (artifact_path / "patch.diff").read_text(encoding="utf-8")
    command_log = (artifact_path / "commands" / "001-test.log").read_text(encoding="utf-8")
    assert "[REDACTED]" in command_log
    events = [
        json.loads(line)
        for line in (artifact_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [event["sequence"] for event in events] == [1, 2]
    assert events[0]["schema_version"] == 1
    assert events[-1]["event"] == "verification_passed"


def test_failed_run_still_writes_report_and_empty_patch(tmp_path: Path) -> None:
    artifact_path = _artifact_path(tmp_path)
    writer = FilesystemArtifactWriter(tmp_path, redactions=(_SECRET,))

    writer.write(_request(), _result(artifact_path, success=False))

    report = (artifact_path / "report.md").read_text(encoding="utf-8")
    assert "Status: `verification_failed`" in report
    assert "## Failure" in report
    assert "[REDACTED]" in report
    assert (artifact_path / "patch.diff").read_bytes() == b""
    assert json.loads((artifact_path / "events.jsonl").read_text().splitlines()[-1])["event"] == (
        "failed"
    )


def test_refuses_to_overwrite_existing_artifacts(tmp_path: Path) -> None:
    artifact_path = _artifact_path(tmp_path)
    writer = FilesystemArtifactWriter(tmp_path)
    result = _result(artifact_path)
    writer.write(_request(), result)
    original_report = (artifact_path / "report.md").read_bytes()

    with pytest.raises(ArtifactPersistenceError, match="Could not persist"):
        writer.write(_request(), result)

    assert (artifact_path / "report.md").read_bytes() == original_report


def test_refuses_artifact_path_outside_run_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(ArtifactPersistenceError, match="outside the allocated"):
        FilesystemArtifactWriter(tmp_path).write(_request(), _result(outside))


def test_reports_when_run_failed_before_artifact_allocation(tmp_path: Path) -> None:
    result = replace(_result(tmp_path), artifact_path=None)

    with pytest.raises(ArtifactPersistenceError, match="before an artifact directory"):
        FilesystemArtifactWriter(tmp_path).write(_request(), result)


def test_rejects_artifact_above_hard_byte_limit(tmp_path: Path) -> None:
    artifact_path = _artifact_path(tmp_path)
    result = replace(_result(artifact_path), patch="x" * 1_048_577)

    with pytest.raises(ArtifactPersistenceError, match=r"patch.diff.*byte limit"):
        FilesystemArtifactWriter(tmp_path).write(_request(), result)

    assert not (artifact_path / "patch.diff").exists()

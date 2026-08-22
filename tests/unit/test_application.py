"""Tests for application-level execution and persistence sequencing."""

from __future__ import annotations

from pathlib import Path

import pytest

from repopilot.application import PersistingRunApplication
from repopilot.errors import ArtifactPersistenceError
from repopilot.run_models import (
    LocalRepositorySource,
    RunCounters,
    RunRequest,
    RunResult,
    TerminationReason,
)
from repopilot.state_machine import RunPhase


def _request() -> RunRequest:
    return RunRequest(source=LocalRepositorySource(path=Path(".")), task="Update docs.")


def _result() -> RunResult:
    return RunResult(
        run_id="application-test",
        phase=RunPhase.COMPLETE,
        termination_reason=TerminationReason.SUCCESS,
        plan=None,
        patch="diff",
        verifications=(),
        reflections=(),
        counters=RunCounters(model_calls=0, tool_calls=0, iterations=0, elapsed_ms=0),
        usage=None,
        transitions=(),
    )


def test_persists_result_after_execution() -> None:
    calls: list[str] = []
    result = _result()

    class Executor:
        def run(self, request: RunRequest) -> RunResult:
            calls.append(f"run:{request.task}")
            return result

    class Writer:
        def write(self, request: RunRequest, received: RunResult) -> None:
            assert received is result
            calls.append(f"write:{request.task}")

    returned = PersistingRunApplication(Executor(), Writer()).run(_request())

    assert returned is result
    assert calls == ["run:Update docs.", "write:Update docs."]


def test_propagates_persistence_failure() -> None:
    class Executor:
        def run(self, request: RunRequest) -> RunResult:
            return _result()

    class Writer:
        def write(self, request: RunRequest, result: RunResult) -> None:
            raise ArtifactPersistenceError("disk unavailable")

    with pytest.raises(ArtifactPersistenceError, match="disk unavailable"):
        PersistingRunApplication(Executor(), Writer()).run(_request())

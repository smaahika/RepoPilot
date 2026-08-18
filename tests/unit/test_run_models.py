"""Tests for bounded run inputs and terminal result invariants."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from repopilot.run_models import (
    LocalRepositorySource,
    RunBudgets,
    RunCounters,
    RunRequest,
    RunResult,
    TerminationReason,
)
from repopilot.state_machine import RunPhase


def test_run_budgets_reject_values_above_system_maximum() -> None:
    with pytest.raises(ValidationError, match="less than or equal to 50"):
        RunBudgets(max_model_calls=51)


def test_run_request_rejects_unknown_source_fields() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RunRequest.model_validate(
            {
                "source": {"kind": "local", "path": ".", "url": "https://example.com"},
                "task": "Change a greeting",
            }
        )


def test_terminal_result_requires_failure_details_only_on_failure() -> None:
    counters = RunCounters(model_calls=0, tool_calls=0, iterations=0, elapsed_ms=0)

    with pytest.raises(ValueError, match="Failed runs require"):
        RunResult(
            run_id="run-1",
            phase=RunPhase.FAILED,
            termination_reason=TerminationReason.EDIT_FAILED,
            plan=None,
            patch="",
            verifications=(),
            reflections=(),
            counters=counters,
            usage=None,
            transitions=(),
        )


def test_run_request_accepts_local_source_model() -> None:
    request = RunRequest(
        source=LocalRepositorySource(path=Path(".")),
        task="Change a greeting",
    )

    assert request.source.kind == "local"

"""Tests for atomic transition recording and logger failure isolation."""

import pytest

from repopilot.errors import RunLoggingError
from repopilot.run_logging import RunLogger, TransitionRecorder
from repopilot.run_models import TransitionRecord
from repopilot.state_machine import RunEvent, RunPhase, RunStateMachine


class _FailingLogger:
    def record_transition(self, record: TransitionRecord) -> None:
        raise RuntimeError("logger unavailable")


def test_logger_failure_does_not_advance_state() -> None:
    machine = RunStateMachine()
    recorder = TransitionRecorder(_FailingLogger())

    with pytest.raises(RunLoggingError, match="RuntimeError"):
        recorder.advance(machine, RunEvent.WORKSPACE_READY, "run-1", 10)

    assert machine.phase is RunPhase.INITIALIZE
    assert recorder.records == []


def test_recorder_disables_failed_logger_for_terminal_transition() -> None:
    machine = RunStateMachine()
    logger: RunLogger = _FailingLogger()
    recorder = TransitionRecorder(logger)

    with pytest.raises(RunLoggingError):
        recorder.advance(machine, RunEvent.WORKSPACE_READY, "run-1", 10)
    recorder.advance(machine, RunEvent.FAILED, "run-1", 11)

    assert machine.phase is RunPhase.FAILED
    assert [record.event for record in recorder.records] == [RunEvent.FAILED]

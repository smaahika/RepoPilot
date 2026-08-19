"""Transition logging interfaces for controller observability."""

from __future__ import annotations

from typing import Protocol

from repopilot.errors import RunLoggingError
from repopilot.run_models import TransitionRecord
from repopilot.state_machine import RunEvent, RunStateMachine


class RunLogger(Protocol):
    def record_transition(self, record: TransitionRecord) -> None:
        """Persist or collect one accepted state transition."""
        ...


class NullRunLogger:
    def record_transition(self, record: TransitionRecord) -> None:
        return None


class InMemoryRunLogger:
    def __init__(self) -> None:
        self.records: list[TransitionRecord] = []

    def record_transition(self, record: TransitionRecord) -> None:
        self.records.append(record)


class TransitionRecorder:
    """Coordinate external logging with atomic state advancement."""

    def __init__(self, logger: RunLogger) -> None:
        self._logger = logger
        self._logging_disabled = False
        self.records: list[TransitionRecord] = []

    def advance(
        self,
        machine: RunStateMachine,
        event: RunEvent,
        run_id: str,
        elapsed_ms: int,
    ) -> None:
        next_phase = machine.next_phase(event)
        record = TransitionRecord(
            run_id=run_id,
            sequence=len(self.records) + 1,
            previous_phase=machine.phase,
            event=event,
            next_phase=next_phase,
            elapsed_ms=elapsed_ms,
        )
        if not self._logging_disabled:
            try:
                self._logger.record_transition(record)
            except Exception as error:
                self._logging_disabled = True
                raise RunLoggingError(
                    f"Transition logger raised {type(error).__name__}."
                ) from error

        transition = machine.advance(event)
        assert transition.next_phase is next_phase
        self.records.append(record)

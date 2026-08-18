"""Transition logging interfaces for controller observability."""

from __future__ import annotations

from typing import Protocol

from repopilot.run_models import TransitionRecord


class RunLogger(Protocol):
    def record_transition(self, record: TransitionRecord) -> None:
        """Persist or collect one accepted state transition."""
        ...


class NullRunLogger:
    def record_transition(self, record: TransitionRecord) -> None:
        pass


class InMemoryRunLogger:
    def __init__(self) -> None:
        self.records: list[TransitionRecord] = []

    def record_transition(self, record: TransitionRecord) -> None:
        self.records.append(record)

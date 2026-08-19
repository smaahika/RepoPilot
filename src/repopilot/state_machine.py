"""Explicit phases, events, and legal transitions for a RepoPilot run."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from repopilot.errors import InvalidTransitionError


class RunPhase(StrEnum):
    INITIALIZE = "initialize"
    INSPECT = "inspect"
    PLAN = "plan"
    EDIT = "edit"
    VERIFY = "verify"
    REFLECT = "reflect"
    COMPLETE = "complete"
    FAILED = "failed"


class RunEvent(StrEnum):
    WORKSPACE_READY = "workspace_ready"
    INVENTORY_READY = "inventory_ready"
    PLAN_READY = "plan_ready"
    TOOL_COMPLETED = "tool_completed"
    PATCH_APPLIED = "patch_applied"
    VERIFICATION_FAILED = "verification_failed"
    REFLECTION_READY = "reflection_ready"
    VERIFICATION_PASSED = "verification_passed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class StateTransition:
    previous_phase: RunPhase
    event: RunEvent
    next_phase: RunPhase


_TRANSITIONS: dict[tuple[RunPhase, RunEvent], RunPhase] = {
    (RunPhase.INITIALIZE, RunEvent.WORKSPACE_READY): RunPhase.INSPECT,
    (RunPhase.INITIALIZE, RunEvent.FAILED): RunPhase.FAILED,
    (RunPhase.INSPECT, RunEvent.INVENTORY_READY): RunPhase.PLAN,
    (RunPhase.INSPECT, RunEvent.FAILED): RunPhase.FAILED,
    (RunPhase.PLAN, RunEvent.PLAN_READY): RunPhase.EDIT,
    (RunPhase.PLAN, RunEvent.FAILED): RunPhase.FAILED,
    (RunPhase.EDIT, RunEvent.TOOL_COMPLETED): RunPhase.EDIT,
    (RunPhase.EDIT, RunEvent.PATCH_APPLIED): RunPhase.VERIFY,
    (RunPhase.EDIT, RunEvent.FAILED): RunPhase.FAILED,
    (RunPhase.VERIFY, RunEvent.VERIFICATION_FAILED): RunPhase.REFLECT,
    (RunPhase.VERIFY, RunEvent.VERIFICATION_PASSED): RunPhase.COMPLETE,
    (RunPhase.VERIFY, RunEvent.FAILED): RunPhase.FAILED,
    (RunPhase.REFLECT, RunEvent.REFLECTION_READY): RunPhase.EDIT,
    (RunPhase.REFLECT, RunEvent.FAILED): RunPhase.FAILED,
}


class RunStateMachine:
    """Advance only through transitions declared in the transition table."""

    def __init__(self) -> None:
        self._phase = RunPhase.INITIALIZE

    @property
    def phase(self) -> RunPhase:
        return self._phase

    def next_phase(self, event: RunEvent) -> RunPhase:
        """Validate an event and return its target without mutating state."""
        try:
            return _TRANSITIONS[(self._phase, event)]
        except KeyError as error:
            raise InvalidTransitionError(
                f"Event {event.value!r} is invalid during phase {self._phase.value!r}."
            ) from error

    def advance(self, event: RunEvent) -> StateTransition:
        next_phase = self.next_phase(event)
        transition = StateTransition(self._phase, event, next_phase)
        self._phase = next_phase
        return transition

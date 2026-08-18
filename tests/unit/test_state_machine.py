"""Tests for explicit controller state transitions."""

import pytest

from repopilot.errors import InvalidTransitionError
from repopilot.state_machine import RunEvent, RunPhase, RunStateMachine


def test_state_machine_follows_the_day_five_success_path() -> None:
    machine = RunStateMachine()

    assert machine.advance(RunEvent.WORKSPACE_READY).next_phase is RunPhase.INSPECT
    assert machine.advance(RunEvent.INVENTORY_READY).next_phase is RunPhase.PLAN
    assert machine.advance(RunEvent.PLAN_READY).next_phase is RunPhase.EDIT
    loop = machine.advance(RunEvent.TOOL_COMPLETED)
    assert loop.previous_phase is RunPhase.EDIT
    assert loop.next_phase is RunPhase.EDIT
    assert machine.advance(RunEvent.PATCH_APPLIED).next_phase is RunPhase.VERIFY
    assert machine.advance(RunEvent.VERIFICATION_PASSED).next_phase is RunPhase.COMPLETE


def test_state_machine_rejects_skipped_and_terminal_transitions() -> None:
    machine = RunStateMachine()

    with pytest.raises(InvalidTransitionError, match="invalid during phase 'initialize'"):
        machine.advance(RunEvent.PLAN_READY)

    machine.advance(RunEvent.FAILED)
    with pytest.raises(InvalidTransitionError, match="invalid during phase 'failed'"):
        machine.advance(RunEvent.WORKSPACE_READY)


def test_state_machine_routes_failed_verification_through_reflection() -> None:
    machine = RunStateMachine()
    machine.advance(RunEvent.WORKSPACE_READY)
    machine.advance(RunEvent.INVENTORY_READY)
    machine.advance(RunEvent.PLAN_READY)
    machine.advance(RunEvent.PATCH_APPLIED)

    assert machine.advance(RunEvent.VERIFICATION_FAILED).next_phase is RunPhase.REFLECT
    assert machine.advance(RunEvent.REFLECTION_READY).next_phase is RunPhase.EDIT

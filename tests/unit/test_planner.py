"""Tests for provider-neutral planning and the scripted model."""

import json

import pytest

from repopilot.errors import ModelOutputError, ModelScriptExhaustedError
from repopilot.model_models import ImplementationPlan
from repopilot.models import FileEntry, FileKind, RepositoryInventory
from repopilot.planner import Planner, PlanningRequest
from repopilot.scripted_model import ScriptedModel


def _plan() -> dict[str, object]:
    return {
        "summary": "Update the greeting and verify it.",
        "steps": [
            {
                "id": "update_greeting",
                "objective": "Change the greeting.",
                "files": ["src/app.py"],
                "verification": ["pytest"],
            }
        ],
        "assumptions": [],
    }


def test_planner_builds_deterministic_inventory_context() -> None:
    model = ScriptedModel([_plan()])
    planner = Planner(model)
    inventory = RepositoryInventory(
        entries=(FileEntry(path="src/app.py", size_bytes=42, kind=FileKind.FILE),)
    )

    response = planner.create_plan(PlanningRequest(task="Update greeting", inventory=inventory))

    assert isinstance(response.output, ImplementationPlan)
    invocation = model.invocations[0]
    assert invocation.request.operation == "create_plan"
    assert json.loads(invocation.request.input) == {
        "task": "Update greeting",
        "repository_inventory": [{"path": "src/app.py", "size_bytes": 42, "kind": "file"}],
    }


def test_scripted_model_rejects_malformed_response() -> None:
    model = ScriptedModel([{"summary": "Missing steps"}])
    planner = Planner(model)
    request = PlanningRequest(task="Update greeting", inventory=RepositoryInventory(entries=()))

    with pytest.raises(ModelOutputError, match="schema validation"):
        planner.create_plan(request)


def test_scripted_model_raises_queued_failure() -> None:
    expected = ModelOutputError("Provider returned malformed data.")
    model = ScriptedModel([expected])
    planner = Planner(model)
    request = PlanningRequest(task="Update greeting", inventory=RepositoryInventory(entries=()))

    with pytest.raises(ModelOutputError) as raised:
        planner.create_plan(request)

    assert raised.value is expected


def test_scripted_model_reports_unexpected_extra_call() -> None:
    model = ScriptedModel([])
    planner = Planner(model)
    request = PlanningRequest(task="Update greeting", inventory=RepositoryInventory(entries=()))

    with pytest.raises(ModelScriptExhaustedError, match="no response"):
        planner.create_plan(request)

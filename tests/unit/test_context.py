"""Tests for deterministic context ranking, compaction, and metrics."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from repopilot.context import ContextPolicy, ContextSession
from repopilot.editor import EditRequest, ToolObservation
from repopilot.model_models import ImplementationPlan, PlanStep
from repopilot.models import FileEntry, FileKind, RepositoryInventory


def _plan() -> ImplementationPlan:
    return ImplementationPlan(
        summary="Update the greeting.",
        steps=(
            PlanStep(
                id="update",
                objective="Change the greeting implementation.",
                files=("src/greeting.py",),
                verification=("pytest -q",),
            ),
        ),
        assumptions=(),
    )


def test_planning_context_ranks_task_paths_before_project_metadata() -> None:
    session = ContextSession(ContextPolicy(max_planning_entries=2))
    inventory = RepositoryInventory(
        entries=(
            FileEntry("docs/notes.md", 20, FileKind.FILE),
            FileEntry("pyproject.toml", 30, FileKind.FILE),
            FileEntry("src/greeting.py", 40, FileKind.FILE),
        )
    )

    payload = json.loads(session.planning_input("Update src/greeting.py", inventory))

    assert [entry["path"] for entry in payload["repository_inventory"]] == [
        "src/greeting.py",
        "pyproject.toml",
    ]
    assert payload["inventory_summary"] == {
        "total_entries": 3,
        "selected_entries": 2,
        "omitted_entries": 1,
    }
    assert session.metrics[0].compacted_items == 1
    assert session.metrics[0].original_chars > 0


def test_planning_context_enforces_its_serialized_character_limit() -> None:
    policy = ContextPolicy(max_planning_chars=20_000, max_planning_entries=1_000)
    session = ContextSession(policy)
    inventory = RepositoryInventory(
        entries=tuple(
            FileEntry(f"src/{index}-" + "x" * 400 + ".py", 20, FileKind.FILE)
            for index in range(100)
        )
    )

    selected = session.planning_input("Update the application", inventory)

    assert len(selected) <= policy.max_planning_chars
    assert session.metrics[0].compacted_items > 0


def test_editing_context_summarizes_old_actions_and_bounds_recent_evidence() -> None:
    session = ContextSession(
        ContextPolicy(
            recent_observations=2,
            max_observation_chars=1_000,
            max_observation_chars_total=2_000,
        )
    )
    observations = tuple(
        ToolObservation(
            call_id=f"call-{index}",
            tool_name="read_file",
            ok=True,
            output=f"start-{index}-" + "x" * 1_500 + f"-end-{index}",
            truncated=False,
        )
        for index in range(5)
    )

    payload = json.loads(session.editing_input("Update greeting", _plan(), observations, None))

    history = payload["action_history"]
    assert [item["call_id"] for item in history["completed_action_summaries"]] == [
        "call-0",
        "call-1",
        "call-2",
    ]
    assert [item["call_id"] for item in history["recent_evidence"]] == [
        "call-3",
        "call-4",
    ]
    assert all(len(item["output"]) == 1_000 for item in history["recent_evidence"])
    assert all(item["truncated"] for item in history["recent_evidence"])
    assert "start-4" in history["recent_evidence"][1]["output"]
    assert "end-4" in history["recent_evidence"][1]["output"]
    assert session.metrics[0].compacted_items == 5


def test_reflection_context_keeps_diff_changes_and_command_failure_tail() -> None:
    session = ContextSession(ContextPolicy(max_command_output_chars=1_000))
    patch = """diff --git a/app.py b/app.py
--- a/app.py
+++ b/app.py
@@ -1,2 +1,2 @@
 unchanged context
-old value
+new value
 trailing context
"""
    stdout = "setup output\n" + "x" * 1_500 + "\nFAILED test_greeting"

    payload = json.loads(
        session.reflection_input(
            "Update greeting",
            _plan(),
            patch,
            status="failed",
            check_kind="test",
            message="Tests failed.",
            stdout=stdout,
            stderr="",
        )
    )

    assert "-old value" in payload["patch"]
    assert "+new value" in payload["patch"]
    assert "unchanged context" not in payload["patch"]
    assert "FAILED test_greeting" in payload["stdout"]
    assert len(payload["stdout"]) == 1_000
    assert payload["evidence_compaction"] == {
        "patch": True,
        "stdout": True,
        "stderr": False,
    }
    assert session.metrics[0].operation == "reflect_on_failure"
    assert session.metrics[0].selected_chars < session.metrics[0].original_chars


def test_edit_request_matches_the_controller_tool_history_limit() -> None:
    observation = ToolObservation(
        call_id="call",
        tool_name="read_file",
        ok=True,
        output="evidence",
        truncated=False,
    )

    request = EditRequest(
        task="Update greeting",
        plan=_plan(),
        observations=(observation,) * 100,
    )

    assert len(request.observations) == 100
    with pytest.raises(ValidationError, match="at most 100 items"):
        EditRequest(
            task="Update greeting",
            plan=_plan(),
            observations=(observation,) * 101,
        )


def test_maximum_history_is_compacted_below_the_model_input_boundary() -> None:
    observation = ToolObservation(
        call_id="call",
        tool_name="read_file",
        ok=True,
        output="x" * 50_000,
        truncated=False,
    )
    session = ContextSession()

    selected = session.editing_input(
        "Update greeting",
        _plan(),
        (observation,) * 100,
        None,
    )

    assert len(selected) < 200_000
    assert session.metrics[0].original_chars > 5_000_000

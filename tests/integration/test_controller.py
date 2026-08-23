"""Deterministic vertical-slice and retry tests for the run controller."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from pydantic import BaseModel

from repopilot.application import PersistingRunApplication
from repopilot.artifacts import FilesystemArtifactWriter
from repopilot.controller import RunController
from repopilot.errors import WorkspaceSafetyError
from repopilot.model_models import ModelRequest, ModelResponse, ModelUsage
from repopilot.models import RunWorkspace
from repopilot.repository import RepositoryService
from repopilot.run_logging import InMemoryRunLogger
from repopilot.run_models import (
    LocalRepositorySource,
    RunBudgets,
    RunRequest,
    TerminationReason,
    TransitionRecord,
)
from repopilot.scripted_model import ScriptedModel, ScriptedResponse
from repopilot.state_machine import RunEvent, RunPhase
from repopilot.tool_models import RunCommandRequest
from repopilot.verification import VerificationStatus
from repopilot.workspace import WorkspaceManager

_PATCH = """diff --git a/greeting.py b/greeting.py
--- a/greeting.py
+++ b/greeting.py
@@ -1,2 +1,2 @@
 def greeting() -> str:
-    return "hello world"
+    return "hello RepoPilot"
"""
_WRONG_PATCH = _PATCH.replace('return "hello RepoPilot"', 'return "hello team"')
_CORRECTION_PATCH = """diff --git a/greeting.py b/greeting.py
--- a/greeting.py
+++ b/greeting.py
@@ -1,2 +1,2 @@
 def greeting() -> str:
-    return "hello team"
+    return "hello RepoPilot"
"""
_IGNORED_PATCH = """diff --git a/scratch.tmp b/scratch.tmp
new file mode 100644
--- /dev/null
+++ b/scratch.tmp
@@ -0,0 +1 @@
+ignored
"""


class _CleanupFailingWorkspaceManager(WorkspaceManager):
    def cleanup(self, workspace: RunWorkspace) -> None:
        raise WorkspaceSafetyError("simulated cleanup failure")


class _UnexpectedCleanupWorkspaceManager(WorkspaceManager):
    def cleanup(self, workspace: RunWorkspace) -> None:
        raise RuntimeError("sensitive cleanup detail")


class _FailingRunLogger:
    def __init__(self, fail_on: RunEvent) -> None:
        self._fail_on = fail_on

    def record_transition(self, record: TransitionRecord) -> None:
        if record.event is self._fail_on:
            raise RuntimeError("sensitive logger detail")


class _InterruptingModel:
    def generate[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_type: type[OutputT],
    ) -> ModelResponse[OutputT]:
        raise KeyboardInterrupt


def _create_source(root: Path) -> Path:
    source = root / "source"
    source.mkdir()
    subprocess.run(["git", "init", "--quiet", str(source)], check=True, capture_output=True)
    (source / "greeting.py").write_text(
        'def greeting() -> str:\n    return "hello world"\n',
        encoding="utf-8",
    )
    (source / "test_greeting.py").write_text(
        "from greeting import greeting\n\n\ndef test_greeting() -> None:\n"
        '    assert greeting() == "hello RepoPilot"\n',
        encoding="utf-8",
    )
    (source / ".gitignore").write_text("*.tmp\n", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(source), "add", ".gitignore", "greeting.py", "test_greeting.py"],
        check=True,
        capture_output=True,
    )
    return source


def _plan() -> dict[str, object]:
    return {
        "summary": "Update the greeting and run its test.",
        "steps": [
            {
                "id": "update_greeting",
                "objective": "Change the greeting returned by greeting.py.",
                "files": ["greeting.py"],
                "verification": ["pytest -q"],
            }
        ],
        "assumptions": [],
    }


def _read_call() -> dict[str, object]:
    return {
        "tool_call": {
            "call_id": "read-1",
            "tool_name": "read_file",
            "arguments": {"path": "greeting.py"},
        }
    }


def _patch_call(patch: str = _PATCH, call_id: str = "patch-1") -> dict[str, object]:
    return {
        "tool_call": {
            "call_id": call_id,
            "tool_name": "write_patch",
            "arguments": {"patch": patch},
        }
    }


def _request(source: Path, *, budgets: RunBudgets | None = None) -> RunRequest:
    return RunRequest(
        source=LocalRepositorySource(path=source),
        task="Change the greeting to hello RepoPilot.",
        verification=RunCommandRequest(argv=("pytest", "-q")),
        budgets=budgets or RunBudgets(),
        run_id="controller-test",
    )


def test_controller_completes_real_repository_vertical_slice(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    managed = tmp_path / "managed"
    logger = InMemoryRunLogger()
    model = ScriptedModel(
        [
            ScriptedResponse(
                _plan(),
                ModelUsage(input_tokens=10, output_tokens=5, total_tokens=15),
            ),
            ScriptedResponse(
                _read_call(),
                ModelUsage(input_tokens=20, output_tokens=10, total_tokens=30),
            ),
            ScriptedResponse(
                _patch_call(),
                ModelUsage(input_tokens=30, output_tokens=15, total_tokens=45),
            ),
        ]
    )
    controller = RunController(
        WorkspaceManager(managed),
        RepositoryService(),
        model,
        logger=logger,
    )

    application = PersistingRunApplication(
        controller,
        FilesystemArtifactWriter(managed),
    )

    result = application.run(_request(source))

    assert result.phase is RunPhase.COMPLETE
    assert result.termination_reason is TerminationReason.SUCCESS
    assert result.failure_message is None
    assert '+    return "hello RepoPilot"' in result.patch
    assert result.verifications[-1].status is VerificationStatus.PASSED
    assert result.verifications[-1].exit_code == 0
    assert result.counters.model_calls == 3
    assert result.counters.tool_calls == 4
    assert result.counters.iterations == 1
    assert result.usage is not None
    assert result.usage.input_tokens == 60
    assert result.usage.output_tokens == 30
    assert [metric.operation for metric in result.context_metrics] == [
        "create_plan",
        "select_tool",
        "select_tool",
    ]
    assert [record.event for record in result.transitions] == [
        RunEvent.WORKSPACE_READY,
        RunEvent.INVENTORY_READY,
        RunEvent.PLAN_READY,
        RunEvent.TOOL_COMPLETED,
        RunEvent.PATCH_APPLIED,
        RunEvent.VERIFICATION_PASSED,
    ]
    assert logger.records == list(result.transitions)
    assert not (managed / "workspaces" / "controller-test").exists()
    artifact_path = managed / "runs" / "controller-test"
    assert result.artifact_path == artifact_path
    assert (artifact_path / "report.md").is_file()
    assert (artifact_path / "patch.diff").read_text(encoding="utf-8") == result.patch
    assert (artifact_path / "events.jsonl").is_file()
    assert (artifact_path / "commands" / "001-test.log").is_file()
    assert "hello world" in (source / "greeting.py").read_text(encoding="utf-8")
    assert "## Context Selection" in (artifact_path / "report.md").read_text(encoding="utf-8")

    read_observation = model.invocations[2].request.input
    assert "hello world" in read_observation


def test_controller_stops_before_exceeding_model_budget(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    managed = tmp_path / "managed"
    model = ScriptedModel([_plan()])
    controller = RunController(WorkspaceManager(managed), RepositoryService(), model)

    result = controller.run(_request(source, budgets=RunBudgets(max_model_calls=1)))

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.BUDGET_EXHAUSTED
    assert result.failure_message is not None
    assert "model_calls" in result.failure_message
    assert result.counters.model_calls == 1
    assert len(model.invocations) == 1
    assert result.transitions[-1].event is RunEvent.FAILED
    assert not (managed / "workspaces" / "controller-test").exists()


def test_controller_preserves_diff_when_verification_fails(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    model = ScriptedModel([_plan(), _patch_call()])
    request = _request(source).model_copy(
        update={"verification": RunCommandRequest(argv=("pytest", "missing.py"))}
    )
    controller = RunController(
        WorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
    )

    request = request.model_copy(update={"budgets": RunBudgets(max_iterations=1)})
    result = controller.run(request)

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.BUDGET_EXHAUSTED
    assert result.patch
    assert result.verifications[-1].status is VerificationStatus.FAILED
    assert result.verifications[-1].exit_code != 0


def test_controller_stops_on_rejected_model_patch(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    invalid_patch = _PATCH.replace("hello world", "content that is not present")
    model = ScriptedModel([_plan(), _patch_call(invalid_patch)])
    controller = RunController(
        WorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
    )

    result = controller.run(_request(source))

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.EDIT_FAILED
    assert result.failure_message is not None
    assert "patch_rejected" in result.failure_message
    assert result.counters.tool_calls == 1
    assert result.transitions[-1].event is RunEvent.FAILED
    assert "hello world" in (source / "greeting.py").read_text(encoding="utf-8")


def test_controller_does_not_complete_when_cleanup_fails(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    model = ScriptedModel([_plan(), _patch_call()])
    controller = RunController(
        _CleanupFailingWorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
    )

    result = controller.run(_request(source))

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.CLEANUP_FAILED
    assert result.transitions[-1].event is RunEvent.FAILED
    assert RunEvent.VERIFICATION_PASSED not in [record.event for record in result.transitions]


def test_controller_reflects_and_fixes_broken_repository(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    model = ScriptedModel(
        [
            _plan(),
            _read_call(),
            _patch_call(_WRONG_PATCH, "patch-wrong"),
            {
                "diagnosis": (
                    "The implementation returns hello team, but the test expects hello RepoPilot."
                ),
                "next_step": "Correct the return value in greeting.py.",
            },
            _patch_call(_CORRECTION_PATCH, "patch-corrected"),
        ]
    )
    controller = RunController(
        WorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
    )

    result = controller.run(_request(source))

    assert result.phase is RunPhase.COMPLETE
    assert result.termination_reason is TerminationReason.SUCCESS
    assert [item.status for item in result.verifications] == [
        VerificationStatus.FAILED,
        VerificationStatus.PASSED,
    ]
    assert len(result.reflections) == 1
    assert "expects hello RepoPilot" in result.reflections[0].diagnosis
    assert result.counters.iterations == 2
    assert result.counters.model_calls == 5
    assert result.counters.tool_calls == 7
    assert RunEvent.VERIFICATION_FAILED in [record.event for record in result.transitions]
    assert RunEvent.REFLECTION_READY in [record.event for record in result.transitions]
    assert 'return "hello RepoPilot"' in result.patch
    assert "hello world" in (source / "greeting.py").read_text(encoding="utf-8")

    reflection_input = model.invocations[3].request.input
    correction_input = model.invocations[4].request.input
    assert "hello team" in reflection_input
    assert "Correct the return value" in correction_input


def test_controller_stops_when_failed_retry_has_same_visible_diff(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    model = ScriptedModel(
        [
            _plan(),
            _patch_call(_WRONG_PATCH, "patch-wrong"),
            {
                "diagnosis": "The greeting is still incorrect.",
                "next_step": "Correct greeting.py.",
            },
            _patch_call(_IGNORED_PATCH, "patch-ignored"),
        ]
    )
    controller = RunController(
        WorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
    )

    result = controller.run(_request(source))

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.NO_PROGRESS
    assert result.failure_message is not None
    assert "same repository diff" in result.failure_message
    assert len(result.verifications) == 2
    assert result.counters.iterations == 2
    assert result.transitions[-1].event is RunEvent.FAILED


def test_controller_does_not_reflect_on_verification_policy_error(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    model = ScriptedModel([_plan(), _patch_call()])
    request = _request(source).model_copy(
        update={"verification": RunCommandRequest(argv=("sh", "-c", "pytest"))}
    )
    controller = RunController(
        WorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
    )

    result = controller.run(request)

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.VERIFICATION_FAILED
    assert result.verifications[-1].status is VerificationStatus.ERROR
    assert not result.verifications[-1].retryable
    assert result.reflections == ()
    assert len(model.invocations) == 2


def test_controller_sanitizes_unexpected_model_failure(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    model = ScriptedModel([RuntimeError("sensitive provider detail")])
    controller = RunController(
        WorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
    )

    result = controller.run(_request(source))

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.INTERNAL_ERROR
    assert result.failure_message == "Unexpected RuntimeError during plan."
    assert "sensitive provider detail" not in result.failure_message
    assert result.transitions[-1].event is RunEvent.FAILED


def test_controller_fails_atomically_when_success_logging_fails(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    model = ScriptedModel([_plan(), _patch_call()])
    controller = RunController(
        WorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
        logger=_FailingRunLogger(RunEvent.VERIFICATION_PASSED),
    )

    result = controller.run(_request(source))

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.LOGGING_FAILED
    assert result.failure_message == "Transition logger raised RuntimeError."
    assert result.transitions[-1].event is RunEvent.FAILED
    assert RunEvent.VERIFICATION_PASSED not in [record.event for record in result.transitions]


def test_controller_survives_logger_failure_on_failed_transition(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    invalid_patch = _PATCH.replace("hello world", "content that is not present")
    model = ScriptedModel([_plan(), _patch_call(invalid_patch)])
    controller = RunController(
        WorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
        logger=_FailingRunLogger(RunEvent.FAILED),
    )

    result = controller.run(_request(source))

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.EDIT_FAILED
    assert result.failure_message is not None
    assert "patch_rejected" in result.failure_message
    assert "Transition logger raised RuntimeError" in result.failure_message
    assert result.transitions[-1].event is RunEvent.FAILED


def test_controller_sanitizes_unexpected_cleanup_failure(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    model = ScriptedModel([_plan(), _patch_call()])
    controller = RunController(
        _UnexpectedCleanupWorkspaceManager(tmp_path / "managed"),
        RepositoryService(),
        model,
    )

    result = controller.run(_request(source))

    assert result.phase is RunPhase.FAILED
    assert result.termination_reason is TerminationReason.CLEANUP_FAILED
    assert result.failure_message is not None
    assert "Unexpected RuntimeError during workspace cleanup" in result.failure_message
    assert "sensitive cleanup detail" not in result.failure_message


def test_controller_cleans_workspace_before_propagating_interrupt(tmp_path: Path) -> None:
    source = _create_source(tmp_path)
    managed = tmp_path / "managed"
    controller = RunController(
        WorkspaceManager(managed),
        RepositoryService(),
        _InterruptingModel(),
    )

    with pytest.raises(KeyboardInterrupt):
        controller.run(_request(source))

    assert not (managed / "workspaces" / "controller-test").exists()

"""Tests for per-run workspace allocation and cleanup."""

from dataclasses import replace
from pathlib import Path

import pytest

from repopilot.errors import WorkspaceExistsError, WorkspaceSafetyError
from repopilot.workspace import WorkspaceManager


def test_creates_unique_workspace_and_artifact_directories(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)

    first = manager.create()
    second = manager.create()

    assert first.run_id != second.run_id
    assert first.root_path.is_dir()
    assert first.artifact_path.is_dir()
    assert second.root_path.is_dir()


def test_rejects_duplicate_run_id_without_disturbing_existing_run(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    original = manager.create("run-123")
    marker = original.root_path / "marker"
    marker.write_text("keep\n")

    with pytest.raises(WorkspaceExistsError):
        manager.create("run-123")

    assert marker.read_text() == "keep\n"


def test_cleanup_removes_workspace_but_preserves_artifacts(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    workspace = manager.create("cleanup-test")
    (workspace.root_path / "temporary.txt").write_text("temporary\n")
    report = workspace.artifact_path / "report.md"
    report.write_text("durable\n")

    manager.cleanup(workspace)

    assert not workspace.root_path.exists()
    assert report.read_text() == "durable\n"


def test_context_manager_cleans_workspace_after_failure(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path)
    allocated_path: Path | None = None

    with (
        pytest.raises(RuntimeError, match="boom"),
        manager.allocated("failed-run") as workspace,
    ):
        allocated_path = workspace.root_path
        raise RuntimeError("boom")

    assert allocated_path is not None
    assert not allocated_path.exists()
    assert (tmp_path / "runs" / "failed-run").is_dir()


def test_cleanup_rejects_forged_workspace_path(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "managed")
    workspace = manager.create("safe-run")
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    forged = replace(workspace, root_path=unrelated)

    with pytest.raises(WorkspaceSafetyError, match="outside its run allocation"):
        manager.cleanup(forged)

    assert unrelated.is_dir()


def test_cleanup_rejects_workspace_root_replaced_by_symlink(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "managed")
    workspace = manager.create("symlink-run")
    workspace.root_path.rmdir()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    workspace.root_path.symlink_to(unrelated, target_is_directory=True)

    with pytest.raises(WorkspaceSafetyError, match="root that is a symlink"):
        manager.cleanup(workspace)

    assert unrelated.is_dir()


def test_cleanup_rejects_workspace_root_replaced_by_file(tmp_path: Path) -> None:
    manager = WorkspaceManager(tmp_path / "managed")
    workspace = manager.create("file-run")
    workspace.root_path.rmdir()
    workspace.root_path.write_text("replacement\n")

    with pytest.raises(WorkspaceSafetyError, match="not a directory"):
        manager.cleanup(workspace)

    assert workspace.root_path.read_text() == "replacement\n"


@pytest.mark.parametrize("run_id", ["../escape", "contains spaces", "", "a" * 65])
def test_rejects_unsafe_run_id(tmp_path: Path, run_id: str) -> None:
    with pytest.raises(WorkspaceSafetyError):
        WorkspaceManager(tmp_path).create(run_id)

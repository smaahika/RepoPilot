"""Integration tests for repository preparation, inventory, and diff behavior."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repopilot.errors import (
    GitCommandError,
    GitOutputLimitError,
    InvalidRepositoryError,
    InventoryLimitError,
)
from repopilot.git_client import SubprocessGitClient
from repopilot.models import FileKind
from repopilot.repository import RepositoryService
from repopilot.workspace import WorkspaceManager


def _git(repository: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repository), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def _make_repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(path)],
        check=True,
        capture_output=True,
    )
    return path


def _commit(repository: Path, message: str = "Test: Create fixture") -> None:
    _git(
        repository,
        "-c",
        "user.name=RepoPilot Tests",
        "-c",
        "user.email=test@example.com",
        "commit",
        "--quiet",
        "-m",
        message,
    )


def test_local_copy_preserves_source_and_treats_dirty_state_as_baseline(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    tracked = source / "tracked.txt"
    tracked.write_text("committed\n")
    _git(source, "add", "tracked.txt")
    tracked.write_text("user change\n")
    (source / "untracked.txt").write_text("also user state\n")
    source_index_before = (source / ".git" / "index").read_bytes()
    workspace = WorkspaceManager(tmp_path / "managed").create("local-copy")

    service = RepositoryService()
    checkout = service.prepare_local(source, workspace)

    assert service.diff(checkout) == ""
    assert (checkout.path / "tracked.txt").read_text() == "user change\n"
    assert (checkout.path / "untracked.txt").read_text() == "also user state\n"

    (checkout.path / "tracked.txt").write_text("RepoPilot change\n")

    assert tracked.read_text() == "user change\n"
    assert (source / ".git" / "index").read_bytes() == source_index_before
    assert "RepoPilot change" in service.diff(checkout)


def test_diff_includes_modified_new_and_deleted_files(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    (source / "modified.txt").write_text("before\n")
    (source / "deleted.txt").write_text("delete me\n")
    _git(source, "add", "modified.txt", "deleted.txt")
    workspace = WorkspaceManager(tmp_path / "managed").create("diff-test")
    service = RepositoryService()
    checkout = service.prepare_local(source, workspace)

    (checkout.path / "modified.txt").write_text("after\n")
    (checkout.path / "new.txt").write_text("brand new\n")
    (checkout.path / "deleted.txt").unlink()

    diff = service.diff(checkout)

    assert "a/modified.txt" in diff
    assert "+after" in diff
    assert "a/new.txt" in diff
    assert "+brand new" in diff
    assert "a/deleted.txt" in diff
    assert "-delete me" in diff


def test_repeated_diff_does_not_retain_deleted_untracked_file(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    workspace = WorkspaceManager(tmp_path / "managed").create("repeated-diff")
    service = RepositoryService()
    checkout = service.prepare_local(source, workspace)
    generated = checkout.path / "generated.txt"
    generated.write_text("temporary\n")

    assert "generated.txt" in service.diff(checkout)

    generated.unlink()

    assert service.diff(checkout) == ""


def test_inventory_is_sorted_ignore_aware_and_describes_symlinks(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    (source / ".gitignore").write_text("*.log\n")
    (source / "zeta.py").write_text("z = 1\n")
    (source / "ignored.log").write_text("ignored\n")
    (source / "tracked.log").write_text("tracked despite rule\n")
    outside = tmp_path / "outside.txt"
    outside.write_text("outside\n")
    (source / "external-link").symlink_to(outside)
    _git(source, "add", ".gitignore", "zeta.py", "external-link")
    _git(source, "add", "--force", "tracked.log")
    workspace = WorkspaceManager(tmp_path / "managed").create("inventory-test")
    service = RepositoryService()
    checkout = service.prepare_local(source, workspace)

    inventory = service.inventory(checkout)
    paths = [entry.path for entry in inventory.entries]

    assert paths == sorted(paths)
    assert "ignored.log" not in paths
    assert "tracked.log" in paths
    link = next(entry for entry in inventory.entries if entry.path == "external-link")
    assert link.kind is FileKind.SYMLINK


def test_inventory_enforces_entry_limit(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    for name in ("one.txt", "two.txt", "three.txt"):
        (source / name).write_text(name)
    workspace = WorkspaceManager(tmp_path / "managed").create("limit-test")
    service = RepositoryService()
    checkout = service.prepare_local(source, workspace)

    with pytest.raises(InventoryLimitError) as exc_info:
        service.inventory(checkout, max_entries=2)

    assert exc_info.value.limit == 2


def test_preparation_enforces_system_inventory_limit(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    for name in ("one.txt", "two.txt", "three.txt"):
        (source / name).write_text(name)
    workspace = WorkspaceManager(tmp_path / "managed").create("preparation-limit")
    service = RepositoryService(max_inventory_entries=2)

    with pytest.raises(InventoryLimitError) as exc_info:
        service.prepare_local(source, workspace)

    assert exc_info.value.limit == 2
    assert not workspace.baseline_git_path.exists()


def test_inventory_cannot_raise_system_limit(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    workspace = WorkspaceManager(tmp_path / "managed").create("system-limit")
    service = RepositoryService(max_inventory_entries=2)
    checkout = service.prepare_local(source, workspace)

    with pytest.raises(ValueError, match="cannot exceed"):
        service.inventory(checkout, max_entries=3)


def test_empty_repository_has_empty_inventory_and_diff(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    workspace = WorkspaceManager(tmp_path / "managed").create("empty-test")
    service = RepositoryService()

    checkout = service.prepare_local(source, workspace)

    assert service.inventory(checkout).count == 0
    assert service.diff(checkout) == ""


class _LocalCloneGitClient(SubprocessGitClient):
    def __init__(self, local_source: Path) -> None:
        super().__init__()
        self._local_source = local_source

    def clone(self, source: str, destination: Path) -> None:
        super().clone(str(self._local_source), destination)


def test_clones_public_repository_through_injected_adapter(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    (source / "README.md").write_text("fixture\n")
    _git(source, "add", "README.md")
    _commit(source)
    workspace = WorkspaceManager(tmp_path / "managed").create("clone-test")
    service = RepositoryService(git=_LocalCloneGitClient(source))

    checkout = service.prepare_public("https://example.com/repository.git", workspace)

    assert (checkout.path / "README.md").read_text() == "fixture\n"
    assert service.diff(checkout) == ""


def test_rejects_non_repository_source(tmp_path: Path) -> None:
    source = tmp_path / "not-a-repository"
    source.mkdir()
    workspace = WorkspaceManager(tmp_path / "managed").create("invalid-test")

    with pytest.raises(InvalidRepositoryError, match="standard Git working trees"):
        RepositoryService().prepare_local(source, workspace)


def test_rejects_workspace_nested_inside_source_repository(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    workspace = WorkspaceManager(source / ".repopilot").create("nested-workspace")

    with pytest.raises(InvalidRepositoryError, match="must not be created inside"):
        RepositoryService().prepare_local(source, workspace)

    assert not workspace.repository_path.exists()


@pytest.mark.parametrize(
    "source",
    [
        "git@github.com:owner/repository.git",
        "file:///private/repository",
        "ext::command argument",
        "http://example.com/repository.git",
        "https://token@example.com/repository.git",
    ],
)
def test_rejects_unsafe_public_repository_source(tmp_path: Path, source: str) -> None:
    workspace = WorkspaceManager(tmp_path / "managed").create()

    with pytest.raises(InvalidRepositoryError):
        RepositoryService().prepare_public(source, workspace)

    assert not workspace.repository_path.exists()


def test_deleted_tracked_directory_is_valid_initial_state(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    nested = source / "nested"
    nested.mkdir()
    (nested / "tracked.txt").write_text("tracked\n")
    _git(source, "add", "nested/tracked.txt")
    (nested / "tracked.txt").unlink()
    nested.rmdir()
    workspace = WorkspaceManager(tmp_path / "managed").create("deleted-directory")
    service = RepositoryService()

    checkout = service.prepare_local(source, workspace)

    assert service.inventory(checkout).count == 0
    assert service.diff(checkout) == ""


class _FailingCloneGitClient(SubprocessGitClient):
    def clone(self, source: str, destination: Path) -> None:
        destination.mkdir()
        (destination / "partial").write_text("partial clone\n")
        raise GitCommandError("clone repository", 128, "simulated failure")


def test_clone_failure_is_typed_and_partial_destination_is_removed(tmp_path: Path) -> None:
    workspace = WorkspaceManager(tmp_path / "managed").create("failed-clone")
    service = RepositoryService(git=_FailingCloneGitClient())

    with pytest.raises(GitCommandError, match="simulated failure"):
        service.prepare_public("https://example.invalid/repository.git", workspace)

    assert not workspace.repository_path.exists()


def test_git_adapter_enforces_output_limit(tmp_path: Path) -> None:
    source = _make_repository(tmp_path / "source")
    (source / "a-file-with-a-long-name.txt").write_text("content\n")
    client = SubprocessGitClient(output_limit_bytes=8)

    with pytest.raises(GitOutputLimitError):
        client.list_files(source)

"""Tests for repository path containment."""

from pathlib import Path

import pytest

from repopilot.errors import PathPolicyError
from repopilot.path_policy import resolve_workspace_entry, resolve_workspace_path


def test_resolves_existing_path_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    target = workspace / "src" / "module.py"
    target.parent.mkdir(parents=True)
    target.write_text("value = 1\n")

    assert resolve_workspace_path(workspace, "src/module.py") == target


@pytest.mark.parametrize("unsafe_path", ["../secret", "src/../../secret"])
def test_rejects_parent_traversal(tmp_path: Path, unsafe_path: str) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(PathPolicyError, match="parent traversal"):
        resolve_workspace_path(workspace, unsafe_path, must_exist=False)


def test_rejects_absolute_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    with pytest.raises(PathPolicyError, match="absolute paths"):
        resolve_workspace_path(workspace, tmp_path / "elsewhere", must_exist=False)


def test_rejects_symlink_escape(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    (workspace / "link").symlink_to(outside)

    with pytest.raises(PathPolicyError, match="escapes the workspace"):
        resolve_workspace_path(workspace, "link")


def test_inventory_can_describe_final_symlink_without_following_it(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    link = workspace / "link"
    link.symlink_to(outside)

    assert resolve_workspace_entry(workspace, "link") == link


def test_inventory_rejects_escape_through_parent_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("secret\n")
    (workspace / "linked-directory").symlink_to(outside, target_is_directory=True)

    with pytest.raises(PathPolicyError, match="parent escapes"):
        resolve_workspace_entry(workspace, "linked-directory/secret.txt")

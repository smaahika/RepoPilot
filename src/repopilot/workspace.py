"""Creation and cleanup of disposable per-run workspaces."""

from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from repopilot.errors import WorkspaceExistsError, WorkspaceSafetyError
from repopilot.models import RunWorkspace

_RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")


class WorkspaceManager:
    """Allocate and safely remove workspaces beneath one trusted run root."""

    def __init__(self, base_path: Path) -> None:
        self._base_path = base_path.resolve()
        self._workspace_parent = self._base_path / "workspaces"
        self._artifact_parent = self._base_path / "runs"

    def create(self, run_id: str | None = None) -> RunWorkspace:
        """Atomically reserve unique workspace and artifact directories."""
        selected_run_id = uuid4().hex if run_id is None else run_id
        if not _RUN_ID_PATTERN.fullmatch(selected_run_id):
            raise WorkspaceSafetyError(
                "Run IDs must be 1-64 characters using letters, digits, underscores, or hyphens."
            )

        self._workspace_parent.mkdir(parents=True, exist_ok=True)
        self._artifact_parent.mkdir(parents=True, exist_ok=True)
        root_path = self._workspace_parent / selected_run_id
        artifact_path = self._artifact_parent / selected_run_id
        root_created = False

        try:
            root_path.mkdir()
            root_created = True
            artifact_path.mkdir()
        except FileExistsError as exc:
            if root_created:
                root_path.rmdir()
            raise WorkspaceExistsError(selected_run_id) from exc
        except OSError:
            if root_created:
                root_path.rmdir()
            raise

        return RunWorkspace(
            run_id=selected_run_id,
            root_path=root_path,
            artifact_path=artifact_path,
        )

    def cleanup(self, workspace: RunWorkspace) -> None:
        """Remove only the disposable workspace, preserving durable artifacts."""
        expected = self._workspace_parent / workspace.run_id
        if workspace.root_path != expected:
            raise WorkspaceSafetyError("Refusing to clean a workspace outside its run allocation.")
        if workspace.root_path.is_symlink():
            raise WorkspaceSafetyError("Refusing to clean a workspace root that is a symlink.")
        if not workspace.root_path.exists():
            return
        if not workspace.root_path.is_dir():
            raise WorkspaceSafetyError(
                "Refusing to clean a workspace root that is not a directory."
            )

        resolved = workspace.root_path.resolve(strict=True)
        if resolved.parent != self._workspace_parent.resolve(strict=True):
            raise WorkspaceSafetyError(
                "Refusing to clean a workspace that resolves outside its root."
            )
        shutil.rmtree(resolved)

    @contextmanager
    def allocated(self, run_id: str | None = None) -> Iterator[RunWorkspace]:
        """Yield a workspace and guarantee cleanup of its disposable portion."""
        workspace = self.create(run_id)
        try:
            yield workspace
        finally:
            self.cleanup(workspace)

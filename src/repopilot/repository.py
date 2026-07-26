"""Safe preparation, inventory, and diff operations for Git repositories."""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import urlsplit

from repopilot.errors import (
    GitError,
    InvalidRepositoryError,
    InventoryLimitError,
    PathNotFoundError,
    RepositoryCopyError,
)
from repopilot.git_client import GitClient, SubprocessGitClient
from repopilot.models import (
    FileEntry,
    FileKind,
    RepositoryCheckout,
    RepositoryInventory,
    RunWorkspace,
)
from repopilot.path_policy import resolve_workspace_entry


class RepositoryService:
    """Prepare repositories without mutating their source and expose bounded inspection."""

    def __init__(
        self,
        git: GitClient | None = None,
        *,
        max_inventory_entries: int = 5_000,
    ) -> None:
        if max_inventory_entries <= 0:
            raise ValueError("max_inventory_entries must be positive")
        self._git = SubprocessGitClient() if git is None else git
        self._max_inventory_entries = max_inventory_entries

    def prepare_local(self, source: Path, workspace: RunWorkspace) -> RepositoryCheckout:
        """Copy a standard local Git working tree and capture its current contents."""
        try:
            resolved_source = source.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise InvalidRepositoryError(source, "source directory does not exist") from exc
        self._validate_repository_marker(resolved_source)
        self._ensure_destination_available(workspace)
        if workspace.root_path.resolve().is_relative_to(resolved_source):
            raise InvalidRepositoryError(
                source,
                "workspace must not be created inside the source repository",
            )

        try:
            shutil.copytree(resolved_source, workspace.repository_path, symlinks=True)
        except (OSError, shutil.Error) as exc:
            self._remove_partial_destination(workspace.repository_path)
            raise RepositoryCopyError(f"Could not copy repository {str(source)!r}: {exc}") from exc
        return self._capture_checkout(workspace)

    def prepare_public(self, source: str, workspace: RunWorkspace) -> RepositoryCheckout:
        """Clone a repository through the injected Git adapter and capture its baseline."""
        self._validate_public_source(source)
        self._ensure_destination_available(workspace)

        try:
            self._git.clone(source, workspace.repository_path)
            self._validate_repository_marker(workspace.repository_path)
            return self._capture_checkout(workspace)
        except (GitError, InvalidRepositoryError):
            self._remove_partial_destination(workspace.repository_path)
            raise

    def inventory(
        self,
        checkout: RepositoryCheckout,
        *,
        max_entries: int | None = None,
    ) -> RepositoryInventory:
        """Return stable metadata for tracked and non-ignored untracked files."""
        limit = self._inventory_limit(max_entries)
        paths = self._visible_paths(checkout.path, limit=limit)

        entries: list[FileEntry] = []
        for path in paths:
            entry_path = resolve_workspace_entry(checkout.path, path)
            stat = entry_path.lstat()
            if entry_path.is_symlink():
                kind = FileKind.SYMLINK
            elif entry_path.is_file():
                kind = FileKind.FILE
            else:
                kind = FileKind.OTHER
            entries.append(FileEntry(path=path, size_bytes=stat.st_size, kind=kind))
        return RepositoryInventory(entries=tuple(entries))

    def diff(self, checkout: RepositoryCheckout) -> str:
        """Return changes made after preparation, including new non-ignored files."""
        current_paths = self._visible_paths(
            checkout.path,
            limit=self._max_inventory_entries,
        )
        return self._git.diff(
            checkout.path,
            checkout.workspace.baseline_git_path,
            checkout.baseline_tree,
            current_paths,
        )

    def _capture_checkout(self, workspace: RunWorkspace) -> RepositoryCheckout:
        paths = self._visible_paths(
            workspace.repository_path,
            limit=self._max_inventory_entries,
        )
        baseline_tree = self._git.capture_baseline(
            workspace.repository_path,
            workspace.baseline_git_path,
            paths,
        )
        return RepositoryCheckout(workspace=workspace, baseline_tree=baseline_tree)

    def _visible_paths(self, repository: Path, *, limit: int) -> tuple[str, ...]:
        validated: set[str] = set()
        for path in self._git.list_files(repository):
            try:
                resolve_workspace_entry(repository, path)
            except PathNotFoundError:
                continue
            validated.add(path)
            if len(validated) > limit:
                raise InventoryLimitError(limit)
        return tuple(sorted(validated))

    def _inventory_limit(self, requested: int | None) -> int:
        if requested is None:
            return self._max_inventory_entries
        if requested <= 0:
            raise ValueError("max_entries must be positive")
        if requested > self._max_inventory_entries:
            raise ValueError("max_entries cannot exceed the repository service limit")
        return requested

    @staticmethod
    def _validate_public_source(source: str) -> None:
        if any(character.isspace() or ord(character) < 32 for character in source):
            raise InvalidRepositoryError(source, "repository URL cannot contain whitespace")
        parsed = urlsplit(source)
        if parsed.scheme != "https" or not parsed.hostname:
            raise InvalidRepositoryError(source, "public repositories require an HTTPS URL")
        if parsed.username is not None or parsed.password is not None:
            raise InvalidRepositoryError(source, "credentials are not allowed in repository URLs")

    @staticmethod
    def _validate_repository_marker(repository: Path) -> None:
        marker = repository / ".git"
        if not repository.is_dir():
            raise InvalidRepositoryError(repository, "source is not a directory")
        if not marker.is_dir() or marker.is_symlink():
            raise InvalidRepositoryError(
                repository,
                "only standard Git working trees with a .git directory are supported",
            )

    @staticmethod
    def _ensure_destination_available(workspace: RunWorkspace) -> None:
        if not workspace.root_path.is_dir():
            raise InvalidRepositoryError(workspace.root_path, "workspace does not exist")
        if workspace.repository_path.exists() or workspace.repository_path.is_symlink():
            raise InvalidRepositoryError(
                workspace.repository_path,
                "workspace repository destination is already occupied",
            )

    @staticmethod
    def _remove_partial_destination(destination: Path) -> None:
        if destination.is_symlink() or destination.is_file():
            destination.unlink()
        elif destination.exists():
            shutil.rmtree(destination)

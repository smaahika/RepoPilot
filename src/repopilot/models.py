"""Domain models for disposable workspaces and repository inspection."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


@dataclass(frozen=True, slots=True)
class RunWorkspace:
    """Filesystem locations allocated to one RepoPilot run."""

    run_id: str
    root_path: Path
    artifact_path: Path

    @property
    def repository_path(self) -> Path:
        """Return the location reserved for the disposable repository copy."""
        return self.root_path / "repository"

    @property
    def baseline_git_path(self) -> Path:
        """Return RepoPilot's private Git directory used for diff bookkeeping."""
        return self.root_path / "baseline.git"


@dataclass(frozen=True, slots=True)
class RepositoryCheckout:
    """A prepared repository and the immutable tree representing its initial contents."""

    workspace: RunWorkspace
    baseline_tree: str

    @property
    def path(self) -> Path:
        """Return the disposable repository root."""
        return self.workspace.repository_path


class FileKind(StrEnum):
    """Kinds of entries that can appear in a repository inventory."""

    FILE = "file"
    SYMLINK = "symlink"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class FileEntry:
    """Bounded metadata for one repository-relative path."""

    path: str
    size_bytes: int
    kind: FileKind


@dataclass(frozen=True, slots=True)
class RepositoryInventory:
    """A deterministic inventory of visible repository files."""

    entries: tuple[FileEntry, ...]

    @property
    def count(self) -> int:
        """Return the number of entries in the inventory."""
        return len(self.entries)

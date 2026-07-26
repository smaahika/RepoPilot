"""Path containment policy for repository tools."""

from __future__ import annotations

from pathlib import Path

from repopilot.errors import PathNotFoundError, PathPolicyError


def resolve_workspace_path(
    workspace_root: Path,
    relative_path: str | Path,
    *,
    must_exist: bool = True,
) -> Path:
    """Resolve a contained path, rejecting traversal and symlink escapes."""
    root = workspace_root.resolve(strict=True)
    candidate = Path(relative_path)

    if "\x00" in str(relative_path):
        raise PathPolicyError(relative_path, "NUL bytes are not allowed")
    if candidate.is_absolute():
        raise PathPolicyError(relative_path, "absolute paths are not allowed")
    if ".." in candidate.parts:
        raise PathPolicyError(relative_path, "parent traversal is not allowed")

    try:
        resolved = (root / candidate).resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise PathNotFoundError(relative_path) from exc
    except (OSError, RuntimeError) as exc:
        raise PathPolicyError(relative_path, f"path cannot be resolved: {exc}") from exc

    if not resolved.is_relative_to(root):
        raise PathPolicyError(relative_path, "resolved path escapes the workspace")
    return resolved


def resolve_workspace_entry(workspace_root: Path, relative_path: str | Path) -> Path:
    """Resolve an entry safely without following its final symlink."""
    root = workspace_root.resolve(strict=True)
    candidate = Path(relative_path)

    if "\x00" in str(relative_path):
        raise PathPolicyError(relative_path, "NUL bytes are not allowed")
    if candidate.is_absolute():
        raise PathPolicyError(relative_path, "absolute paths are not allowed")
    if not candidate.parts or ".." in candidate.parts:
        raise PathPolicyError(relative_path, "parent traversal is not allowed")

    try:
        parent = (root / candidate).parent.resolve(strict=False)
    except (OSError, RuntimeError) as exc:
        raise PathPolicyError(relative_path, "parent path cannot be resolved") from exc
    if not parent.is_relative_to(root):
        raise PathPolicyError(relative_path, "resolved parent escapes the workspace")

    entry = parent / candidate.name
    if not entry.exists() and not entry.is_symlink():
        raise PathNotFoundError(relative_path)
    return entry

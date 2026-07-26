"""Read-only Git tools for a prepared checkout."""

from __future__ import annotations

from repopilot.errors import GitError, InventoryLimitError, PathPolicyError
from repopilot.models import RepositoryCheckout
from repopilot.repository import RepositoryService
from repopilot.tool_models import (
    GitDiffData,
    GitDiffRequest,
    ToolErrorCode,
    ToolName,
    ToolResult,
)
from repopilot.tools._results import failed, started_at, succeeded


class GitTools:
    """Expose bounded repository diff generation."""

    def __init__(self, checkout: RepositoryCheckout, repository: RepositoryService) -> None:
        self._checkout = checkout
        self._repository = repository

    def diff(self, request: GitDiffRequest) -> ToolResult[GitDiffData]:
        """Return a diff when it fits the caller's requested byte budget."""
        started = started_at()
        try:
            patch = self._repository.diff(self._checkout)
            patch_bytes = patch.encode("utf-8")
            if len(patch_bytes) > request.max_bytes:
                return failed(
                    ToolName.GIT_DIFF,
                    started,
                    ToolErrorCode.LIMIT_EXCEEDED,
                    f"Repository diff exceeds the {request.max_bytes} byte limit.",
                )
            return succeeded(ToolName.GIT_DIFF, started, GitDiffData(patch=patch))
        except InventoryLimitError as exc:
            return failed(ToolName.GIT_DIFF, started, ToolErrorCode.LIMIT_EXCEEDED, str(exc))
        except PathPolicyError as exc:
            return failed(ToolName.GIT_DIFF, started, ToolErrorCode.POLICY_DENIED, str(exc))
        except GitError as exc:
            return failed(ToolName.GIT_DIFF, started, ToolErrorCode.EXECUTION_ERROR, str(exc))

"""Typed failures raised by RepoPilot's repository boundary."""

from __future__ import annotations

from pathlib import Path


class RepoPilotError(Exception):
    """Base class for expected RepoPilot failures."""


class ConfigurationError(RepoPilotError):
    """Raised when runtime configuration is missing or invalid."""


class ArtifactPersistenceError(RepoPilotError):
    """Raised when a terminal run cannot be persisted safely."""


class ModelError(RepoPilotError):
    """Base class for model-boundary failures."""


class ModelTransportError(ModelError):
    """Raised when a provider request cannot complete."""


class ModelOutputError(ModelError):
    """Raised when a provider returns no valid structured output."""


class ModelScriptExhaustedError(ModelError):
    """Raised when a scripted model receives an unexpected call."""


class ControllerError(RepoPilotError):
    """Base class for deterministic run-controller failures."""


class InvalidTransitionError(ControllerError):
    """Raised when an event is illegal for the current run phase."""


class RunBudgetExceededError(ControllerError):
    """Raised before an operation would exceed a configured run budget."""

    def __init__(self, budget: str, limit: int | float) -> None:
        super().__init__(f"Run exhausted its {budget} budget of {limit}.")
        self.budget = budget
        self.limit = limit


class ControllerToolError(ControllerError):
    """Raised when a validated tool invocation fails."""


class NoProgressError(ControllerError):
    """Raised when consecutive failed iterations produce the same visible diff."""


class VerificationError(ControllerError):
    """Raised when verification fails in a way an edit cannot recover."""


class RunLoggingError(ControllerError):
    """Raised when a transition logger cannot record an event."""


class WorkspaceError(RepoPilotError):
    """Base class for workspace lifecycle failures."""


class WorkspaceExistsError(WorkspaceError):
    """Raised when a requested run identifier is already allocated."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"Workspace already exists for run {run_id!r}.")
        self.run_id = run_id


class WorkspaceSafetyError(WorkspaceError):
    """Raised when a workspace operation targets an unexpected location."""


class PathPolicyError(RepoPilotError):
    """Raised when a repository-relative path violates containment policy."""

    def __init__(self, path: str | Path, reason: str) -> None:
        super().__init__(f"Unsafe repository path {str(path)!r}: {reason}.")
        self.path = Path(path)
        self.reason = reason


class PathNotFoundError(PathPolicyError):
    """Raised when a safe repository-relative path does not exist."""

    def __init__(self, path: str | Path) -> None:
        super().__init__(path, "path does not exist")


class RepositoryError(RepoPilotError):
    """Base class for repository preparation and inspection failures."""


class InvalidRepositoryError(RepositoryError):
    """Raised when a source is not a supported Git working tree."""

    def __init__(self, source: str | Path, reason: str) -> None:
        super().__init__(f"Invalid repository {str(source)!r}: {reason}.")
        self.source = str(source)
        self.reason = reason


class RepositoryCopyError(RepositoryError):
    """Raised when a local repository cannot be copied."""


class InventoryLimitError(RepositoryError):
    """Raised when a repository inventory exceeds its configured limit."""

    def __init__(self, limit: int) -> None:
        super().__init__(f"Repository inventory exceeds the limit of {limit} entries.")
        self.limit = limit


class GitError(RepositoryError):
    """Base class for failures from the controlled Git adapter."""


class GitCommandError(GitError):
    """Raised when Git exits unsuccessfully."""

    def __init__(self, operation: str, exit_code: int, stderr: str) -> None:
        detail = stderr.strip() or "Git returned no error output"
        super().__init__(f"Git operation {operation!r} failed with exit code {exit_code}: {detail}")
        self.operation = operation
        self.exit_code = exit_code
        self.stderr = stderr


class GitTimeoutError(GitError):
    """Raised when a Git operation exceeds its deadline."""

    def __init__(self, operation: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Git operation {operation!r} exceeded its {timeout_seconds:g} second timeout."
        )
        self.operation = operation
        self.timeout_seconds = timeout_seconds


class GitOutputLimitError(GitError):
    """Raised when Git produces more output than policy allows."""

    def __init__(self, operation: str, output_limit_bytes: int) -> None:
        super().__init__(
            f"Git operation {operation!r} exceeded its {output_limit_bytes} byte output limit."
        )
        self.operation = operation
        self.output_limit_bytes = output_limit_bytes


class ProcessError(RepoPilotError):
    """Base class for bounded subprocess failures."""


class ProcessSpawnError(ProcessError):
    """Raised when a subprocess cannot be started."""

    def __init__(self, operation: str, reason: str) -> None:
        super().__init__(f"Could not start {operation!r}: {reason}")
        self.operation = operation
        self.reason = reason


class ProcessTimeoutError(ProcessError):
    """Raised when a subprocess exceeds its deadline."""

    def __init__(self, operation: str, timeout_seconds: float) -> None:
        super().__init__(f"Process {operation!r} exceeded its {timeout_seconds:g} second timeout.")
        self.operation = operation
        self.timeout_seconds = timeout_seconds


class ProcessOutputLimitError(ProcessError):
    """Raised when a subprocess exceeds its output budget."""

    def __init__(self, operation: str, output_limit_bytes: int) -> None:
        super().__init__(
            f"Process {operation!r} exceeded its {output_limit_bytes} byte output limit."
        )
        self.operation = operation
        self.output_limit_bytes = output_limit_bytes

"""Validated unified-patch application inside the disposable repository."""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path

from repopilot.errors import (
    PathNotFoundError,
    PathPolicyError,
    ProcessOutputLimitError,
    ProcessSpawnError,
    ProcessTimeoutError,
)
from repopilot.models import RepositoryCheckout
from repopilot.path_policy import resolve_workspace_entry, resolve_workspace_path
from repopilot.process import BoundedProcessRunner, safe_search_path
from repopilot.tool_models import (
    ToolErrorCode,
    ToolName,
    ToolResult,
    WritePatchData,
    WritePatchRequest,
)
from repopilot.tools._results import failed, started_at, succeeded


class PatchTool:
    """Validate and apply a constrained Git-style unified patch."""

    def __init__(
        self,
        checkout: RepositoryCheckout,
        *,
        timeout_seconds: float = 30,
        output_limit_bytes: int = 262_144,
    ) -> None:
        self._checkout = checkout
        self._runner = BoundedProcessRunner(
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
        )
        search_path = safe_search_path(
            os.environ.get("PATH", os.defpath),
            forbidden_root=checkout.path,
        )
        self._git_executable = shutil.which("git", path=search_path)

    def apply(self, request: WritePatchRequest) -> ToolResult[WritePatchData]:
        """Check the patch and apply it only when every target is safe."""
        started = started_at()
        try:
            if self._git_executable is None:
                raise ProcessSpawnError("apply patch", "Git is not installed")
            paths = self._validated_paths(request.patch)
            environment = _git_environment(self._checkout.path)
            check = self._runner.run(
                "check patch",
                _git_apply_command(self._git_executable, check=True),
                cwd=self._checkout.path,
                stdin=request.patch.encode("utf-8"),
                environment=environment,
            )
            if check.exit_code != 0:
                message = check.stderr.decode("utf-8", errors="replace").strip()
                return failed(
                    ToolName.WRITE_PATCH,
                    started,
                    ToolErrorCode.PATCH_REJECTED,
                    message or "Git rejected the patch during validation.",
                )
            applied = self._runner.run(
                "apply patch",
                _git_apply_command(self._git_executable, check=False),
                cwd=self._checkout.path,
                stdin=request.patch.encode("utf-8"),
                environment=environment,
            )
            if applied.exit_code != 0:
                message = applied.stderr.decode("utf-8", errors="replace").strip()
                return failed(
                    ToolName.WRITE_PATCH,
                    started,
                    ToolErrorCode.EXECUTION_ERROR,
                    message or "Git failed while applying the validated patch.",
                )
            return succeeded(
                ToolName.WRITE_PATCH,
                started,
                WritePatchData(changed_paths=paths),
            )
        except _PatchFormatError as exc:
            return failed(ToolName.WRITE_PATCH, started, ToolErrorCode.PATCH_REJECTED, str(exc))
        except PathPolicyError as exc:
            return failed(ToolName.WRITE_PATCH, started, ToolErrorCode.POLICY_DENIED, str(exc))
        except ProcessTimeoutError as exc:
            return failed(ToolName.WRITE_PATCH, started, ToolErrorCode.TIMEOUT, str(exc))
        except ProcessOutputLimitError as exc:
            return failed(ToolName.WRITE_PATCH, started, ToolErrorCode.LIMIT_EXCEEDED, str(exc))
        except (ProcessSpawnError, OSError) as exc:
            return failed(ToolName.WRITE_PATCH, started, ToolErrorCode.EXECUTION_ERROR, str(exc))

    def _validated_paths(self, patch: str) -> tuple[str, ...]:
        paths: set[str] = set()
        for line in patch.splitlines():
            if line in ("new file mode 120000", "new mode 120000"):
                raise _PatchFormatError("Patches cannot create symbolic links in the MVP.")
            if line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
                raise _PatchFormatError("Rename and copy metadata are not supported in the MVP.")
            if not line.startswith("diff --git "):
                if line.startswith(("--- ", "+++ ")):
                    marker_path = _marker_path(line)
                    if marker_path != "/dev/null":
                        paths.add(self._validate_patch_path(marker_path[2:]))
                continue
            try:
                parts = shlex.split(line)
            except ValueError as exc:
                raise _PatchFormatError(f"Invalid diff header: {exc}") from exc
            if len(parts) != 4 or not parts[2].startswith("a/") or not parts[3].startswith("b/"):
                raise _PatchFormatError("Every patch section requires a Git-style diff header.")
            for raw_path in (parts[2][2:], parts[3][2:]):
                paths.add(self._validate_patch_path(raw_path))
        if not paths:
            raise _PatchFormatError("Patch does not contain a Git-style file section.")
        return tuple(sorted(paths))

    def _validate_patch_path(self, raw_path: str) -> str:
        candidate = Path(raw_path)
        if not candidate.parts or candidate.parts[0].casefold() == ".git":
            raise PathPolicyError(raw_path, "Git metadata cannot be modified")
        try:
            entry = resolve_workspace_entry(self._checkout.path, candidate)
        except PathNotFoundError:
            pass
        else:
            if entry.is_symlink():
                raise PathPolicyError(raw_path, "symbolic links cannot be modified")
        resolve_workspace_path(self._checkout.path, candidate, must_exist=False)
        return candidate.as_posix()


class _PatchFormatError(ValueError):
    pass


def _git_apply_command(executable: str, *, check: bool) -> tuple[str, ...]:
    command = [executable, "-c", "core.hooksPath=/dev/null", "apply"]
    if check:
        command.append("--check")
    command.extend(("--whitespace=error-all", "-"))
    return tuple(command)


def _git_environment(repository: Path) -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "PATH": safe_search_path(
            os.environ.get("PATH", os.defpath),
            forbidden_root=repository,
        ),
    }


def _marker_path(line: str) -> str:
    value = line[4:].split("\t", maxsplit=1)[0]
    try:
        parts = shlex.split(value)
    except ValueError as exc:
        raise _PatchFormatError(f"Invalid patch marker: {exc}") from exc
    if len(parts) != 1:
        raise _PatchFormatError("Patch marker paths with spaces must be quoted.")
    path = parts[0]
    expected_prefix = "a/" if line.startswith("--- ") else "b/"
    if path != "/dev/null" and not path.startswith(expected_prefix):
        raise _PatchFormatError("Patch markers must use a/ and b/ path prefixes.")
    return path

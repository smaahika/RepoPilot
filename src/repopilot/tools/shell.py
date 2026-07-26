"""Allowlisted, bounded command execution inside a prepared repository."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from repopilot.errors import (
    PathNotFoundError,
    PathPolicyError,
    ProcessOutputLimitError,
    ProcessSpawnError,
    ProcessTimeoutError,
)
from repopilot.models import RepositoryCheckout
from repopilot.path_policy import resolve_workspace_path
from repopilot.process import BoundedProcessRunner, safe_search_path
from repopilot.tool_models import (
    RunCommandData,
    RunCommandRequest,
    ToolErrorCode,
    ToolName,
    ToolResult,
)
from repopilot.tools._results import failed, started_at, succeeded


@dataclass(frozen=True, slots=True)
class CommandRule:
    """An allowed command prefix with optional arguments after it."""

    prefix: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.prefix or any(not part for part in self.prefix):
            raise ValueError("Command rule prefixes must contain non-empty arguments")


class CommandPolicy:
    """Authorize narrow command prefixes and reject path escapes in arguments."""

    def __init__(self, rules: tuple[CommandRule, ...] | None = None) -> None:
        self._rules = self.default_rules() if rules is None else rules

    @staticmethod
    def default_rules() -> tuple[CommandRule, ...]:
        return (
            CommandRule(("pytest",)),
            CommandRule(("python", "-m", "pytest")),
            CommandRule(("python3", "-m", "pytest")),
            CommandRule(("ruff", "check")),
            CommandRule(("ruff", "format", "--check")),
            CommandRule(("mypy",)),
            CommandRule(("npm", "test")),
            CommandRule(("npm", "run", "test")),
            CommandRule(("npm", "run", "lint")),
        )

    def authorize(self, argv: tuple[str, ...], *, search_path: str) -> tuple[str, ...]:
        """Return argv with a resolved executable or raise a policy failure."""
        if Path(argv[0]).name != argv[0]:
            raise _CommandPolicyError("Command executables cannot contain path components.")
        if not any(argv[: len(rule.prefix)] == rule.prefix for rule in self._rules):
            raise _CommandPolicyError("Command prefix is not allowlisted.")
        for argument in argv[1:]:
            self._validate_argument(argument)

        executable = shutil.which(argv[0], path=search_path)
        if executable is None:
            raise _CommandPolicyError(f"Allowlisted executable {argv[0]!r} is not installed.")
        return (str(Path(executable).resolve(strict=True)), *argv[1:])

    @staticmethod
    def _validate_argument(argument: str) -> None:
        if argument.startswith("@"):
            raise _CommandPolicyError("Command response files are not allowed.")
        values = (argument, argument.partition("=")[2]) if "=" in argument else (argument,)
        for value in values:
            if not value or value.startswith("-"):
                continue
            candidate = Path(value)
            if candidate.is_absolute() or ".." in candidate.parts:
                raise _CommandPolicyError(
                    f"Command argument {argument!r} can escape the repository."
                )


class CommandTool:
    """Execute approved verification commands with bounded resources."""

    def __init__(
        self,
        checkout: RepositoryCheckout,
        policy: CommandPolicy | None = None,
        *,
        output_limit_bytes: int = 1_048_576,
        timeout_limit_seconds: float = 120,
    ) -> None:
        self._checkout = checkout
        self._policy = policy or CommandPolicy()
        self._runner = BoundedProcessRunner(
            timeout_seconds=timeout_limit_seconds,
            output_limit_bytes=output_limit_bytes,
        )

    def run(self, request: RunCommandRequest) -> ToolResult[RunCommandData]:
        """Run an allowlisted command and preserve nonzero exits as data."""
        started = started_at()
        try:
            cwd = resolve_workspace_path(self._checkout.path, request.cwd)
            if not cwd.is_dir():
                raise PathPolicyError(request.cwd, "command cwd is not a directory")
            environment = self._environment()
            argv = self._policy.authorize(request.argv, search_path=environment["PATH"])
            result = self._runner.run(
                "run command",
                argv,
                cwd=cwd,
                environment=environment,
                timeout_seconds=request.timeout_seconds,
            )
            relative_cwd = cwd.relative_to(self._checkout.path.resolve(strict=True)).as_posix()
            return succeeded(
                ToolName.RUN_COMMAND,
                started,
                RunCommandData(
                    argv=request.argv,
                    cwd=relative_cwd or ".",
                    exit_code=result.exit_code,
                    stdout=result.stdout.decode("utf-8", errors="replace"),
                    stderr=result.stderr.decode("utf-8", errors="replace"),
                ),
            )
        except _CommandPolicyError as exc:
            return failed(ToolName.RUN_COMMAND, started, ToolErrorCode.POLICY_DENIED, str(exc))
        except PathNotFoundError as exc:
            return failed(ToolName.RUN_COMMAND, started, ToolErrorCode.NOT_FOUND, str(exc))
        except PathPolicyError as exc:
            return failed(ToolName.RUN_COMMAND, started, ToolErrorCode.POLICY_DENIED, str(exc))
        except ProcessTimeoutError as exc:
            return failed(ToolName.RUN_COMMAND, started, ToolErrorCode.TIMEOUT, str(exc))
        except ProcessOutputLimitError as exc:
            return failed(ToolName.RUN_COMMAND, started, ToolErrorCode.LIMIT_EXCEEDED, str(exc))
        except (ProcessSpawnError, OSError) as exc:
            return failed(ToolName.RUN_COMMAND, started, ToolErrorCode.EXECUTION_ERROR, str(exc))

    def _environment(self) -> dict[str, str]:
        temporary = self._checkout.workspace.root_path / "command-tmp"
        cache = self._checkout.workspace.root_path / "command-cache"
        temporary.mkdir(exist_ok=True)
        cache.mkdir(exist_ok=True)
        return {
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PATH": safe_search_path(
                os.environ.get("PATH", os.defpath),
                forbidden_root=self._checkout.path,
            ),
            "PYTHONDONTWRITEBYTECODE": "1",
            "TMPDIR": str(temporary),
            "XDG_CACHE_HOME": str(cache),
        }


class _CommandPolicyError(ValueError):
    pass

"""Bounded, non-shelling Git operations used by the repository service."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol

from repopilot.errors import (
    GitCommandError,
    GitOutputLimitError,
    GitTimeoutError,
    ProcessOutputLimitError,
    ProcessSpawnError,
    ProcessTimeoutError,
)
from repopilot.process import BoundedProcessRunner, ProcessResult, safe_search_path


class GitClient(Protocol):
    """Operations RepoPilot needs from Git, injectable for deterministic tests."""

    def clone(self, source: str, destination: Path) -> None:
        """Clone ``source`` into ``destination``."""
        ...

    def list_files(self, repository: Path) -> tuple[str, ...]:
        """List tracked and non-ignored untracked paths."""
        ...

    def capture_baseline(
        self,
        repository: Path,
        baseline_git_path: Path,
        paths: tuple[str, ...],
    ) -> str:
        """Capture the current files in a private Git tree and return its object ID."""
        ...

    def diff(
        self,
        repository: Path,
        baseline_git_path: Path,
        baseline_tree: str,
        current_paths: tuple[str, ...],
    ) -> str:
        """Return the working tree's binary-capable unified diff from ``baseline_tree``."""
        ...


class SubprocessGitClient:
    """Execute a deliberately small set of Git commands without invoking a shell."""

    def __init__(
        self,
        *,
        timeout_seconds: float = 120,
        output_limit_bytes: int = 1_048_576,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if output_limit_bytes <= 0:
            raise ValueError("output_limit_bytes must be positive")
        self._timeout_seconds = timeout_seconds
        self._runner = BoundedProcessRunner(
            timeout_seconds=timeout_seconds,
            output_limit_bytes=output_limit_bytes,
        )
        self._search_path = safe_search_path(os.environ.get("PATH", os.defpath))
        self._git_executable = shutil.which("git", path=self._search_path)

    def clone(self, source: str, destination: Path) -> None:
        """Clone a repository with prompts and user-level Git configuration disabled."""
        self._run(
            "clone repository",
            ["clone", "--quiet", "--no-hardlinks", "--", source, str(destination)],
        )

    def list_files(self, repository: Path) -> tuple[str, ...]:
        """Use the repository index and ignore rules to select visible files."""
        result = self._run(
            "list repository files",
            [
                "-C",
                str(repository),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
                "-z",
                "--",
            ],
        )
        return tuple(os.fsdecode(item) for item in result.stdout.split(b"\0") if item)

    def capture_baseline(
        self,
        repository: Path,
        baseline_git_path: Path,
        paths: tuple[str, ...],
    ) -> str:
        """Create a private object database and snapshot only inventory-visible paths."""
        self._run(
            "initialize baseline",
            ["init", "--bare", "--quiet", str(baseline_git_path)],
        )
        if paths:
            self._run_controlled(
                "stage baseline",
                repository,
                baseline_git_path,
                [
                    "add",
                    "--all",
                    "--force",
                    "--pathspec-from-file=-",
                    "--pathspec-file-nul",
                ],
                stdin=self._encode_paths(paths),
            )
        result = self._run_controlled(
            "write baseline tree",
            repository,
            baseline_git_path,
            ["write-tree"],
        )
        return result.stdout.decode("ascii").strip()

    def diff(
        self,
        repository: Path,
        baseline_git_path: Path,
        baseline_tree: str,
        current_paths: tuple[str, ...],
    ) -> str:
        """Include new visible files and compare the worktree with its captured tree."""
        self._run_controlled(
            "reset diff index",
            repository,
            baseline_git_path,
            ["read-tree", baseline_tree],
        )
        if current_paths:
            self._run_controlled(
                "mark new files for diff",
                repository,
                baseline_git_path,
                ["add", "--intent-to-add", "--pathspec-from-file=-", "--pathspec-file-nul"],
                stdin=self._encode_paths(current_paths),
            )
        result = self._run_controlled(
            "generate repository diff",
            repository,
            baseline_git_path,
            ["diff", "--binary", "--no-ext-diff", "--no-renames", baseline_tree, "--"],
        )
        return result.stdout.decode("utf-8", errors="replace")

    def _run_controlled(
        self,
        operation: str,
        repository: Path,
        baseline_git_path: Path,
        arguments: list[str],
        *,
        stdin: bytes | None = None,
    ) -> ProcessResult:
        return self._run(
            operation,
            [
                "--literal-pathspecs",
                f"--git-dir={baseline_git_path}",
                f"--work-tree={repository}",
                *arguments,
            ],
            stdin=stdin,
        )

    def _run(
        self,
        operation: str,
        arguments: list[str],
        *,
        stdin: bytes | None = None,
    ) -> ProcessResult:
        if self._git_executable is None:
            raise GitCommandError(operation, 127, "Git is not installed")
        command = [
            self._git_executable,
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.hooksPath=/dev/null",
            *arguments,
        ]
        environment = {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_LFS_SKIP_SMUDGE": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
            "PATH": self._search_path,
        }

        try:
            result = self._runner.run(
                operation,
                command,
                stdin=stdin,
                environment=environment,
            )
        except ProcessTimeoutError as exc:
            raise GitTimeoutError(operation, self._timeout_seconds) from exc
        except ProcessOutputLimitError as exc:
            raise GitOutputLimitError(operation, exc.output_limit_bytes) from exc
        except ProcessSpawnError as exc:
            raise GitCommandError(operation, 127, exc.reason) from exc

        if result.exit_code != 0:
            raise GitCommandError(
                operation,
                result.exit_code,
                result.stderr.decode("utf-8", errors="replace"),
            )
        return result

    @staticmethod
    def _encode_paths(paths: tuple[str, ...]) -> bytes:
        if any("\x00" in path for path in paths):
            raise ValueError("Git paths cannot contain NUL bytes")
        return b"\0".join(os.fsencode(path) for path in paths) + b"\0"

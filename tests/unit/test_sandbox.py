"""Tests for Docker command construction and failure handling."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from pydantic import ValidationError

from repopilot.errors import ProcessTimeoutError, SandboxExecutionError
from repopilot.models import RepositoryCheckout, RunWorkspace
from repopilot.process import ProcessResult
from repopilot.sandbox import DockerCommandBackend, DockerSandboxConfig, find_docker_executable
from repopilot.tool_models import RunCommandRequest, ToolErrorCode
from repopilot.tools.shell import CommandTool


class _RecordingRunner:
    def __init__(
        self,
        *,
        exit_code: int = 0,
        stdout: bytes = b"",
        stderr: bytes = b"",
        error: BaseException | None = None,
    ) -> None:
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        self.error = error
        self.calls: list[tuple[str, tuple[str, ...], Mapping[str, str] | None, float | None]] = []

    def run(
        self,
        operation: str,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: bytes | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> ProcessResult:
        arguments = tuple(argv)
        self.calls.append((operation, arguments, environment, timeout_seconds))
        if self.error is not None:
            raise self.error
        return ProcessResult(
            argv=arguments,
            exit_code=self.exit_code,
            stdout=self.stdout,
            stderr=self.stderr,
            duration_ms=7,
        )


def _checkout(tmp_path: Path) -> tuple[RepositoryCheckout, Path]:
    root = tmp_path / "workspace"
    repository = root / "repository"
    cwd = repository / "tests"
    cwd.mkdir(parents=True)
    workspace = RunWorkspace(
        run_id="sandbox-test",
        root_path=root,
        artifact_path=tmp_path / "artifacts",
    )
    return RepositoryCheckout(workspace=workspace, baseline_tree="tree"), cwd


def test_builds_fixed_isolation_command_without_shell(tmp_path: Path) -> None:
    checkout, cwd = _checkout(tmp_path)
    runner = _RecordingRunner(stdout=b"passed\n")
    backend = DockerCommandBackend(
        DockerSandboxConfig(
            image="sandbox:test",
            cpus=1.5,
            memory_mb=768,
            pids_limit=64,
            tmpfs_mb=128,
        ),
        runner=runner,
        executable_finder=lambda: "/usr/local/bin/docker",
        identifier_factory=lambda: "abcdef1234567890",
    )

    result = backend.run(checkout, cwd, ("pytest", "-q"), 30)

    assert result.stdout == b"passed\n"
    operation, command, environment, timeout = runner.calls[0]
    assert operation == "Docker sandbox"
    assert timeout == 30
    assert command[:2] == ("/usr/local/bin/docker", "run")
    assert command[-3:] == ("sandbox:test", "pytest", "-q")
    assert _option(command, "--network") == "none"
    assert "--read-only" in command
    assert _option(command, "--cap-drop") == "ALL"
    assert _option(command, "--security-opt") == "no-new-privileges=true"
    assert _option(command, "--pids-limit") == "64"
    assert _option(command, "--memory") == "768m"
    assert _option(command, "--cpus") == "1.5"
    assert _option(command, "--pull") == "never"
    assert _option(command, "--workdir") == "/workspace/tests"
    assert _option(command, "--mount").endswith(",dst=/workspace,readonly")
    assert environment is not None
    assert "OPENAI_API_KEY" not in environment
    if hasattr(os, "getuid"):
        assert _option(command, "--user") == f"{os.getuid()}:{os.getgid()}"


def test_missing_docker_is_an_actionable_tool_error(tmp_path: Path) -> None:
    checkout, _ = _checkout(tmp_path)
    backend = DockerCommandBackend(executable_finder=lambda: None)

    result = CommandTool(checkout, backend=backend).run(RunCommandRequest(argv=("pytest", "-q")))

    assert result.error is not None
    assert result.error.code is ToolErrorCode.EXECUTION_ERROR
    assert "Docker CLI is not installed" in result.error.message


def test_docker_start_failure_is_not_treated_as_test_failure(tmp_path: Path) -> None:
    checkout, cwd = _checkout(tmp_path)
    runner = _RecordingRunner(exit_code=125, stderr=b"daemon unavailable")
    backend = DockerCommandBackend(
        runner=runner,
        executable_finder=lambda: "/usr/bin/docker",
    )

    with pytest.raises(SandboxExecutionError, match="daemon unavailable"):
        backend.run(checkout, cwd, ("pytest",), 10)


def test_timeout_forces_named_container_removal(tmp_path: Path) -> None:
    checkout, cwd = _checkout(tmp_path)
    runner = _RecordingRunner(error=ProcessTimeoutError("Docker sandbox", 5))
    cleanup = _RecordingRunner()
    backend = DockerCommandBackend(
        runner=runner,
        cleanup_runner=cleanup,
        executable_finder=lambda: "/usr/bin/docker",
        identifier_factory=lambda: "cleanup123456",
    )

    with pytest.raises(ProcessTimeoutError):
        backend.run(checkout, cwd, ("pytest",), 5)

    assert cleanup.calls[0][1] == (
        "/usr/bin/docker",
        "rm",
        "--force",
        "repopilot-sandbox-test-cleanup12345",
    )


@pytest.mark.parametrize(
    "values",
    [
        {"image": "--privileged"},
        {"cpus": 0},
        {"memory_mb": 64},
        {"pids_limit": 1_000},
        {"tmpfs_mb": 2_000},
    ],
)
def test_rejects_unsafe_or_unbounded_configuration(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DockerSandboxConfig.model_validate(values)


def test_finds_docker_desktop_when_cli_is_not_on_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    bundled = tmp_path / "docker"
    bundled.write_text("binary", encoding="utf-8")
    monkeypatch.setattr("repopilot.sandbox.shutil.which", lambda name, path: None)
    monkeypatch.setattr("repopilot.sandbox.sys.platform", "darwin")
    monkeypatch.setattr("repopilot.sandbox._MACOS_DOCKER_CLI", bundled)

    assert find_docker_executable() == str(bundled.resolve())


def _option(command: tuple[str, ...], name: str) -> str:
    return command[command.index(name) + 1]

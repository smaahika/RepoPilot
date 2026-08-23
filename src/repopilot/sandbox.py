"""Docker-backed command execution with explicit isolation limits."""

from __future__ import annotations

import os
import shutil
import sys
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from pathlib import Path, PurePosixPath
from typing import Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from repopilot.errors import SandboxExecutionError
from repopilot.models import RepositoryCheckout
from repopilot.process import BoundedProcessRunner, ProcessResult, safe_search_path

_MACOS_DOCKER_CLI = Path("/Applications/Docker.app/Contents/Resources/bin/docker")


class DockerSandboxConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    image: str = Field(
        default="repopilot-sandbox:py312",
        min_length=1,
        max_length=255,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._/:@-]*$",
    )
    cpus: float = Field(default=1.0, gt=0, le=8)
    memory_mb: int = Field(default=512, ge=128, le=4_096)
    pids_limit: int = Field(default=128, ge=16, le=512)
    tmpfs_mb: int = Field(default=256, ge=16, le=1_024)


class _ProcessRunner(Protocol):
    def run(
        self,
        operation: str,
        argv: Sequence[str],
        *,
        cwd: Path | None = None,
        stdin: bytes | None = None,
        environment: Mapping[str, str] | None = None,
        timeout_seconds: float | None = None,
    ) -> ProcessResult: ...


class DockerCommandBackend:
    """Run validated commands in an ephemeral, resource-bounded container."""

    def __init__(
        self,
        config: DockerSandboxConfig | None = None,
        *,
        runner: _ProcessRunner | None = None,
        cleanup_runner: _ProcessRunner | None = None,
        executable_finder: Callable[[], str | None] | None = None,
        identifier_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config or DockerSandboxConfig()
        self._runner = runner or BoundedProcessRunner()
        self._cleanup_runner = cleanup_runner or BoundedProcessRunner(
            timeout_seconds=10,
            output_limit_bytes=65_536,
        )
        self._executable_finder = executable_finder or find_docker_executable
        self._identifier_factory = identifier_factory or (lambda: uuid4().hex)

    def run(
        self,
        checkout: RepositoryCheckout,
        cwd: Path,
        argv: tuple[str, ...],
        timeout_seconds: float,
    ) -> ProcessResult:
        docker = self._executable_finder()
        if docker is None:
            raise SandboxExecutionError(
                "Docker execution was requested, but the Docker CLI is not installed."
            )
        if "," in str(checkout.path):
            raise SandboxExecutionError("Docker bind-mount paths cannot contain commas.")

        container_name = self._container_name(checkout.workspace.run_id)
        environment = _docker_environment()
        command = self._command(docker, container_name, checkout, cwd, argv)
        try:
            result = self._runner.run(
                "Docker sandbox",
                command,
                environment=environment,
                timeout_seconds=timeout_seconds,
            )
        except BaseException:
            self._force_remove(docker, container_name, environment)
            raise

        if result.exit_code == 125:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            message = detail or "Docker returned no diagnostic output"
            raise SandboxExecutionError(f"Docker sandbox could not start: {message}")
        return result

    def _command(
        self,
        docker: str,
        container_name: str,
        checkout: RepositoryCheckout,
        cwd: Path,
        argv: tuple[str, ...],
    ) -> tuple[str, ...]:
        repository = checkout.path.resolve(strict=True)
        relative_cwd = cwd.relative_to(repository)
        container_cwd = PurePosixPath("/workspace", *relative_cwd.parts).as_posix()
        command = [
            docker,
            "run",
            "--rm",
            "--pull",
            "never",
            "--name",
            container_name,
            "--network",
            "none",
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges=true",
            "--pids-limit",
            str(self._config.pids_limit),
            "--memory",
            f"{self._config.memory_mb}m",
            "--cpus",
            f"{self._config.cpus:g}",
            "--tmpfs",
            f"/tmp:rw,noexec,nosuid,nodev,size={self._config.tmpfs_mb}m",
            "--mount",
            f"type=bind,src={repository},dst=/workspace,readonly",
            "--workdir",
            container_cwd,
            "--env",
            "HOME=/tmp/home",
            "--env",
            "TMPDIR=/tmp",
            "--env",
            "XDG_CACHE_HOME=/tmp/cache",
            "--env",
            "PYTHONDONTWRITEBYTECODE=1",
            "--env",
            "COVERAGE_FILE=/tmp/coverage",
            "--env",
            "MYPY_CACHE_DIR=/tmp/mypy-cache",
            "--env",
            "RUFF_CACHE_DIR=/tmp/ruff-cache",
            "--env",
            "npm_config_cache=/tmp/npm-cache",
            "--init",
        ]
        container_user = _container_user()
        if container_user is not None:
            command.extend(("--user", container_user))
        command.extend((self._config.image, *argv))
        return tuple(command)

    def _container_name(self, run_id: str) -> str:
        identifier = self._identifier_factory()[:12]
        return f"repopilot-{run_id[:32]}-{identifier}"

    def _force_remove(
        self,
        docker: str,
        container_name: str,
        environment: Mapping[str, str],
    ) -> None:
        with suppress(Exception):
            self._cleanup_runner.run(
                "Docker sandbox cleanup",
                (docker, "rm", "--force", container_name),
                environment=environment,
                timeout_seconds=10,
            )


def find_docker_executable() -> str | None:
    """Find Docker on PATH or in Docker Desktop's standard macOS location."""
    search_path = safe_search_path(os.environ.get("PATH", os.defpath))
    executable = shutil.which("docker", path=search_path)
    if executable is not None:
        return str(Path(executable).resolve(strict=True))
    if sys.platform == "darwin" and _MACOS_DOCKER_CLI.is_file():
        return str(_MACOS_DOCKER_CLI.resolve(strict=True))
    return None


def _docker_environment() -> dict[str, str]:
    allowed = (
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "HOME",
        "LANG",
        "LC_ALL",
    )
    environment = {name: os.environ[name] for name in allowed if name in os.environ}
    environment["PATH"] = safe_search_path(os.environ.get("PATH", os.defpath))
    return environment


def _container_user() -> str | None:
    if not hasattr(os, "getuid") or not hasattr(os, "getgid"):
        return None
    return f"{os.getuid()}:{os.getgid()}"

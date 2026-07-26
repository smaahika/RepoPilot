"""Reusable bounded subprocess execution without a shell."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from repopilot.errors import ProcessOutputLimitError, ProcessSpawnError, ProcessTimeoutError


@dataclass(frozen=True, slots=True)
class ProcessResult:
    """Captured result from a completed subprocess."""

    argv: tuple[str, ...]
    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_ms: int


class BoundedProcessRunner:
    """Run argument vectors with hard time and combined-output limits."""

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
        self._output_limit_bytes = output_limit_bytes

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
        """Execute a subprocess and capture bounded byte output."""
        arguments = tuple(argv)
        if not arguments:
            raise ValueError("argv cannot be empty")
        timeout = self._timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0 or timeout > self._timeout_seconds:
            raise ValueError("timeout_seconds must be positive and within the runner limit")

        started = time.monotonic_ns()
        try:
            process = subprocess.Popen(
                arguments,
                cwd=cwd,
                env=dict(environment) if environment is not None else None,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=os.name == "posix",
            )
        except OSError as exc:
            raise ProcessSpawnError(operation, str(exc)) from exc

        assert process.stdout is not None
        assert process.stderr is not None
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        if stdin is not None:
            assert process.stdin is not None
            os.set_blocking(process.stdin.fileno(), False)
            selector.register(process.stdin, selectors.EVENT_WRITE, "stdin")

        stdout = bytearray()
        stderr = bytearray()
        stdin_offset = 0
        deadline = time.monotonic() + timeout

        try:
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ProcessTimeoutError(operation, timeout)

                for key, _ in selector.select(timeout=remaining):
                    if key.data == "stdin":
                        assert stdin is not None
                        try:
                            written = os.write(key.fd, stdin[stdin_offset : stdin_offset + 65_536])
                        except BlockingIOError:
                            written = 0
                        except BrokenPipeError:
                            written = len(stdin) - stdin_offset
                        stdin_offset += written
                        if stdin_offset >= len(stdin):
                            assert process.stdin is not None
                            selector.unregister(process.stdin)
                            process.stdin.close()
                        continue

                    chunk = os.read(key.fd, 65_536)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    target = stdout if key.data == "stdout" else stderr
                    target.extend(chunk)
                    if len(stdout) + len(stderr) > self._output_limit_bytes:
                        raise ProcessOutputLimitError(operation, self._output_limit_bytes)

            exit_code = process.wait()
        except BaseException:
            _kill_process_group(process)
            process.wait()
            raise
        finally:
            selector.close()
            process.stdout.close()
            process.stderr.close()
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()

        duration_ms = (time.monotonic_ns() - started) // 1_000_000
        return ProcessResult(
            argv=arguments,
            exit_code=exit_code,
            stdout=bytes(stdout),
            stderr=bytes(stderr),
            duration_ms=duration_ms,
        )


def safe_search_path(search_path: str, *, forbidden_root: Path | None = None) -> str:
    """Keep absolute PATH entries outside an optional untrusted root."""
    entries: list[str] = []
    resolved_root = forbidden_root.resolve(strict=True) if forbidden_root is not None else None
    for entry in search_path.split(os.pathsep):
        path = Path(entry)
        if not path.is_absolute():
            continue
        try:
            resolved = path.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved_root is not None and resolved.is_relative_to(resolved_root):
            continue
        entries.append(str(resolved))
    return os.pathsep.join(entries) or os.defpath


def _kill_process_group(process: subprocess.Popen[bytes]) -> None:
    if os.name == "posix":
        with suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
    elif process.poll() is None:
        process.kill()

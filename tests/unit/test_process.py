"""Tests for reusable bounded subprocess execution."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from repopilot.errors import ProcessOutputLimitError, ProcessTimeoutError
from repopilot.process import BoundedProcessRunner


def test_captures_exit_and_both_output_streams() -> None:
    result = BoundedProcessRunner().run(
        "capture",
        [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"],
    )

    assert result.exit_code == 0
    assert result.stdout == b"out\n"
    assert result.stderr == b"err\n"
    assert result.duration_ms >= 0


def test_streams_large_stdin_without_deadlock() -> None:
    payload = b"x" * 200_000
    result = BoundedProcessRunner(output_limit_bytes=300_000).run(
        "stdin",
        [sys.executable, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
        stdin=payload,
    )

    assert result.stdout == payload


def test_kills_process_at_output_limit() -> None:
    runner = BoundedProcessRunner(output_limit_bytes=32)

    with pytest.raises(ProcessOutputLimitError):
        runner.run("output", [sys.executable, "-c", "print('x' * 1000)"])


def test_kills_process_at_deadline() -> None:
    runner = BoundedProcessRunner(timeout_seconds=0.05)

    with pytest.raises(ProcessTimeoutError):
        runner.run("sleep", [sys.executable, "-c", "import time; time.sleep(2)"])


def test_stdin_write_is_covered_by_deadline() -> None:
    runner = BoundedProcessRunner(timeout_seconds=0.05, output_limit_bytes=1_024)

    with pytest.raises(ProcessTimeoutError):
        runner.run(
            "blocked stdin",
            [sys.executable, "-c", "import time; time.sleep(2)"],
            stdin=b"x" * 1_000_000,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX process-group behavior")
def test_timeout_kills_spawned_children(tmp_path: Path) -> None:
    marker = tmp_path / "child-survived"
    child = f"import time; time.sleep(0.3); open({str(marker)!r}, 'w').write('alive')"
    parent = (
        "import subprocess, sys, time; "
        f"subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(2)"
    )

    with pytest.raises(ProcessTimeoutError):
        BoundedProcessRunner(timeout_seconds=0.1).run(
            "process tree",
            [sys.executable, "-c", parent],
        )

    time.sleep(0.4)
    assert not marker.exists()

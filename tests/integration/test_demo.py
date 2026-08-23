"""Executable documentation test for the deterministic demo."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_demo_runs_real_controller_and_prints_reviewable_evidence() -> None:
    completed = subprocess.run(
        (sys.executable, str(_ROOT / "scripts" / "demo.py")),
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    transcript = completed.stdout
    demo_document = (_ROOT / "docs" / "demo.md").read_text(encoding="utf-8")
    canonical = demo_document.split("```text\n", 1)[1].split("\n```", 1)[0] + "\n"
    assert completed.returncode == 0
    assert completed.stderr == ""
    assert transcript == canonical
    assert "Result: success" in transcript
    assert "Verification: passed" in transcript
    assert "Changed files: greeting.py" in transcript
    assert "commands/001-test.log" in transcript
    assert '+    return "hello RepoPilot"' in transcript


def test_demo_can_preserve_its_artifacts(tmp_path: Path) -> None:
    output = tmp_path / "demo"

    completed = subprocess.run(
        (
            sys.executable,
            str(_ROOT / "scripts" / "demo.py"),
            "--output-dir",
            str(output),
        ),
        cwd=_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert completed.returncode == 0
    assert f"Saved demo workspace: {output}" in completed.stdout
    assert (output / "managed" / "runs" / "demo" / "report.md").is_file()
    assert not (output / "managed" / "workspaces" / "demo").exists()

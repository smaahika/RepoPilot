"""Tests for the local repository security checkpoint."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "security_check.py"


def test_current_repository_passes_security_check() -> None:
    completed = _run_check(_ROOT)

    assert completed.returncode == 0, completed.stderr
    assert "Repository security check passed" in completed.stdout


def test_security_check_rejects_secret_without_printing_it(tmp_path: Path) -> None:
    repository = _git_repository(tmp_path)
    credential = "AK" + "IA" + ("A" * 16)
    (repository / "credentials.txt").write_text(credential, encoding="utf-8")

    completed = _run_check(repository)

    assert completed.returncode == 1
    assert "credentials.txt:1: possible AWS access key" in completed.stderr
    assert credential not in completed.stderr


def test_security_check_rejects_environment_files(tmp_path: Path) -> None:
    repository = _git_repository(tmp_path)
    (repository / ".env.production").write_text("DEBUG=false\n", encoding="utf-8")

    completed = _run_check(repository)

    assert completed.returncode == 1
    assert ".env.production: environment file must not be committed" in completed.stderr


def test_security_check_rejects_oversized_files(tmp_path: Path) -> None:
    repository = _git_repository(tmp_path)
    (repository / "large.txt").write_bytes(b"x" * 1_048_577)

    completed = _run_check(repository)

    assert completed.returncode == 1
    assert "large.txt: file exceeds 1048576 byte limit" in completed.stderr


def test_security_check_allows_tracked_file_deletion(tmp_path: Path) -> None:
    repository = _git_repository(tmp_path)
    removed = repository / "removed.txt"
    removed.write_text("temporary\n", encoding="utf-8")
    subprocess.run(("git", "-C", str(repository), "add", "removed.txt"), check=True)
    removed.unlink()

    completed = _run_check(repository)

    assert completed.returncode == 0, completed.stderr


def _git_repository(tmp_path: Path) -> Path:
    subprocess.run(("git", "init", "--quiet", str(tmp_path)), check=True)
    return tmp_path


def _run_check(repository: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        (sys.executable, str(_SCRIPT), "--root", str(repository)),
        check=False,
        capture_output=True,
        text=True,
    )

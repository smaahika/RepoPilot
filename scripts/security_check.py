"""Check the repository snapshot for high-confidence security mistakes."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

_MAX_FILE_BYTES = 1_048_576
_MAX_FILE_COUNT = 2_000
_MAX_REPOSITORY_BYTES = 16 * _MAX_FILE_BYTES
_FORBIDDEN_DIRECTORIES = frozenset(
    {".mypy_cache", ".pytest_cache", ".repopilot", "__pycache__", "build", "dist"}
)
_FORBIDDEN_SUFFIXES = frozenset({".key", ".log", ".p12", ".pem", ".pfx", ".pyc"})
_SECRET_PATTERNS = (
    ("AWS access key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("GitHub fine-grained token", re.compile(rb"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("OpenAI API key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("private key", re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----")),
)


@dataclass(frozen=True)
class SecurityIssue:
    path: str
    message: str
    line: int | None = None

    def render(self) -> str:
        location = f"{self.path}:{self.line}" if self.line is not None else self.path
        return f"{location}: {self.message}"


@dataclass(frozen=True)
class SecurityReport:
    file_count: int
    total_bytes: int
    issues: tuple[SecurityIssue, ...]


def scan_repository(root: Path) -> SecurityReport:
    root = root.resolve()
    paths = _repository_paths(root)
    if len(paths) > _MAX_FILE_COUNT:
        limit_issue = SecurityIssue(".", f"repository exceeds {_MAX_FILE_COUNT} file scan limit")
        return SecurityReport(len(paths), 0, (limit_issue,))

    issues: list[SecurityIssue] = []
    total_bytes = 0

    for relative_path in paths:
        path_issue = _path_issue(relative_path)
        if path_issue is not None:
            issues.append(path_issue)

        absolute_path = root / relative_path
        if absolute_path.is_symlink():
            issues.append(SecurityIssue(relative_path, "symbolic links are not allowed"))
            continue

        try:
            size = absolute_path.stat().st_size
        except OSError as error:
            issues.append(SecurityIssue(relative_path, f"cannot inspect file: {error.strerror}"))
            continue

        total_bytes += size
        if total_bytes > _MAX_REPOSITORY_BYTES:
            issues.append(
                SecurityIssue(".", f"repository exceeds {_MAX_REPOSITORY_BYTES} byte scan limit")
            )
            break
        if size > _MAX_FILE_BYTES:
            issues.append(
                SecurityIssue(relative_path, f"file exceeds {_MAX_FILE_BYTES} byte limit")
            )
            continue

        try:
            content = absolute_path.read_bytes()
        except OSError as error:
            issues.append(SecurityIssue(relative_path, f"cannot read file: {error.strerror}"))
            continue

        for label, pattern in _SECRET_PATTERNS:
            match = pattern.search(content)
            if match is not None:
                line = content.count(b"\n", 0, match.start()) + 1
                issues.append(SecurityIssue(relative_path, f"possible {label}", line))

    return SecurityReport(len(paths), total_bytes, tuple(issues))


def _repository_paths(root: Path) -> tuple[str, ...]:
    completed = subprocess.run(
        ("git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"),
        cwd=root,
        check=False,
        capture_output=True,
        timeout=10,
    )
    if completed.returncode != 0:
        detail = completed.stderr.decode(errors="replace").strip() or "unknown Git error"
        raise RuntimeError(f"cannot enumerate repository files: {detail}")

    decoded = (os.fsdecode(item) for item in completed.stdout.split(b"\0") if item)
    present = (path for path in decoded if (root / path).exists() or (root / path).is_symlink())
    return tuple(sorted(present))


def _path_issue(path: str) -> SecurityIssue | None:
    parsed = PurePosixPath(path)
    name = parsed.name.lower()
    parts = {part.lower() for part in parsed.parts}

    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return SecurityIssue(path, "environment file must not be committed")
    if parsed.suffix.lower() in _FORBIDDEN_SUFFIXES:
        return SecurityIssue(path, f"forbidden file type: {parsed.suffix.lower()}")
    if parts & _FORBIDDEN_DIRECTORIES or any(part.endswith(".egg-info") for part in parts):
        return SecurityIssue(path, "generated or private runtime path is present")
    if path == "evaluation/results/latest.json":
        return SecurityIssue(path, "generated evaluation result is present")
    return None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Git repository to inspect (defaults to the project root)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = _parse_args(argv)
    try:
        report = scan_repository(arguments.root)
    except (OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(f"Repository security check failed: {error}", file=sys.stderr)
        return 2

    if report.issues:
        print("Repository security check failed:", file=sys.stderr)
        for issue in report.issues:
            print(f"- {issue.render()}", file=sys.stderr)
        return 1

    print(
        f"Repository security check passed: {report.file_count} files, {report.total_bytes} bytes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Isolated worker for time-bounded regular-expression searches."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import TypedDict

from repopilot.path_policy import resolve_workspace_path

_MAX_INPUT_BYTES = 1_048_576
_MAX_LINE_CHARS = 2_000


class _SearchInput(TypedDict):
    pattern: str
    paths: list[str]
    max_file_bytes: int
    max_results: int


def main() -> int:
    payload = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)
    if len(payload) > _MAX_INPUT_BYTES:
        return _write_error("regex search input exceeded its limit")

    try:
        request: _SearchInput = json.loads(payload)
        pattern = re.compile(request["pattern"])
    except (json.JSONDecodeError, KeyError, TypeError, re.error) as exc:
        return _write_error(str(exc))

    matches: list[dict[str, object]] = []
    skipped_files = 0
    truncated = False
    root = Path.cwd()
    for path in request["paths"]:
        try:
            content = _read_text(root, path, request["max_file_bytes"])
        except (OSError, UnicodeError, ValueError):
            skipped_files += 1
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            if pattern.search(line) is None:
                continue
            if len(matches) >= request["max_results"]:
                truncated = True
                break
            matches.append(_match(path, line_number, line))
        if truncated:
            break

    json.dump(
        {"matches": matches, "truncated": truncated, "skipped_files": skipped_files},
        sys.stdout,
        separators=(",", ":"),
    )
    return 0


def _read_text(root: Path, path: str, max_bytes: int) -> str:
    resolved = resolve_workspace_path(root, path)
    with resolved.open("rb") as file:
        content = file.read(max_bytes + 1)
    if len(content) > max_bytes or b"\x00" in content:
        raise ValueError("file is not searchable text")
    return content.decode("utf-8")


def _match(path: str, line_number: int, line: str) -> dict[str, object]:
    return {
        "path": path,
        "line_number": line_number,
        "line": line[:_MAX_LINE_CHARS],
        "line_truncated": len(line) > _MAX_LINE_CHARS,
    }


def _write_error(message: str) -> int:
    json.dump({"error": message}, sys.stdout, separators=(",", ":"))
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

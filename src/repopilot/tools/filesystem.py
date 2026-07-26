"""Bounded filesystem inspection tools."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from repopilot.errors import (
    GitError,
    InventoryLimitError,
    PathNotFoundError,
    PathPolicyError,
    ProcessOutputLimitError,
    ProcessSpawnError,
    ProcessTimeoutError,
)
from repopilot.models import FileKind, RepositoryCheckout
from repopilot.path_policy import resolve_workspace_path
from repopilot.process import BoundedProcessRunner
from repopilot.repository import RepositoryService
from repopilot.tool_models import (
    ListFilesData,
    ListFilesRequest,
    ReadFileData,
    ReadFileRequest,
    SearchMatch,
    SearchTextData,
    SearchTextRequest,
    ToolErrorCode,
    ToolName,
    ToolResult,
)
from repopilot.tools._results import failed, started_at, succeeded

_MAX_SEARCH_LINE_CHARS = 2_000


class FilesystemTools:
    """Expose read-only repository capabilities through normalized results."""

    def __init__(
        self,
        checkout: RepositoryCheckout,
        repository: RepositoryService,
        *,
        regex_timeout_seconds: float = 5,
    ) -> None:
        self._checkout = checkout
        self._repository = repository
        self._regex_runner = BoundedProcessRunner(
            timeout_seconds=regex_timeout_seconds,
            output_limit_bytes=1_048_576,
        )

    def list_files(self, request: ListFilesRequest) -> ToolResult[ListFilesData]:
        """List bounded inventory entries below a validated relative root."""
        started = started_at()
        try:
            root = self._relative_directory(request.root)
            inventory = self._repository.inventory(self._checkout)
            entries = tuple(entry for entry in inventory.entries if _is_below(entry.path, root))
            if len(entries) > request.max_entries:
                return failed(
                    ToolName.LIST_FILES,
                    started,
                    ToolErrorCode.LIMIT_EXCEEDED,
                    f"File listing exceeds the requested limit of {request.max_entries} entries.",
                )
            return succeeded(ToolName.LIST_FILES, started, ListFilesData(entries=entries))
        except PathNotFoundError as exc:
            return failed(ToolName.LIST_FILES, started, ToolErrorCode.NOT_FOUND, str(exc))
        except InventoryLimitError as exc:
            return failed(ToolName.LIST_FILES, started, ToolErrorCode.LIMIT_EXCEEDED, str(exc))
        except PathPolicyError as exc:
            return failed(ToolName.LIST_FILES, started, ToolErrorCode.POLICY_DENIED, str(exc))
        except (GitError, OSError) as exc:
            return failed(ToolName.LIST_FILES, started, ToolErrorCode.EXECUTION_ERROR, str(exc))

    def read_file(self, request: ReadFileRequest) -> ToolResult[ReadFileData]:
        """Read a bounded UTF-8 text file and optional line range."""
        started = started_at()
        try:
            path = resolve_workspace_path(self._checkout.path, request.path)
            if not path.is_file():
                return failed(
                    ToolName.READ_FILE,
                    started,
                    ToolErrorCode.INVALID_INPUT,
                    f"Repository path {request.path!r} is not a regular file.",
                )
            content = _read_bounded(path, request.max_bytes)
            if b"\x00" in content:
                return failed(
                    ToolName.READ_FILE,
                    started,
                    ToolErrorCode.BINARY_FILE,
                    f"Repository path {request.path!r} appears to be binary.",
                )
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                return failed(
                    ToolName.READ_FILE,
                    started,
                    ToolErrorCode.DECODE_ERROR,
                    f"Repository path {request.path!r} is not valid UTF-8.",
                )
            lines = text.splitlines(keepends=True)
            requested_end = request.end_line or len(lines)
            selected = lines[request.start_line - 1 : requested_end]
            actual_end = request.start_line + len(selected) - 1
            return succeeded(
                ToolName.READ_FILE,
                started,
                ReadFileData(
                    path=request.path,
                    start_line=request.start_line,
                    end_line=actual_end,
                    content="".join(selected),
                ),
            )
        except PathNotFoundError as exc:
            return failed(ToolName.READ_FILE, started, ToolErrorCode.NOT_FOUND, str(exc))
        except PathPolicyError as exc:
            return failed(ToolName.READ_FILE, started, ToolErrorCode.POLICY_DENIED, str(exc))
        except _FileLimitError as exc:
            return failed(ToolName.READ_FILE, started, ToolErrorCode.LIMIT_EXCEEDED, str(exc))
        except OSError as exc:
            return failed(ToolName.READ_FILE, started, ToolErrorCode.EXECUTION_ERROR, str(exc))

    def search_text(self, request: SearchTextRequest) -> ToolResult[SearchTextData]:
        """Search bounded UTF-8 files using exact or isolated regex matching."""
        started = started_at()
        try:
            root = self._relative_directory(request.root)
            inventory = self._repository.inventory(self._checkout)
            paths = tuple(
                entry.path
                for entry in inventory.entries
                if entry.kind is FileKind.FILE and _is_below(entry.path, root)
            )
            if request.regex:
                data = self._search_regex(request, paths)
            else:
                data = self._search_exact(request, paths)
            return succeeded(ToolName.SEARCH_TEXT, started, data)
        except PathNotFoundError as exc:
            return failed(ToolName.SEARCH_TEXT, started, ToolErrorCode.NOT_FOUND, str(exc))
        except InventoryLimitError as exc:
            return failed(ToolName.SEARCH_TEXT, started, ToolErrorCode.LIMIT_EXCEEDED, str(exc))
        except PathPolicyError as exc:
            return failed(ToolName.SEARCH_TEXT, started, ToolErrorCode.POLICY_DENIED, str(exc))
        except ProcessTimeoutError as exc:
            return failed(ToolName.SEARCH_TEXT, started, ToolErrorCode.TIMEOUT, str(exc))
        except ProcessOutputLimitError as exc:
            return failed(ToolName.SEARCH_TEXT, started, ToolErrorCode.LIMIT_EXCEEDED, str(exc))
        except _SearchInputLimitError as exc:
            return failed(ToolName.SEARCH_TEXT, started, ToolErrorCode.LIMIT_EXCEEDED, str(exc))
        except _InvalidRegexError as exc:
            return failed(ToolName.SEARCH_TEXT, started, ToolErrorCode.INVALID_INPUT, str(exc))
        except (
            GitError,
            ProcessSpawnError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            return failed(ToolName.SEARCH_TEXT, started, ToolErrorCode.EXECUTION_ERROR, str(exc))

    def _relative_directory(self, requested: str) -> str:
        resolved = resolve_workspace_path(self._checkout.path, requested)
        if not resolved.is_dir():
            raise PathPolicyError(requested, "path is not a directory")
        relative = resolved.relative_to(self._checkout.path.resolve(strict=True))
        return relative.as_posix() or "."

    def _search_exact(
        self,
        request: SearchTextRequest,
        paths: tuple[str, ...],
    ) -> SearchTextData:
        matches: list[SearchMatch] = []
        skipped_files = 0
        for path in paths:
            try:
                entry = resolve_workspace_path(self._checkout.path, path)
                content = _read_bounded(entry, request.max_file_bytes)
                if b"\x00" in content:
                    raise ValueError("binary file")
                text = content.decode("utf-8")
            except (OSError, UnicodeError, ValueError, _FileLimitError):
                skipped_files += 1
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                if request.query not in line:
                    continue
                if len(matches) >= request.max_results:
                    return SearchTextData(tuple(matches), True, skipped_files)
                matches.append(_search_match(path, line_number, line))
        return SearchTextData(tuple(matches), False, skipped_files)

    def _search_regex(
        self,
        request: SearchTextRequest,
        paths: tuple[str, ...],
    ) -> SearchTextData:
        payload = json.dumps(
            {
                "pattern": request.query,
                "paths": paths,
                "max_file_bytes": request.max_file_bytes,
                "max_results": request.max_results,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        if len(payload) > 1_048_576:
            raise _SearchInputLimitError("Regex search input exceeds its 1048576 byte limit.")
        environment = {
            "PATH": os.environ.get("PATH", os.defpath),
            "PYTHONUTF8": "1",
        }
        result = self._regex_runner.run(
            "regex search",
            [sys.executable, "-I", "-m", "repopilot._regex_search"],
            cwd=self._checkout.path,
            stdin=payload,
            environment=environment,
        )
        response: dict[str, Any] = json.loads(result.stdout)
        if result.exit_code != 0:
            raise _InvalidRegexError(str(response.get("error", "regex search failed")))
        matches = tuple(SearchMatch(**match) for match in response["matches"])
        return SearchTextData(
            matches=matches,
            truncated=bool(response["truncated"]),
            skipped_files=int(response["skipped_files"]),
        )


class _FileLimitError(ValueError):
    pass


class _InvalidRegexError(ValueError):
    pass


class _SearchInputLimitError(ValueError):
    pass


def _read_bounded(path: Path, max_bytes: int) -> bytes:
    with path.open("rb") as file:
        content = file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise _FileLimitError(f"File {str(path)!r} exceeds the {max_bytes} byte read limit.")
    return content


def _is_below(path: str, root: str) -> bool:
    if root == ".":
        return True
    return PurePosixPath(path).is_relative_to(PurePosixPath(root))


def _search_match(path: str, line_number: int, line: str) -> SearchMatch:
    return SearchMatch(
        path=path,
        line_number=line_number,
        line=line[:_MAX_SEARCH_LINE_CHARS],
        line_truncated=len(line) > _MAX_SEARCH_LINE_CHARS,
    )

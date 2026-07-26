"""Integration tests for bounded filesystem tools."""

from __future__ import annotations

from repopilot.models import RepositoryCheckout
from repopilot.repository import RepositoryService
from repopilot.tool_models import (
    ListFilesRequest,
    ReadFileRequest,
    SearchTextRequest,
    ToolErrorCode,
)
from repopilot.tools.filesystem import FilesystemTools


def test_lists_only_requested_subtree(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    result = FilesystemTools(checkout, service).list_files(ListFilesRequest(root="src"))

    assert result.ok
    assert result.data is not None
    assert [entry.path for entry in result.data.entries] == ["src/module.py"]


def test_list_reports_requested_output_limit(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    result = FilesystemTools(checkout, service).list_files(ListFilesRequest(max_entries=1))

    assert not result.ok
    assert result.error is not None
    assert result.error.code is ToolErrorCode.LIMIT_EXCEEDED


def test_reads_requested_line_range(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    result = FilesystemTools(checkout, service).read_file(
        ReadFileRequest(path="alpha.txt", start_line=2, end_line=2)
    )

    assert result.ok
    assert result.data is not None
    assert result.data.content == "second line\n"
    assert result.data.end_line == 2


def test_read_rejects_traversal(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    result = FilesystemTools(checkout, service).read_file(ReadFileRequest(path="../secret"))

    assert result.error is not None
    assert result.error.code is ToolErrorCode.POLICY_DENIED


def test_read_rejects_large_and_binary_files(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    (checkout.path / "large.txt").write_text("too large")
    (checkout.path / "binary.dat").write_bytes(b"text\x00binary")
    tools = FilesystemTools(checkout, service)

    large = tools.read_file(ReadFileRequest(path="large.txt", max_bytes=2))
    binary = tools.read_file(ReadFileRequest(path="binary.dat"))

    assert large.error is not None
    assert large.error.code is ToolErrorCode.LIMIT_EXCEEDED
    assert binary.error is not None
    assert binary.error.code is ToolErrorCode.BINARY_FILE


def test_exact_search_is_bounded_and_reports_truncation(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    result = FilesystemTools(checkout, service).search_text(
        SearchTextRequest(query="hello", max_results=1)
    )

    assert result.ok
    assert result.data is not None
    assert len(result.data.matches) == 1
    assert result.data.truncated


def test_regex_search_runs_in_isolated_worker(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    result = FilesystemTools(checkout, service).search_text(
        SearchTextRequest(query=r"value\s*=\s*['\"]hello", root="src", regex=True)
    )

    assert result.ok
    assert result.data is not None
    assert result.data.matches[0].path == "src/module.py"


def test_invalid_regex_is_normalized(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    result = FilesystemTools(checkout, service).search_text(
        SearchTextRequest(query="(", regex=True)
    )

    assert result.error is not None
    assert result.error.code is ToolErrorCode.INVALID_INPUT


def test_pathological_regex_is_timed_out(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    (checkout.path / "expensive.txt").write_text("a" * 20_000 + "!")
    tools = FilesystemTools(checkout, service, regex_timeout_seconds=0.1)

    result = tools.search_text(SearchTextRequest(query=r"(a+)+$", regex=True))

    assert result.error is not None
    assert result.error.code is ToolErrorCode.TIMEOUT

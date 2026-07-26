"""Validated tool inputs and normalized tool outputs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from repopilot.models import FileEntry

_MAX_PATH_LENGTH = 4_096
_MAX_PATCH_BYTES = 1_048_576


class ToolName(StrEnum):
    """Names exposed by RepoPilot's tool layer."""

    LIST_FILES = "list_files"
    SEARCH_TEXT = "search_text"
    READ_FILE = "read_file"
    WRITE_PATCH = "write_patch"
    RUN_COMMAND = "run_command"
    GIT_DIFF = "git_diff"


class ToolErrorCode(StrEnum):
    """Stable error categories consumed by the future controller."""

    POLICY_DENIED = "policy_denied"
    NOT_FOUND = "not_found"
    INVALID_INPUT = "invalid_input"
    LIMIT_EXCEEDED = "limit_exceeded"
    BINARY_FILE = "binary_file"
    DECODE_ERROR = "decode_error"
    PATCH_REJECTED = "patch_rejected"
    TIMEOUT = "timeout"
    EXECUTION_ERROR = "execution_error"


@dataclass(frozen=True, slots=True)
class ToolError:
    """Structured details for an expected tool failure."""

    code: ToolErrorCode
    message: str


@dataclass(frozen=True, slots=True)
class ToolResult[ToolData]:
    """Normalized success or failure from one tool invocation."""

    tool_name: ToolName
    duration_ms: int
    data: ToolData | None = None
    error: ToolError | None = None

    def __post_init__(self) -> None:
        if (self.data is None) == (self.error is None):
            raise ValueError("ToolResult requires exactly one of data or error")

    @property
    def ok(self) -> bool:
        """Return whether the tool completed successfully."""
        return self.error is None


class _ToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ListFilesRequest(_ToolRequest):
    root: str = Field(default=".", min_length=1, max_length=_MAX_PATH_LENGTH)
    max_entries: int = Field(default=500, ge=1, le=5_000)


class SearchTextRequest(_ToolRequest):
    query: str = Field(min_length=1, max_length=512)
    root: str = Field(default=".", min_length=1, max_length=_MAX_PATH_LENGTH)
    regex: bool = False
    max_results: int = Field(default=100, ge=1, le=500)
    max_file_bytes: int = Field(default=262_144, ge=1, le=262_144)

    @field_validator("query")
    @classmethod
    def reject_nul_query(cls, value: str) -> str:
        if "\x00" in value:
            raise ValueError("query cannot contain NUL bytes")
        return value


class ReadFileRequest(_ToolRequest):
    path: str = Field(min_length=1, max_length=_MAX_PATH_LENGTH)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)
    max_bytes: int = Field(default=262_144, ge=1, le=262_144)

    @model_validator(mode="after")
    def validate_line_range(self) -> ReadFileRequest:
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class WritePatchRequest(_ToolRequest):
    patch: str = Field(min_length=1, max_length=_MAX_PATCH_BYTES)

    @field_validator("patch")
    @classmethod
    def enforce_patch_byte_limit(cls, value: str) -> str:
        if len(value.encode("utf-8")) > _MAX_PATCH_BYTES:
            raise ValueError(f"patch cannot exceed {_MAX_PATCH_BYTES} UTF-8 bytes")
        return value


class RunCommandRequest(_ToolRequest):
    argv: tuple[str, ...] = Field(min_length=1, max_length=64)
    cwd: str = Field(default=".", min_length=1, max_length=_MAX_PATH_LENGTH)
    timeout_seconds: float = Field(default=120, gt=0, le=120)

    @field_validator("argv")
    @classmethod
    def validate_arguments(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not argument or "\x00" in argument for argument in value):
            raise ValueError("command arguments must be non-empty and cannot contain NUL bytes")
        if any(len(argument) > _MAX_PATH_LENGTH for argument in value):
            raise ValueError(f"command arguments cannot exceed {_MAX_PATH_LENGTH} characters")
        return value


class GitDiffRequest(_ToolRequest):
    max_bytes: int = Field(default=_MAX_PATCH_BYTES, ge=1, le=_MAX_PATCH_BYTES)


@dataclass(frozen=True, slots=True)
class ListFilesData:
    entries: tuple[FileEntry, ...]


@dataclass(frozen=True, slots=True)
class SearchMatch:
    path: str
    line_number: int
    line: str
    line_truncated: bool


@dataclass(frozen=True, slots=True)
class SearchTextData:
    matches: tuple[SearchMatch, ...]
    truncated: bool
    skipped_files: int


@dataclass(frozen=True, slots=True)
class ReadFileData:
    path: str
    start_line: int
    end_line: int
    content: str


@dataclass(frozen=True, slots=True)
class WritePatchData:
    changed_paths: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GitDiffData:
    patch: str


@dataclass(frozen=True, slots=True)
class RunCommandData:
    argv: tuple[str, ...]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str

"""Provider-neutral model requests, outputs, and structured agent schemas."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from repopilot.tool_models import (
    GitDiffRequest,
    ListFilesRequest,
    ReadFileRequest,
    RunCommandRequest,
    SearchTextRequest,
    ToolName,
    WritePatchRequest,
)


class _BoundaryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ModelRequest(_BoundaryModel):
    operation: str = Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_]*$")
    instructions: str = Field(min_length=1, max_length=20_000)
    input: str = Field(min_length=1, max_length=200_000)


@dataclass(frozen=True, slots=True)
class ModelUsage:
    """Normalized token counts reported by a model provider."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        counts = (
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.cached_input_tokens,
            self.reasoning_tokens,
        )
        if any(count < 0 for count in counts):
            raise ValueError("model usage counts cannot be negative")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens plus output_tokens")
        if self.cached_input_tokens > self.input_tokens:
            raise ValueError("cached_input_tokens cannot exceed input_tokens")
        if self.reasoning_tokens > self.output_tokens:
            raise ValueError("reasoning_tokens cannot exceed output_tokens")


@dataclass(frozen=True, slots=True)
class ModelResponse[OutputT: BaseModel]:
    output: OutputT
    model_name: str
    usage: ModelUsage | None = None
    provider_response_id: str | None = None


class PlanStep(_BoundaryModel):
    id: str = Field(min_length=1, max_length=32, pattern=r"^[a-z][a-z0-9_-]*$")
    objective: str = Field(min_length=1, max_length=500)
    files: tuple[str, ...] = Field(max_length=20)
    verification: tuple[str, ...] = Field(min_length=1, max_length=10)


class ImplementationPlan(_BoundaryModel):
    summary: str = Field(min_length=1, max_length=1_000)
    steps: tuple[PlanStep, ...] = Field(min_length=1, max_length=12)
    assumptions: tuple[str, ...] = Field(max_length=10)

    @model_validator(mode="after")
    def require_unique_step_ids(self) -> ImplementationPlan:
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("plan step ids must be unique")
        return self


class ListFilesCall(_BoundaryModel):
    call_id: str = Field(min_length=1, max_length=64)
    tool_name: Literal[ToolName.LIST_FILES]
    arguments: ListFilesRequest


class SearchTextCall(_BoundaryModel):
    call_id: str = Field(min_length=1, max_length=64)
    tool_name: Literal[ToolName.SEARCH_TEXT]
    arguments: SearchTextRequest


class ReadFileCall(_BoundaryModel):
    call_id: str = Field(min_length=1, max_length=64)
    tool_name: Literal[ToolName.READ_FILE]
    arguments: ReadFileRequest


class WritePatchCall(_BoundaryModel):
    call_id: str = Field(min_length=1, max_length=64)
    tool_name: Literal[ToolName.WRITE_PATCH]
    arguments: WritePatchRequest


class RunCommandCall(_BoundaryModel):
    call_id: str = Field(min_length=1, max_length=64)
    tool_name: Literal[ToolName.RUN_COMMAND]
    arguments: RunCommandRequest


class GitDiffCall(_BoundaryModel):
    call_id: str = Field(min_length=1, max_length=64)
    tool_name: Literal[ToolName.GIT_DIFF]
    arguments: GitDiffRequest


type ModelToolCall = Annotated[
    ListFilesCall | SearchTextCall | ReadFileCall | WritePatchCall | RunCommandCall | GitDiffCall,
    Field(discriminator="tool_name"),
]


class ToolCallOutput(_BoundaryModel):
    """Structured model output containing one validated tool invocation."""

    tool_call: ModelToolCall

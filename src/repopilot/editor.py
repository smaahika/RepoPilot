"""Model-driven selection of one validated repository tool call."""

from __future__ import annotations

import json
from dataclasses import asdict

from pydantic import BaseModel, ConfigDict, Field

from repopilot.model_client import ModelClient
from repopilot.model_models import (
    ImplementationPlan,
    ModelRequest,
    ModelResponse,
    Reflection,
    ToolCallOutput,
)
from repopilot.tool_executor import AnyToolResult

_MAX_OBSERVATION_CHARS = 50_000
_EDITOR_INSTRUCTIONS = """Implement the task by selecting exactly one available tool call.
Use repository evidence from prior tool results; do not invent file contents.
Read or search before editing when needed, and use write_patch only for a grounded change.
The controller decides state transitions and verification; you only select the next tool."""


class ToolObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    call_id: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(min_length=1, max_length=64)
    ok: bool
    output: str = Field(max_length=_MAX_OBSERVATION_CHARS)
    truncated: bool

    @classmethod
    def from_result(cls, call_id: str, result: AnyToolResult) -> ToolObservation:
        payload = result.data if result.ok else result.error
        assert payload is not None
        serialized = json.dumps(asdict(payload), ensure_ascii=False, separators=(",", ":"))
        truncated = len(serialized) > _MAX_OBSERVATION_CHARS
        if truncated:
            serialized = serialized[:_MAX_OBSERVATION_CHARS]
        return cls(
            call_id=call_id,
            tool_name=result.tool_name.value,
            ok=result.ok,
            output=serialized,
            truncated=truncated,
        )


class EditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    task: str = Field(min_length=1, max_length=10_000)
    plan: ImplementationPlan
    observations: tuple[ToolObservation, ...] = Field(max_length=20)
    reflection: Reflection | None = None


class Editor:
    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def next_tool_call(self, request: EditRequest) -> ModelResponse[ToolCallOutput]:
        """Ask for one structured action using bounded execution history."""
        return self._model.generate(
            ModelRequest(
                operation="select_tool",
                instructions=_EDITOR_INSTRUCTIONS,
                input=request.model_dump_json(),
            ),
            ToolCallOutput,
        )

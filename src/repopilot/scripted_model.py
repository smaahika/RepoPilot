"""Deterministic model implementation for orchestration tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from repopilot.errors import ModelOutputError, ModelScriptExhaustedError
from repopilot.model_models import ModelRequest, ModelResponse, ModelUsage

type ScriptedOutput = BaseModel | Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ScriptedResponse:
    output: ScriptedOutput
    usage: ModelUsage | None = None
    model_name: str = "scripted"


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    request: ModelRequest
    output_type: type[BaseModel]


class ScriptedModel:
    """Return queued values while preserving model-boundary validation."""

    def __init__(self, responses: Iterable[ScriptedOutput | ScriptedResponse | Exception]) -> None:
        self._responses = deque(responses)
        self.invocations: list[ModelInvocation] = []

    def generate[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_type: type[OutputT],
    ) -> ModelResponse[OutputT]:
        self.invocations.append(ModelInvocation(request=request, output_type=output_type))
        if not self._responses:
            raise ModelScriptExhaustedError("Scripted model has no response for this invocation.")

        scripted = self._responses.popleft()
        if isinstance(scripted, Exception):
            raise scripted

        if isinstance(scripted, ScriptedResponse):
            scripted_output = scripted.output
            response_usage = scripted.usage
            model_name = scripted.model_name
        else:
            scripted_output = scripted
            response_usage = None
            model_name = "scripted"

        candidate = (
            scripted_output.model_dump()
            if isinstance(scripted_output, BaseModel)
            else scripted_output
        )
        try:
            output = output_type.model_validate(candidate)
        except ValidationError as error:
            raise ModelOutputError("Scripted model response failed schema validation.") from error

        return ModelResponse(output=output, model_name=model_name, usage=response_usage)

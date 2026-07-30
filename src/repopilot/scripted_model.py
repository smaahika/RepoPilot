"""Deterministic model implementation for orchestration tests."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ValidationError

from repopilot.errors import ModelOutputError, ModelScriptExhaustedError
from repopilot.model_models import ModelRequest, ModelResponse


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    request: ModelRequest
    output_type: type[BaseModel]


class ScriptedModel:
    """Return queued values while preserving model-boundary validation."""

    def __init__(self, responses: Iterable[BaseModel | Mapping[str, Any] | Exception]) -> None:
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

        candidate = scripted.model_dump() if isinstance(scripted, BaseModel) else scripted
        try:
            output = output_type.model_validate(candidate)
        except ValidationError as error:
            raise ModelOutputError("Scripted model response failed schema validation.") from error

        return ModelResponse(output=output, model_name="scripted")

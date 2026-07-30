"""Provider-neutral structured model interface."""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel

from repopilot.model_models import ModelRequest, ModelResponse


class ModelClient(Protocol):
    """Generate a response validated as the caller's requested schema."""

    def generate[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_type: type[OutputT],
    ) -> ModelResponse[OutputT]: ...

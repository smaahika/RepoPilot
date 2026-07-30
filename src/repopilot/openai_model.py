"""OpenAI Responses API adapter for structured model generation."""

from __future__ import annotations

from typing import Literal

from openai import OpenAI, OpenAIError
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from repopilot.errors import ModelOutputError, ModelTransportError
from repopilot.model_models import ModelRequest, ModelResponse, ModelUsage


class OpenAIModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    model: str = Field(default="gpt-5.6-sol", min_length=1, max_length=128)
    reasoning_effort: Literal["none", "low", "medium", "high", "xhigh", "max"] = "medium"
    max_output_tokens: int = Field(default=8_000, ge=1, le=100_000)
    timeout_seconds: float = Field(default=120, gt=0, le=300)


class OpenAIResponsesModel:
    """Generate Pydantic outputs through OpenAI's Responses API."""

    def __init__(self, client: OpenAI, config: OpenAIModelConfig | None = None) -> None:
        self._client = client.with_options(max_retries=0)
        self._config = config or OpenAIModelConfig()

    def generate[OutputT: BaseModel](
        self,
        request: ModelRequest,
        output_type: type[OutputT],
    ) -> ModelResponse[OutputT]:
        try:
            response = self._client.responses.parse(
                model=self._config.model,
                instructions=request.instructions,
                input=request.input,
                text_format=output_type,
                reasoning={"effort": self._config.reasoning_effort},
                max_output_tokens=self._config.max_output_tokens,
                metadata={"operation": request.operation},
                store=False,
                timeout=self._config.timeout_seconds,
            )
        except ValidationError as error:
            raise ModelOutputError("OpenAI output failed schema validation.") from error
        except OpenAIError as error:
            raise ModelTransportError("OpenAI request failed.") from error

        if response.output_parsed is None:
            raise ModelOutputError("OpenAI returned no structured output.")

        try:
            output = output_type.model_validate(response.output_parsed)
        except ValidationError as error:
            raise ModelOutputError("OpenAI output failed schema validation.") from error

        usage = None
        if response.usage is not None:
            try:
                usage = ModelUsage(
                    input_tokens=response.usage.input_tokens,
                    output_tokens=response.usage.output_tokens,
                    total_tokens=response.usage.total_tokens,
                    cached_input_tokens=response.usage.input_tokens_details.cached_tokens,
                    reasoning_tokens=response.usage.output_tokens_details.reasoning_tokens,
                )
            except ValueError as error:
                raise ModelOutputError("OpenAI returned invalid usage data.") from error

        return ModelResponse(
            output=output,
            model_name=response.model,
            usage=usage,
            provider_response_id=response.id,
        )

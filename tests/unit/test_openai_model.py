"""Tests for the OpenAI structured Responses adapter."""

from types import SimpleNamespace
from typing import Self, cast

import httpx
import pytest
from openai import APIConnectionError, OpenAI

from repopilot.errors import ModelOutputError, ModelTransportError
from repopilot.model_models import ImplementationPlan, ModelRequest, PlanStep
from repopilot.openai_model import OpenAIModelConfig, OpenAIResponsesModel


class _FakeResponses:
    def __init__(self, response: object = None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.kwargs: dict[str, object] | None = None

    def parse(self, **kwargs: object) -> object:
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return self.response


class _FakeOpenAI:
    def __init__(self, responses: _FakeResponses) -> None:
        self.responses = responses
        self.max_retries: int | None = None

    def with_options(self, *, max_retries: int) -> Self:
        self.max_retries = max_retries
        return self


def _request() -> ModelRequest:
    return ModelRequest(operation="create_plan", instructions="Plan safely.", input="Task context")


def _plan() -> ImplementationPlan:
    return ImplementationPlan(
        summary="Implement and test.",
        steps=(
            PlanStep(
                id="implement",
                objective="Make the requested change.",
                files=("src/app.py",),
                verification=("pytest",),
            ),
        ),
        assumptions=(),
    )


def test_adapter_requests_structured_output_and_normalizes_usage() -> None:
    parsed = _plan()
    response = SimpleNamespace(
        output_parsed=parsed,
        model="gpt-5.6-sol",
        id="resp-123",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=40,
            total_tokens=140,
            input_tokens_details=SimpleNamespace(cached_tokens=25),
            output_tokens_details=SimpleNamespace(reasoning_tokens=15),
        ),
    )
    responses = _FakeResponses(response=response)
    fake_client = _FakeOpenAI(responses)
    client = cast(OpenAI, fake_client)
    adapter = OpenAIResponsesModel(client)

    result = adapter.generate(_request(), ImplementationPlan)

    assert result.output == parsed
    assert result.provider_response_id == "resp-123"
    assert result.usage is not None
    assert result.usage.cached_input_tokens == 25
    assert fake_client.max_retries == 0
    assert responses.kwargs == {
        "model": "gpt-5.6-sol",
        "instructions": "Plan safely.",
        "input": "Task context",
        "text_format": ImplementationPlan,
        "reasoning": {"effort": "medium"},
        "max_output_tokens": 8_000,
        "metadata": {"operation": "create_plan"},
        "store": False,
        "timeout": 120,
    }


def test_adapter_rejects_missing_parsed_output() -> None:
    response = SimpleNamespace(output_parsed=None)
    adapter = OpenAIResponsesModel(cast(OpenAI, _FakeOpenAI(_FakeResponses(response=response))))

    with pytest.raises(ModelOutputError, match="no structured output"):
        adapter.generate(_request(), ImplementationPlan)


def test_adapter_translates_openai_failures() -> None:
    provider_error = APIConnectionError(request=httpx.Request("POST", "https://api.openai.com"))
    responses = _FakeResponses(error=provider_error)
    adapter = OpenAIResponsesModel(cast(OpenAI, _FakeOpenAI(responses)))

    with pytest.raises(ModelTransportError, match="OpenAI request failed") as raised:
        adapter.generate(_request(), ImplementationPlan)

    assert raised.value.__cause__ is provider_error


def test_adapter_rejects_inconsistent_usage() -> None:
    response = SimpleNamespace(
        output_parsed=_plan(),
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=40,
            total_tokens=100,
            input_tokens_details=SimpleNamespace(cached_tokens=0),
            output_tokens_details=SimpleNamespace(reasoning_tokens=0),
        ),
    )
    adapter = OpenAIResponsesModel(cast(OpenAI, _FakeOpenAI(_FakeResponses(response=response))))

    with pytest.raises(ModelOutputError, match="invalid usage"):
        adapter.generate(_request(), ImplementationPlan)


def test_adapter_accepts_bounded_configuration() -> None:
    config = OpenAIModelConfig(
        model="gpt-5.6-terra",
        reasoning_effort="low",
        max_output_tokens=500,
        timeout_seconds=30,
    )

    assert config.model == "gpt-5.6-terra"

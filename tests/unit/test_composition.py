"""Tests for production dependency composition."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from repopilot.application import PersistingRunApplication
from repopilot.config import ExecutionBackend, RuntimeConfig
from repopilot.controller import RunController
from repopilot.openai_model import OpenAIModelConfig


def test_builds_controller_with_explicit_provider_secret(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, str] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str) -> None:
            captured["api_key"] = api_key

        def with_options(self, *, max_retries: int) -> FakeOpenAI:
            captured["max_retries"] = str(max_retries)
            return self

    monkeypatch.setattr("repopilot.composition.OpenAI", FakeOpenAI)
    config = RuntimeConfig(
        api_key=SecretStr("provider-secret"),
        run_root=tmp_path,
        model=OpenAIModelConfig(model="gpt-test"),
        execution_backend=ExecutionBackend.DOCKER,
    )

    from repopilot.composition import build_application, build_controller

    controller = build_controller(config)
    application = build_application(config)

    assert isinstance(controller, RunController)
    assert isinstance(application, PersistingRunApplication)
    assert captured == {"api_key": "provider-secret", "max_retries": "0"}

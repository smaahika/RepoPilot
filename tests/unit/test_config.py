"""Tests for runtime configuration loading and secret handling."""

from pathlib import Path

import pytest

from repopilot.config import load_runtime_config
from repopilot.errors import ConfigurationError


def test_loads_bounded_provider_settings_from_environment(tmp_path: Path) -> None:
    config = load_runtime_config(
        {
            "OPENAI_API_KEY": "provider-secret",
            "REPOPILOT_RUN_ROOT": str(tmp_path),
            "REPOPILOT_MODEL": "gpt-test",
            "REPOPILOT_REASONING_EFFORT": "high",
            "REPOPILOT_MAX_OUTPUT_TOKENS": "4096",
            "REPOPILOT_MODEL_TIMEOUT_SECONDS": "30",
        }
    )

    assert config.run_root == tmp_path.resolve()
    assert config.model.model == "gpt-test"
    assert config.model.reasoning_effort == "high"
    assert config.model.max_output_tokens == 4096
    assert config.model.timeout_seconds == 30
    assert "provider-secret" not in repr(config)


def test_explicit_overrides_take_precedence(tmp_path: Path) -> None:
    override_root = tmp_path / "override"

    config = load_runtime_config(
        {
            "OPENAI_API_KEY": "provider-secret",
            "REPOPILOT_RUN_ROOT": str(tmp_path / "environment"),
            "REPOPILOT_MODEL": "environment-model",
        },
        run_root=override_root,
        model="argument-model",
    )

    assert config.run_root == override_root.resolve()
    assert config.model.model == "argument-model"


def test_invalid_provider_setting_is_sanitized() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        load_runtime_config(
            {
                "OPENAI_API_KEY": "provider-secret",
                "REPOPILOT_MAX_OUTPUT_TOKENS": "unbounded",
            }
        )

    message = str(exc_info.value)
    assert "max_output_tokens" in message
    assert "provider-secret" not in message


@pytest.mark.parametrize("name", ["REPOPILOT_RUN_ROOT", "REPOPILOT_MODEL"])
def test_rejects_empty_optional_setting(name: str) -> None:
    with pytest.raises(ConfigurationError, match=f"{name} cannot be empty"):
        load_runtime_config({"OPENAI_API_KEY": "provider-secret", name: " "})

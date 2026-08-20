"""Validated environment and provider configuration."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError

from repopilot.errors import ConfigurationError
from repopilot.openai_model import OpenAIModelConfig


class RuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    api_key: SecretStr
    run_root: Path
    model: OpenAIModelConfig


def load_runtime_config(
    environ: Mapping[str, str] | None = None,
    *,
    run_root: Path | None = None,
    model: str | None = None,
) -> RuntimeConfig:
    """Load secrets and bounded runtime settings without mutating the environment."""
    values = os.environ if environ is None else environ
    api_key = values.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise ConfigurationError("OPENAI_API_KEY is required to run RepoPilot.")

    selected_root = run_root or _environment_path(values, "REPOPILOT_RUN_ROOT")
    if selected_root is None:
        selected_root = Path.home() / ".repopilot"

    model_values: dict[str, object] = {}
    _copy_setting(values, model_values, "REPOPILOT_REASONING_EFFORT", "reasoning_effort")
    _copy_setting(values, model_values, "REPOPILOT_MAX_OUTPUT_TOKENS", "max_output_tokens")
    _copy_setting(values, model_values, "REPOPILOT_MODEL_TIMEOUT_SECONDS", "timeout_seconds")
    selected_model = model if model is not None else _environment_text(values, "REPOPILOT_MODEL")
    if selected_model is not None:
        model_values["model"] = selected_model

    try:
        return RuntimeConfig(
            api_key=SecretStr(api_key),
            run_root=selected_root.expanduser().resolve(),
            model=OpenAIModelConfig.model_validate(model_values),
        )
    except (OSError, RuntimeError, ValidationError) as error:
        raise ConfigurationError(_configuration_message(error)) from error


def _environment_text(values: Mapping[str, str], name: str) -> str | None:
    value = values.get(name)
    if value is None:
        return None
    value = value.strip()
    if not value:
        raise ConfigurationError(f"{name} cannot be empty when set.")
    return value


def _environment_path(values: Mapping[str, str], name: str) -> Path | None:
    value = _environment_text(values, name)
    return None if value is None else Path(value)


def _copy_setting(
    values: Mapping[str, str],
    destination: dict[str, object],
    environment_name: str,
    field_name: str,
) -> None:
    value = _environment_text(values, environment_name)
    if value is not None:
        destination[field_name] = value


def _configuration_message(error: OSError | RuntimeError | ValidationError) -> str:
    if isinstance(error, ValidationError):
        issue = error.errors(include_url=False, include_input=False)[0]
        field = ".".join(str(part) for part in issue["loc"])
        return f"Invalid RepoPilot configuration for {field}: {issue['msg']}."
    return f"Invalid RepoPilot run root: {error}."

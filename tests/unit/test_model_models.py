"""Tests for structured plan and model tool-call schemas."""

import pytest
from pydantic import TypeAdapter, ValidationError

from repopilot.model_models import (
    ImplementationPlan,
    ModelToolCall,
    RunCommandCall,
    ToolCallOutput,
)


def test_plan_requires_unique_step_ids() -> None:
    plan = {
        "summary": "Make the change safely.",
        "steps": [
            {
                "id": "inspect",
                "objective": "Inspect the implementation.",
                "files": ["src/app.py"],
                "verification": ["Read the relevant tests."],
            },
            {
                "id": "inspect",
                "objective": "Implement the change.",
                "files": ["src/app.py"],
                "verification": ["pytest"],
            },
        ],
        "assumptions": [],
    }

    with pytest.raises(ValidationError, match="step ids must be unique"):
        ImplementationPlan.model_validate(plan)


def test_tool_call_discriminator_validates_specific_arguments() -> None:
    call: ModelToolCall = TypeAdapter(ModelToolCall).validate_python(
        {
            "call_id": "call-1",
            "tool_name": "run_command",
            "arguments": {"argv": ["pytest"], "timeout_seconds": 30},
        }
    )

    assert isinstance(call, RunCommandCall)
    assert call.arguments.argv == ("pytest",)


def test_tool_call_rejects_arguments_for_a_different_tool() -> None:
    with pytest.raises(ValidationError, match="path"):
        TypeAdapter(ModelToolCall).validate_python(
            {
                "call_id": "call-1",
                "tool_name": "read_file",
                "arguments": {"argv": ["pytest"]},
            }
        )


def test_tool_call_output_is_a_structured_generation_schema() -> None:
    output = ToolCallOutput.model_validate(
        {
            "tool_call": {
                "call_id": "call-2",
                "tool_name": "read_file",
                "arguments": {"path": "src/app.py", "start_line": 1, "end_line": 20},
            }
        }
    )

    assert output.tool_call.tool_name == "read_file"

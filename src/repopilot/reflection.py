"""Structured diagnosis of failed verification attempts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from repopilot.model_client import ModelClient
from repopilot.model_models import (
    ImplementationPlan,
    ModelRequest,
    ModelResponse,
    Reflection,
)
from repopilot.verification import CheckKind, VerificationResult, VerificationStatus

_MAX_PATCH_CHARS = 50_000
_MAX_OUTPUT_CHARS = 20_000
_REFLECTION_INSTRUCTIONS = """Diagnose why repository verification failed.
Use only the supplied plan, visible diff, and bounded command evidence.
Return one concrete correction for the next edit turn; do not request a state transition."""


class ReflectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    task: str = Field(min_length=1, max_length=10_000)
    plan: ImplementationPlan
    patch: str = Field(max_length=_MAX_PATCH_CHARS)
    status: VerificationStatus
    check_kind: CheckKind
    message: str = Field(min_length=1, max_length=2_000)
    stdout: str = Field(max_length=_MAX_OUTPUT_CHARS)
    stderr: str = Field(max_length=_MAX_OUTPUT_CHARS)

    @classmethod
    def from_verification(
        cls,
        task: str,
        plan: ImplementationPlan,
        patch: str,
        verification: VerificationResult,
    ) -> ReflectionRequest:
        return cls(
            task=task,
            plan=plan,
            patch=patch[:_MAX_PATCH_CHARS],
            status=verification.status,
            check_kind=verification.check_kind,
            message=verification.message,
            stdout=verification.stdout[:_MAX_OUTPUT_CHARS],
            stderr=verification.stderr[:_MAX_OUTPUT_CHARS],
        )


class Reflector:
    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def reflect(self, request: ReflectionRequest) -> ModelResponse[Reflection]:
        """Generate one structured correction from failed verification evidence."""
        return self._model.generate(
            ModelRequest(
                operation="reflect_on_failure",
                instructions=_REFLECTION_INSTRUCTIONS,
                input=request.model_dump_json(),
            ),
            Reflection,
        )

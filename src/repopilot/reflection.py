"""Structured diagnosis of failed verification attempts."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from repopilot.context import ContextSession
from repopilot.model_client import ModelClient
from repopilot.model_models import (
    ImplementationPlan,
    ModelRequest,
    ModelResponse,
    Reflection,
)
from repopilot.verification import CheckKind, VerificationResult, VerificationStatus

_MAX_EVIDENCE_CHARS = 1_048_576
_REFLECTION_INSTRUCTIONS = """Diagnose why repository verification failed.
Use only the supplied plan, visible diff, and bounded command evidence.
Respect the evidence-compaction flags and do not assume omitted content supports a diagnosis.
Return one concrete correction for the next edit turn; do not request a state transition."""


class ReflectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    task: str = Field(min_length=1, max_length=10_000)
    plan: ImplementationPlan
    patch: str = Field(max_length=_MAX_EVIDENCE_CHARS)
    status: VerificationStatus
    check_kind: CheckKind
    message: str = Field(min_length=1, max_length=2_000)
    stdout: str = Field(max_length=_MAX_EVIDENCE_CHARS)
    stderr: str = Field(max_length=_MAX_EVIDENCE_CHARS)

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
            patch=patch,
            status=verification.status,
            check_kind=verification.check_kind,
            message=verification.message,
            stdout=verification.stdout,
            stderr=verification.stderr,
        )


class Reflector:
    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def reflect(
        self,
        request: ReflectionRequest,
        *,
        context: ContextSession | None = None,
    ) -> ModelResponse[Reflection]:
        """Generate one structured correction from failed verification evidence."""
        session = context or ContextSession()
        return self._model.generate(
            ModelRequest(
                operation="reflect_on_failure",
                instructions=_REFLECTION_INSTRUCTIONS,
                input=session.reflection_input(
                    request.task,
                    request.plan,
                    request.patch,
                    status=request.status.value,
                    check_kind=request.check_kind.value,
                    message=request.message,
                    stdout=request.stdout,
                    stderr=request.stderr,
                ),
            ),
            Reflection,
        )

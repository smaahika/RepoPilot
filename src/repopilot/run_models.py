"""Validated run inputs and provider-neutral controller results."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from repopilot.model_models import ImplementationPlan, ModelUsage, Reflection
from repopilot.state_machine import RunEvent, RunPhase
from repopilot.tool_models import RunCommandRequest
from repopilot.verification import VerificationResult


class _RunModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class LocalRepositorySource(_RunModel):
    kind: Literal["local"] = "local"
    path: Path


class PublicRepositorySource(_RunModel):
    kind: Literal["public"] = "public"
    url: str = Field(min_length=1, max_length=2_048)


type RepositorySource = Annotated[
    LocalRepositorySource | PublicRepositorySource,
    Field(discriminator="kind"),
]


class RunBudgets(_RunModel):
    max_runtime_seconds: float = Field(default=600, gt=0, le=3_600)
    max_model_calls: int = Field(default=8, ge=1, le=50)
    max_tool_calls: int = Field(default=20, ge=1, le=100)
    max_iterations: int = Field(default=3, ge=1, le=10)


class RunRequest(_RunModel):
    source: RepositorySource
    task: str = Field(min_length=1, max_length=10_000)
    verification: RunCommandRequest | None = None
    budgets: RunBudgets = Field(default_factory=RunBudgets)
    run_id: str | None = Field(default=None, min_length=1, max_length=64)


class TerminationReason(StrEnum):
    SUCCESS = "success"
    INITIALIZATION_FAILED = "initialization_failed"
    INSPECTION_FAILED = "inspection_failed"
    PLANNING_FAILED = "planning_failed"
    EDIT_FAILED = "edit_failed"
    VERIFICATION_FAILED = "verification_failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_PROGRESS = "no_progress"
    CLEANUP_FAILED = "cleanup_failed"
    LOGGING_FAILED = "logging_failed"
    INTERNAL_ERROR = "internal_error"


@dataclass(frozen=True, slots=True)
class RunCounters:
    model_calls: int
    tool_calls: int
    iterations: int
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class TransitionRecord:
    run_id: str
    sequence: int
    previous_phase: RunPhase
    event: RunEvent
    next_phase: RunPhase
    elapsed_ms: int


@dataclass(frozen=True, slots=True)
class RunResult:
    run_id: str
    phase: RunPhase
    termination_reason: TerminationReason
    plan: ImplementationPlan | None
    patch: str
    verifications: tuple[VerificationResult, ...]
    reflections: tuple[Reflection, ...]
    counters: RunCounters
    usage: ModelUsage | None
    transitions: tuple[TransitionRecord, ...]
    failure_message: str | None = None

    def __post_init__(self) -> None:
        if self.phase not in (RunPhase.COMPLETE, RunPhase.FAILED):
            raise ValueError("RunResult requires a terminal phase")
        if self.phase is RunPhase.COMPLETE:
            if self.termination_reason is not TerminationReason.SUCCESS:
                raise ValueError("Completed runs require the success termination reason")
            if self.failure_message is not None:
                raise ValueError("Completed runs cannot contain a failure message")
        elif self.termination_reason is TerminationReason.SUCCESS or self.failure_message is None:
            raise ValueError("Failed runs require a failure reason and message")

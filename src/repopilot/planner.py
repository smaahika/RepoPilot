"""Structured implementation planning independent of model providers."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from repopilot.context import ContextSession
from repopilot.model_client import ModelClient
from repopilot.model_models import ImplementationPlan, ModelRequest, ModelResponse
from repopilot.models import RepositoryInventory

_PLANNER_INSTRUCTIONS = """You plan small, safe repository changes.
Return an ordered implementation plan grounded only in the task and ranked inventory subset.
Use the inventory summary to recognize when paths were omitted and preserve that uncertainty.
Every step must name its objective, likely files, and concrete verification commands or checks.
Do not claim to have read file contents, and record any uncertainty as an assumption."""


class PlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    task: str = Field(min_length=1, max_length=10_000)
    inventory: RepositoryInventory


class Planner:
    def __init__(self, model: ModelClient) -> None:
        self._model = model

    def create_plan(
        self,
        request: PlanningRequest,
        *,
        context: ContextSession | None = None,
    ) -> ModelResponse[ImplementationPlan]:
        """Build and execute one structured planning request."""
        session = context or ContextSession()
        return self._model.generate(
            ModelRequest(
                operation="create_plan",
                instructions=_PLANNER_INSTRUCTIONS,
                input=session.planning_input(request.task, request.inventory),
            ),
            ImplementationPlan,
        )

"""Deterministic run orchestration with bounded verification retries."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import BaseModel, ValidationError

from repopilot.editor import Editor, EditRequest, ToolObservation
from repopilot.errors import (
    ControllerToolError,
    NoProgressError,
    RepoPilotError,
    RunBudgetExceededError,
    VerificationError,
)
from repopilot.model_client import ModelClient
from repopilot.model_models import (
    ImplementationPlan,
    ModelResponse,
    ModelUsage,
    Reflection,
    WritePatchCall,
)
from repopilot.models import RepositoryCheckout, RunWorkspace
from repopilot.planner import Planner, PlanningRequest
from repopilot.reflection import ReflectionRequest, Reflector
from repopilot.repository import RepositoryService
from repopilot.run_logging import NullRunLogger, RunLogger
from repopilot.run_models import (
    LocalRepositorySource,
    RunBudgets,
    RunCounters,
    RunRequest,
    RunResult,
    TerminationReason,
    TransitionRecord,
)
from repopilot.state_machine import RunEvent, RunPhase, RunStateMachine
from repopilot.tool_executor import AnyToolResult, ToolExecutor
from repopilot.tool_models import GitDiffRequest
from repopilot.tools.shell import CommandPolicy
from repopilot.verification import VerificationResult, normalize_command, verify_diff
from repopilot.workspace import WorkspaceManager

_MAX_RECENT_OBSERVATIONS = 3


class RunController:
    """Own run state, budgets, model calls, tools, retries, and termination."""

    def __init__(
        self,
        workspaces: WorkspaceManager,
        repository: RepositoryService,
        model: ModelClient,
        *,
        logger: RunLogger | None = None,
        command_policy: CommandPolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._workspaces = workspaces
        self._repository = repository
        self._planner = Planner(model)
        self._editor = Editor(model)
        self._reflector = Reflector(model)
        self._logger = logger or NullRunLogger()
        self._command_policy = command_policy
        self._clock = clock

    def run(self, request: RunRequest) -> RunResult:
        machine = RunStateMachine()
        tracker = _BudgetTracker(request.budgets, self._clock)
        usage = _UsageAccumulator()
        transitions: list[TransitionRecord] = []
        observations: list[ToolObservation] = []
        verifications: list[VerificationResult] = []
        reflections: list[Reflection] = []
        workspace: RunWorkspace | None = None
        plan: ImplementationPlan | None = None
        current_reflection: Reflection | None = None
        previous_failed_patch: str | None = None
        patch = ""
        termination_reason: TerminationReason | None = None
        failure_message: str | None = None
        run_id = request.run_id or "unallocated"

        try:
            workspace = self._workspaces.create(request.run_id)
            run_id = workspace.run_id
            self._advance(machine, RunEvent.WORKSPACE_READY, run_id, tracker, transitions)

            checkout = self._prepare_repository(request, workspace)
            inventory = self._repository.inventory(checkout)
            tracker.check_runtime()
            self._advance(machine, RunEvent.INVENTORY_READY, run_id, tracker, transitions)

            tracker.consume_model_call()
            plan_response = self._planner.create_plan(
                PlanningRequest(task=request.task, inventory=inventory)
            )
            usage.add(plan_response)
            plan = plan_response.output
            tracker.check_runtime()
            self._advance(machine, RunEvent.PLAN_READY, run_id, tracker, transitions)

            executor = ToolExecutor(checkout, self._repository, self._command_policy)
            while True:
                while machine.phase is RunPhase.EDIT:
                    tracker.consume_model_call()
                    action_response = self._editor.next_tool_call(
                        EditRequest(
                            task=request.task,
                            plan=plan,
                            observations=tuple(observations[-_MAX_RECENT_OBSERVATIONS:]),
                            reflection=current_reflection,
                        )
                    )
                    usage.add(action_response)
                    tracker.check_runtime()
                    call = action_response.output.tool_call

                    tracker.consume_tool_call()
                    tool_result = executor.execute(call)
                    tracker.check_runtime()
                    observations.append(ToolObservation.from_result(call.call_id, tool_result))
                    self._require_tool_success(tool_result)

                    if isinstance(call, WritePatchCall):
                        tracker.consume_iteration()
                        self._advance(
                            machine,
                            RunEvent.PATCH_APPLIED,
                            run_id,
                            tracker,
                            transitions,
                        )
                    else:
                        self._advance(
                            machine,
                            RunEvent.TOOL_COMPLETED,
                            run_id,
                            tracker,
                            transitions,
                        )

                tracker.consume_tool_call()
                diff_result = executor.diff(GitDiffRequest())
                self._require_tool_success(diff_result)
                assert diff_result.data is not None
                patch = diff_result.data.patch

                verification = verify_diff(patch)
                if verification.passed and request.verification is not None:
                    tracker.consume_tool_call()
                    command_result = executor.run_command(request.verification)
                    observations.append(
                        ToolObservation.from_result(
                            f"verify-{tracker.iterations}",
                            command_result,
                        )
                    )
                    verification = normalize_command(
                        command_result,
                        request.verification.argv,
                    )
                verifications.append(verification)
                tracker.check_runtime()

                if verification.passed:
                    break
                if not verification.retryable:
                    raise VerificationError(verification.message)
                if previous_failed_patch is not None and patch == previous_failed_patch:
                    raise NoProgressError(
                        "Two consecutive failed iterations produced the same repository diff."
                    )
                previous_failed_patch = patch
                tracker.require_retry_available()
                self._advance(
                    machine,
                    RunEvent.VERIFICATION_FAILED,
                    run_id,
                    tracker,
                    transitions,
                )

                tracker.consume_model_call()
                reflection_response = self._reflector.reflect(
                    ReflectionRequest.from_verification(
                        request.task,
                        plan,
                        patch,
                        verification,
                    )
                )
                usage.add(reflection_response)
                current_reflection = reflection_response.output
                reflections.append(current_reflection)
                tracker.check_runtime()
                self._advance(
                    machine,
                    RunEvent.REFLECTION_READY,
                    run_id,
                    tracker,
                    transitions,
                )
        except (RepoPilotError, OSError, ValidationError) as error:
            termination_reason = _termination_reason(machine.phase, error)
            failure_message = str(error)
            if machine.phase not in (RunPhase.COMPLETE, RunPhase.FAILED):
                self._advance(machine, RunEvent.FAILED, run_id, tracker, transitions)

        if workspace is not None:
            try:
                self._workspaces.cleanup(workspace)
            except (RepoPilotError, OSError) as error:
                if termination_reason is None:
                    termination_reason = TerminationReason.CLEANUP_FAILED
                    failure_message = f"Workspace cleanup failed: {error}"
                    self._advance(machine, RunEvent.FAILED, run_id, tracker, transitions)
                else:
                    failure_message = f"{failure_message} Workspace cleanup also failed: {error}"

        if termination_reason is None:
            try:
                tracker.check_runtime()
            except RunBudgetExceededError as error:
                termination_reason = TerminationReason.BUDGET_EXHAUSTED
                failure_message = str(error)
                self._advance(machine, RunEvent.FAILED, run_id, tracker, transitions)
            else:
                termination_reason = TerminationReason.SUCCESS
                self._advance(
                    machine,
                    RunEvent.VERIFICATION_PASSED,
                    run_id,
                    tracker,
                    transitions,
                )

        assert termination_reason is not None
        return RunResult(
            run_id=run_id,
            phase=machine.phase,
            termination_reason=termination_reason,
            plan=plan,
            patch=patch,
            verifications=tuple(verifications),
            reflections=tuple(reflections),
            counters=tracker.counters(),
            usage=usage.value(),
            transitions=tuple(transitions),
            failure_message=failure_message,
        )

    def _prepare_repository(
        self,
        request: RunRequest,
        workspace: RunWorkspace,
    ) -> RepositoryCheckout:
        if isinstance(request.source, LocalRepositorySource):
            return self._repository.prepare_local(request.source.path, workspace)
        return self._repository.prepare_public(request.source.url, workspace)

    def _advance(
        self,
        machine: RunStateMachine,
        event: RunEvent,
        run_id: str,
        tracker: _BudgetTracker,
        records: list[TransitionRecord],
    ) -> None:
        transition = machine.advance(event)
        record = TransitionRecord(
            run_id=run_id,
            sequence=len(records) + 1,
            previous_phase=transition.previous_phase,
            event=transition.event,
            next_phase=transition.next_phase,
            elapsed_ms=tracker.elapsed_ms,
        )
        records.append(record)
        self._logger.record_transition(record)

    @staticmethod
    def _require_tool_success(result: AnyToolResult) -> None:
        if result.error is not None:
            raise ControllerToolError(
                f"Tool {result.tool_name.value!r} failed with {result.error.code.value}: "
                f"{result.error.message}"
            )


class _BudgetTracker:
    def __init__(self, budgets: RunBudgets, clock: Callable[[], float]) -> None:
        self._budgets = budgets
        self._clock = clock
        self._started = clock()
        self._model_calls = 0
        self._tool_calls = 0
        self._iterations = 0

    @property
    def elapsed_ms(self) -> int:
        return max(0, int((self._clock() - self._started) * 1_000))

    @property
    def iterations(self) -> int:
        return self._iterations

    def check_runtime(self) -> None:
        if self.elapsed_ms >= self._budgets.max_runtime_seconds * 1_000:
            raise RunBudgetExceededError("runtime_seconds", self._budgets.max_runtime_seconds)

    def consume_model_call(self) -> None:
        self.check_runtime()
        if self._model_calls >= self._budgets.max_model_calls:
            raise RunBudgetExceededError("model_calls", self._budgets.max_model_calls)
        self._model_calls += 1

    def consume_tool_call(self) -> None:
        self.check_runtime()
        if self._tool_calls >= self._budgets.max_tool_calls:
            raise RunBudgetExceededError("tool_calls", self._budgets.max_tool_calls)
        self._tool_calls += 1

    def require_retry_available(self) -> None:
        if self._iterations >= self._budgets.max_iterations:
            raise RunBudgetExceededError("iterations", self._budgets.max_iterations)

    def consume_iteration(self) -> None:
        self.require_retry_available()
        self._iterations += 1

    def counters(self) -> RunCounters:
        return RunCounters(
            model_calls=self._model_calls,
            tool_calls=self._tool_calls,
            iterations=self._iterations,
            elapsed_ms=self.elapsed_ms,
        )


@dataclass(slots=True)
class _UsageAccumulator:
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    reasoning_tokens: int = 0
    observed: bool = False

    def add[OutputT: BaseModel](self, response: ModelResponse[OutputT]) -> None:
        if response.usage is None:
            return
        self.observed = True
        self.input_tokens += response.usage.input_tokens
        self.output_tokens += response.usage.output_tokens
        self.cached_input_tokens += response.usage.cached_input_tokens
        self.reasoning_tokens += response.usage.reasoning_tokens

    def value(self) -> ModelUsage | None:
        if not self.observed:
            return None
        return ModelUsage(
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.input_tokens + self.output_tokens,
            cached_input_tokens=self.cached_input_tokens,
            reasoning_tokens=self.reasoning_tokens,
        )


def _termination_reason(phase: RunPhase, error: Exception) -> TerminationReason:
    if isinstance(error, RunBudgetExceededError):
        return TerminationReason.BUDGET_EXHAUSTED
    if isinstance(error, NoProgressError):
        return TerminationReason.NO_PROGRESS
    return {
        RunPhase.INITIALIZE: TerminationReason.INITIALIZATION_FAILED,
        RunPhase.INSPECT: TerminationReason.INSPECTION_FAILED,
        RunPhase.PLAN: TerminationReason.PLANNING_FAILED,
        RunPhase.EDIT: TerminationReason.EDIT_FAILED,
        RunPhase.VERIFY: TerminationReason.VERIFICATION_FAILED,
        RunPhase.REFLECT: TerminationReason.EDIT_FAILED,
    }.get(phase, TerminationReason.INITIALIZATION_FAILED)

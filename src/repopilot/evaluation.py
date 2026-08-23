"""Versioned offline benchmarks and aggregate agent-run metrics."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from repopilot.controller import RunController
from repopilot.errors import EvaluationError
from repopilot.process import safe_search_path
from repopilot.repository import RepositoryService
from repopilot.run_models import (
    LocalRepositorySource,
    RunBudgets,
    RunRequest,
    RunResult,
    TerminationReason,
)
from repopilot.scripted_model import ScriptedModel
from repopilot.tool_models import RunCommandRequest
from repopilot.verification import VerificationStatus
from repopilot.workspace import WorkspaceManager

_MAX_SUITE_BYTES = 2_097_152
_CASE_ID_PATTERN = r"^[a-z][a-z0-9_-]{0,47}$"


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class BenchmarkFile(_EvaluationModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    path: str = Field(
        min_length=1,
        max_length=4_096,
        pattern=r"^[A-Za-z0-9._/-]+$",
    )
    content: str = Field(max_length=100_000)

    @field_validator("path")
    @classmethod
    def require_safe_normalized_path(cls, value: str) -> str:
        return _validate_benchmark_path(value)


class BenchmarkExpectation(_EvaluationModel):
    termination_reason: TerminationReason
    changed_files: tuple[str, ...] = Field(max_length=20)
    verification_statuses: tuple[VerificationStatus, ...] = Field(max_length=10)
    patch_contains: tuple[str, ...] = Field(default=(), max_length=20)
    patch_excludes: tuple[str, ...] = Field(default=(), max_length=20)

    @field_validator("changed_files")
    @classmethod
    def require_sorted_unique_changed_files(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        validated = tuple(_validate_benchmark_path(path) for path in value)
        if validated != tuple(sorted(set(validated))):
            raise ValueError("expected changed files must be unique and sorted")
        return validated


class BenchmarkCase(_EvaluationModel):
    id: str = Field(min_length=1, max_length=48, pattern=_CASE_ID_PATTERN)
    task: str = Field(min_length=1, max_length=10_000)
    files: tuple[BenchmarkFile, ...] = Field(min_length=1, max_length=50)
    verification: RunCommandRequest
    budgets: RunBudgets = Field(default_factory=RunBudgets)
    scripted_responses: tuple[dict[str, Any], ...] = Field(min_length=1, max_length=50)
    expected: BenchmarkExpectation

    @model_validator(mode="after")
    def require_unique_file_paths(self) -> BenchmarkCase:
        paths = [file.path for file in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("benchmark file paths must be unique")
        return self


class BenchmarkSuite(_EvaluationModel):
    schema_version: Literal[1]
    name: str = Field(min_length=1, max_length=64, pattern=_CASE_ID_PATTERN)
    cases: tuple[BenchmarkCase, ...] = Field(min_length=6, max_length=10)

    @model_validator(mode="after")
    def require_unique_case_ids(self) -> BenchmarkSuite:
        case_ids = [case.id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case IDs must be unique")
        return self


class BenchmarkResult(_EvaluationModel):
    case_id: str
    expectation_met: bool
    task_succeeded: bool
    termination_reason: str
    verification_statuses: tuple[VerificationStatus, ...]
    changed_files: tuple[str, ...]
    failures: tuple[str, ...]
    run_failure_message: str | None
    model_calls: int
    tool_calls: int
    iterations: int
    duration_ms: int
    input_tokens: int | None
    context_original_chars: int
    context_selected_chars: int


class EvaluationSummary(_EvaluationModel):
    total_cases: int
    expectations_met: int
    task_successes: int
    expectation_pass_rate: float
    task_success_rate: float
    total_model_calls: int
    total_tool_calls: int
    total_iterations: int
    total_duration_ms: int
    total_input_tokens: int | None
    context_original_chars: int
    context_selected_chars: int


class EvaluationReport(_EvaluationModel):
    schema_version: Literal[1] = 1
    suite: str
    mode: Literal["scripted_replay"] = "scripted_replay"
    summary: EvaluationSummary
    results: tuple[BenchmarkResult, ...]


class EvaluationRunner:
    """Materialize cases, execute isolated runs, and compare observable outcomes."""

    def __init__(self, working_root: Path) -> None:
        self._working_root = working_root.resolve()

    def run(self, suite: BenchmarkSuite) -> EvaluationReport:
        self._working_root.mkdir(parents=True, exist_ok=False, mode=0o700)
        results: list[BenchmarkResult] = []
        for case in suite.cases:
            try:
                results.append(self._run_case(case))
            except Exception as error:
                results.append(_harness_failure(case, error))
        return EvaluationReport(
            suite=suite.name,
            summary=_summarize(results),
            results=tuple(results),
        )

    def _run_case(self, case: BenchmarkCase) -> BenchmarkResult:
        case_root = self._working_root / case.id
        source = case_root / "source"
        execution_root = case_root / "execution"
        self._materialize(case, source)
        model = ScriptedModel(case.scripted_responses)
        controller = RunController(
            WorkspaceManager(execution_root),
            RepositoryService(),
            model,
        )
        result = controller.run(
            RunRequest(
                source=LocalRepositorySource(path=source),
                task=case.task,
                verification=case.verification,
                budgets=case.budgets,
                run_id=f"eval-{case.id}",
            )
        )
        return _assess(case, result)

    def _materialize(self, case: BenchmarkCase, source: Path) -> None:
        source.mkdir(parents=True)
        for fixture in case.files:
            path = source.joinpath(*PurePosixPath(fixture.path).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(fixture.content, encoding="utf-8")
        _initialize_git(source, self._working_root)


def load_benchmark_suite(path: Path) -> BenchmarkSuite:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise EvaluationError(f"Could not read benchmark suite {str(path)!r}: {error}.") from error
    if len(payload) > _MAX_SUITE_BYTES:
        raise EvaluationError(f"Benchmark suite exceeds {_MAX_SUITE_BYTES} bytes.")
    try:
        return BenchmarkSuite.model_validate_json(payload)
    except ValidationError as error:
        raise EvaluationError(f"Benchmark suite {str(path)!r} is invalid: {error}.") from error


def write_evaluation_report(report: EvaluationReport, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = report.model_dump_json(indent=2) + "\n"
        descriptor, temporary_name = tempfile.mkstemp(prefix=".repopilot-eval-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    except OSError as error:
        raise EvaluationError(
            f"Could not write evaluation report {str(path)!r}: {error}."
        ) from error


def _validate_benchmark_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        "\\" in value
        or path.is_absolute()
        or value != path.as_posix()
        or any(part in ("", ".", "..", ".git") for part in path.parts)
    ):
        raise ValueError("benchmark paths must be normalized and repository-relative")
    return value


def _initialize_git(source: Path, working_root: Path) -> None:
    search_path = safe_search_path(os.environ.get("PATH", os.defpath))
    git = shutil.which("git", path=search_path)
    if git is None:
        raise EvaluationError("Git is required to materialize benchmark repositories.")
    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": str(working_root),
        "LC_ALL": "C",
        "PATH": search_path,
    }
    executable = str(Path(git).resolve(strict=True))
    for argv in (
        (executable, "init", "--quiet", str(source)),
        (executable, "-C", str(source), "add", "--all"),
    ):
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            env=environment,
            timeout=30,
        )
        if completed.returncode != 0:
            detail = completed.stderr.decode("utf-8", errors="replace").strip()
            raise EvaluationError(f"Could not initialize benchmark repository: {detail}.")


def _assess(case: BenchmarkCase, result: RunResult) -> BenchmarkResult:
    expected = case.expected
    statuses = tuple(item.status for item in result.verifications)
    changed_files = _changed_files(result.patch)
    failures: list[str] = []
    if result.termination_reason is not expected.termination_reason:
        failures.append(
            f"termination expected {expected.termination_reason.value}, "
            f"observed {result.termination_reason.value}"
        )
    if changed_files != expected.changed_files:
        failures.append(
            f"changed files expected {expected.changed_files}, observed {changed_files}"
        )
    if statuses != expected.verification_statuses:
        failures.append(
            f"verification statuses expected {expected.verification_statuses}, observed {statuses}"
        )
    for fragment in expected.patch_contains:
        if fragment not in result.patch:
            failures.append(f"patch is missing required fragment {fragment!r}")
    for fragment in expected.patch_excludes:
        if fragment in result.patch:
            failures.append(f"patch contains forbidden fragment {fragment!r}")

    return BenchmarkResult(
        case_id=case.id,
        expectation_met=not failures,
        task_succeeded=result.termination_reason is TerminationReason.SUCCESS,
        termination_reason=result.termination_reason.value,
        verification_statuses=statuses,
        changed_files=changed_files,
        failures=tuple(failures),
        run_failure_message=result.failure_message,
        model_calls=result.counters.model_calls,
        tool_calls=result.counters.tool_calls,
        iterations=result.counters.iterations,
        duration_ms=result.counters.elapsed_ms,
        input_tokens=None if result.usage is None else result.usage.input_tokens,
        context_original_chars=sum(item.original_chars for item in result.context_metrics),
        context_selected_chars=sum(item.selected_chars for item in result.context_metrics),
    )


def _changed_files(patch: str) -> tuple[str, ...]:
    prefix = "diff --git a/"
    paths: list[str] = []
    for line in patch.splitlines():
        if not line.startswith(prefix):
            continue
        remainder = line[len(prefix) :]
        old_path, separator, new_path = remainder.partition(" b/")
        if separator and old_path == new_path:
            paths.append(new_path)
    return tuple(paths)


def _harness_failure(case: BenchmarkCase, error: Exception) -> BenchmarkResult:
    return BenchmarkResult(
        case_id=case.id,
        expectation_met=False,
        task_succeeded=False,
        termination_reason="harness_error",
        verification_statuses=(),
        changed_files=(),
        failures=(f"{type(error).__name__}: {error}",),
        run_failure_message=None,
        model_calls=0,
        tool_calls=0,
        iterations=0,
        duration_ms=0,
        input_tokens=None,
        context_original_chars=0,
        context_selected_chars=0,
    )


def _summarize(results: list[BenchmarkResult]) -> EvaluationSummary:
    total = len(results)
    token_counts = [result.input_tokens for result in results if result.input_tokens is not None]
    expectations_met = sum(result.expectation_met for result in results)
    task_successes = sum(result.task_succeeded for result in results)
    return EvaluationSummary(
        total_cases=total,
        expectations_met=expectations_met,
        task_successes=task_successes,
        expectation_pass_rate=expectations_met / total,
        task_success_rate=task_successes / total,
        total_model_calls=sum(result.model_calls for result in results),
        total_tool_calls=sum(result.tool_calls for result in results),
        total_iterations=sum(result.iterations for result in results),
        total_duration_ms=sum(result.duration_ms for result in results),
        total_input_tokens=sum(token_counts) if token_counts else None,
        context_original_chars=sum(result.context_original_chars for result in results),
        context_selected_chars=sum(result.context_selected_chars for result in results),
    )

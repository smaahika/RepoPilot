"""End-to-end execution of the offline benchmark runner."""

from __future__ import annotations

from pathlib import Path

from repopilot.evaluation import EvaluationRunner, load_benchmark_suite
from repopilot.run_models import TerminationReason

_ROOT = Path(__file__).resolve().parents[2]


def test_offline_replay_matches_all_expectations_and_exposes_failed_tasks(
    tmp_path: Path,
) -> None:
    suite = load_benchmark_suite(_ROOT / "evaluation" / "cases.json")

    report = EvaluationRunner(tmp_path / "work").run(suite)

    assert report.summary.total_cases == 8
    assert report.summary.expectations_met == 8
    assert report.summary.task_successes == 6
    assert report.summary.total_model_calls == 24
    assert report.summary.total_iterations == 8
    assert report.summary.context_original_chars > 0
    assert report.summary.context_selected_chars > 0
    assert [result.termination_reason for result in report.results[-2:]] == [
        TerminationReason.EDIT_FAILED.value,
        TerminationReason.BUDGET_EXHAUSTED.value,
    ]
    assert all(result.expectation_met for result in report.results)

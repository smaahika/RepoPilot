"""Tests for versioned benchmark schemas and report persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from repopilot.errors import EvaluationError
from repopilot.evaluation import (
    EvaluationReport,
    load_benchmark_suite,
    write_evaluation_report,
)

_ROOT = Path(__file__).resolve().parents[2]
_SUITE = _ROOT / "evaluation" / "cases.json"
_BASELINE = _ROOT / "evaluation" / "results" / "baseline.json"


def test_suite_loads_eight_cases_and_preserves_source_bytes() -> None:
    suite = load_benchmark_suite(_SUITE)

    assert suite.schema_version == 1
    assert len(suite.cases) == 8
    assert suite.cases[0].files[0].content.endswith("\n")
    assert len({case.id for case in suite.cases}) == len(suite.cases)


def test_suite_rejects_repository_path_traversal(tmp_path: Path) -> None:
    payload = json.loads(_SUITE.read_text(encoding="utf-8"))
    payload["cases"][0]["files"][0]["path"] = "../escape.py"
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(EvaluationError):
        load_benchmark_suite(invalid)


def test_checked_in_baseline_is_valid_and_records_failures_honestly() -> None:
    report = EvaluationReport.model_validate_json(_BASELINE.read_bytes())

    assert report.summary.expectations_met == 8
    assert report.summary.task_successes == 6
    assert report.summary.task_success_rate == 0.75
    assert sum(not result.task_succeeded for result in report.results) == 2


def test_report_writer_atomically_replaces_existing_output(tmp_path: Path) -> None:
    report = EvaluationReport.model_validate_json(_BASELINE.read_bytes())
    output = tmp_path / "nested" / "report.json"
    output.parent.mkdir()
    output.write_text("stale", encoding="utf-8")

    write_evaluation_report(report, output)

    assert EvaluationReport.model_validate_json(output.read_bytes()) == report
    assert not tuple(output.parent.glob(".repopilot-eval-*"))

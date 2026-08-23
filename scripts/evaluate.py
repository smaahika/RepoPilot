"""Run the deterministic RepoPilot benchmark suite."""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from repopilot.errors import EvaluationError
from repopilot.evaluation import EvaluationRunner, load_benchmark_suite, write_evaluation_report

_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_SUITE = _ROOT / "evaluation" / "cases.json"
_DEFAULT_OUTPUT = _ROOT / "evaluation" / "results" / "latest.json"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run RepoPilot's offline scripted benchmark.")
    parser.add_argument("--suite", type=Path, default=_DEFAULT_SUITE)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    arguments = parser.parse_args(argv)

    try:
        suite = load_benchmark_suite(arguments.suite)
        with tempfile.TemporaryDirectory(prefix="repopilot-evaluation-") as temporary:
            report = EvaluationRunner(Path(temporary) / "work").run(suite)
        write_evaluation_report(report, arguments.output)
    except EvaluationError as error:
        print(f"Evaluation failed: {error}", file=sys.stderr)
        return 1

    summary = report.summary
    print(
        f"Expectations: {summary.expectations_met}/{summary.total_cases}; "
        f"task successes: {summary.task_successes}/{summary.total_cases}"
    )
    print(f"Report: {arguments.output}")
    return 0 if summary.expectations_met == summary.total_cases else 1


if __name__ == "__main__":
    raise SystemExit(main())

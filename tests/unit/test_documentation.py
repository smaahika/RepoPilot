"""Checks that recruiter-facing documentation stays linked to real evidence."""

from __future__ import annotations

import re
from pathlib import Path

from repopilot.evaluation import EvaluationReport

_ROOT = Path(__file__).resolve().parents[2]
_LINK_PATTERN = re.compile(r"\[[^]]+\]\(([^)]+)\)")


def test_readme_local_links_resolve() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")

    local_links = (
        target.partition("#")[0] for target in _LINK_PATTERN.findall(readme) if "://" not in target
    )

    assert all((_ROOT / target).is_file() for target in local_links)


def test_readme_metrics_match_the_checked_baseline() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")
    report = EvaluationReport.model_validate_json(
        (_ROOT / "evaluation" / "results" / "baseline.json").read_bytes()
    )
    summary = report.summary

    assert f"{summary.expectations_met}/{summary.total_cases}" in readme
    assert f"{summary.task_successes}/{summary.total_cases} (75%)" in readme
    assert f"{summary.context_original_chars:,} before" in readme
    assert f"{summary.context_selected_chars:,} after" in readme


def test_readme_commands_reference_existing_scripts() -> None:
    readme = (_ROOT / "README.md").read_text(encoding="utf-8")

    for name in ("check.py", "demo.py", "evaluate.py", "security_check.py"):
        assert f"scripts/{name}" in readme
        assert (_ROOT / "scripts" / name).is_file()

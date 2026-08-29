"""Checks that repository automation retains its security boundaries."""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW_DIRECTORY = _ROOT / ".github" / "workflows"
_EXPECTED_ACTIONS = {
    "actions/checkout@v7",
    "actions/dependency-review-action@v5",
    "actions/setup-python@v7",
    "github/codeql-action/analyze@v4",
    "github/codeql-action/init@v4",
}


def test_workflows_use_only_reviewed_action_versions() -> None:
    workflows = tuple(_WORKFLOW_DIRECTORY.glob("*.yml"))
    contents = "\n".join(path.read_text(encoding="utf-8") for path in workflows)
    action_references = set(re.findall(r"uses:\s+([^\s]+)", contents))

    assert {path.name for path in workflows} == {
        "ci.yml",
        "codeql.yml",
        "dependency-review.yml",
    }
    assert action_references == _EXPECTED_ACTIONS
    assert "pull_request_target" not in contents
    assert "secrets." not in contents


def test_workflows_are_bounded_and_do_not_persist_credentials() -> None:
    for workflow in _WORKFLOW_DIRECTORY.glob("*.yml"):
        contents = workflow.read_text(encoding="utf-8")
        jobs = contents.partition("jobs:\n")[2]
        job_count = len(re.findall(r"^  [a-z][a-z-]+:\n", jobs, flags=re.MULTILINE))

        assert contents.count("timeout-minutes:") == job_count
        assert contents.count("persist-credentials: false") == contents.count(
            "uses: actions/checkout@"
        )


def test_workflow_permissions_are_least_privilege() -> None:
    ci = (_WORKFLOW_DIRECTORY / "ci.yml").read_text(encoding="utf-8")
    dependency_review = (_WORKFLOW_DIRECTORY / "dependency-review.yml").read_text(encoding="utf-8")
    codeql = (_WORKFLOW_DIRECTORY / "codeql.yml").read_text(encoding="utf-8")

    assert "permissions:\n  contents: read" in ci
    assert "permissions:\n  contents: read" in dependency_review
    assert "permissions:\n  contents: read\n  security-events: write" in codeql


def test_dependabot_covers_python_and_workflow_dependencies() -> None:
    configuration = (_ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")

    assert configuration.count("interval: weekly") == 2
    assert "package-ecosystem: pip" in configuration
    assert "package-ecosystem: github-actions" in configuration

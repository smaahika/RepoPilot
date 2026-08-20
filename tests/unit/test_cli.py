"""Tests for CLI parsing, composition inputs, and terminal presentation."""

from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from repopilot import __version__
from repopilot.cli import main
from repopilot.config import RuntimeConfig
from repopilot.run_models import (
    LocalRepositorySource,
    PublicRepositorySource,
    RunCounters,
    RunRequest,
    RunResult,
    TerminationReason,
)
from repopilot.state_machine import RunPhase


class _FakeApplication:
    def __init__(self, result: RunResult) -> None:
        self.result = result
        self.request: RunRequest | None = None

    def run(self, request: RunRequest) -> RunResult:
        self.request = request
        return self.result


class _Factory:
    def __init__(self, application: _FakeApplication) -> None:
        self.application = application
        self.config: RuntimeConfig | None = None

    def __call__(self, config: RuntimeConfig) -> _FakeApplication:
        self.config = config
        return self.application


def _result(*, success: bool = True) -> RunResult:
    return RunResult(
        run_id="cli-test",
        phase=RunPhase.COMPLETE if success else RunPhase.FAILED,
        termination_reason=(
            TerminationReason.SUCCESS if success else TerminationReason.VERIFICATION_FAILED
        ),
        plan=None,
        patch="diff --git a/a.py b/a.py\n" if success else "",
        verifications=(),
        reflections=(),
        counters=RunCounters(model_calls=2, tool_calls=3, iterations=1, elapsed_ms=10),
        usage=None,
        transitions=(),
        failure_message=None if success else "Tests failed.",
    )


def test_version_reports_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"repopilot {__version__}"


def test_empty_invocation_prints_help_without_loading_configuration() -> None:
    output = StringIO()

    assert main([], environ={}, stdout=output) == 0

    assert "{run}" in output.getvalue()


def test_run_builds_validated_local_request_and_prints_patch(tmp_path: Path) -> None:
    output = StringIO()
    errors = StringIO()
    application = _FakeApplication(_result())
    factory = _Factory(application)
    run_root = tmp_path / "managed"

    exit_code = main(
        [
            "run",
            "--local-repo",
            str(tmp_path),
            "--task",
            "Add a flag.",
            "--run-root",
            str(run_root),
            "--model",
            "gpt-test",
            "--max-iterations",
            "2",
            "--verify",
            "pytest",
            "-q",
        ],
        environ={"OPENAI_API_KEY": "secret-key"},
        controller_factory=factory,
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 0
    assert application.request is not None
    assert application.request.source == LocalRepositorySource(path=tmp_path)
    assert application.request.task == "Add a flag."
    assert application.request.verification is not None
    assert application.request.verification.argv == ("pytest", "-q")
    assert application.request.budgets.max_iterations == 2
    assert factory.config is not None
    assert factory.config.run_root == run_root.resolve()
    assert factory.config.model.model == "gpt-test"
    assert factory.config.api_key.get_secret_value() == "secret-key"
    assert "secret-key" not in repr(factory.config)
    assert "Run cli-test: success" in output.getvalue()
    assert "diff --git" in output.getvalue()
    assert errors.getvalue() == ""


def test_run_accepts_public_source_without_verification() -> None:
    application = _FakeApplication(_result())

    exit_code = main(
        [
            "run",
            "--public-repo",
            "https://github.com/example/project.git",
            "--task",
            "Update docs.",
        ],
        environ={"OPENAI_API_KEY": "secret-key"},
        controller_factory=_Factory(application),
        stdout=StringIO(),
    )

    assert exit_code == 0
    assert application.request is not None
    assert application.request.source == PublicRepositorySource(
        url="https://github.com/example/project.git"
    )
    assert application.request.verification is None


def test_missing_api_key_returns_configuration_exit_without_composing() -> None:
    errors = StringIO()
    factory = _Factory(_FakeApplication(_result()))

    exit_code = main(
        ["run", "--local-repo", ".", "--task", "Update docs."],
        environ={},
        controller_factory=factory,
        stderr=errors,
    )

    assert exit_code == 2
    assert factory.config is None
    assert "OPENAI_API_KEY is required" in errors.getvalue()


def test_invalid_budget_returns_sanitized_input_error() -> None:
    errors = StringIO()

    exit_code = main(
        [
            "run",
            "--local-repo",
            ".",
            "--task",
            "Update docs.",
            "--max-iterations",
            "0",
        ],
        environ={"OPENAI_API_KEY": "secret-key"},
        stderr=errors,
    )

    assert exit_code == 2
    assert "max_iterations" in errors.getvalue()
    assert "secret-key" not in errors.getvalue()


def test_empty_verification_command_returns_input_error() -> None:
    errors = StringIO()

    exit_code = main(
        ["run", "--local-repo", ".", "--task", "Update docs.", "--verify"],
        environ={"OPENAI_API_KEY": "secret-key"},
        stderr=errors,
    )

    assert exit_code == 2
    assert "--verify requires at least one" in errors.getvalue()


def test_failed_run_returns_one_and_writes_failure_to_stderr() -> None:
    output = StringIO()
    errors = StringIO()

    exit_code = main(
        ["run", "--local-repo", ".", "--task", "Update docs."],
        environ={"OPENAI_API_KEY": "secret-key"},
        controller_factory=_Factory(_FakeApplication(_result(success=False))),
        stdout=output,
        stderr=errors,
    )

    assert exit_code == 1
    assert "verification_failed" in output.getvalue()
    assert "Tests failed." in errors.getvalue()

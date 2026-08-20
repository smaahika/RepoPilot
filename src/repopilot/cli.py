"""Command-line entry point for RepoPilot."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TextIO

from repopilot import __version__

if TYPE_CHECKING:
    from pydantic import ValidationError

    from repopilot.config import RuntimeConfig
    from repopilot.errors import ConfigurationError
    from repopilot.run_models import RunRequest, RunResult


class RunApplication(Protocol):
    def run(self, request: RunRequest) -> RunResult: ...


type ControllerFactory = Callable[[RuntimeConfig], RunApplication]


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser without performing side effects."""
    parser = argparse.ArgumentParser(
        prog="repopilot",
        description="Produce a tested, reviewable patch for a scoped repository task.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    commands = parser.add_subparsers(dest="command")
    run_parser = commands.add_parser("run", help="Run a bounded repository task.")

    source = run_parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--local-repo", type=Path, metavar="PATH")
    source.add_argument("--public-repo", metavar="HTTPS_URL")
    run_parser.add_argument("--task", required=True)
    run_parser.add_argument("--run-id")
    run_parser.add_argument("--run-root", type=Path)
    run_parser.add_argument("--model")
    run_parser.add_argument("--max-runtime-seconds", type=float, default=600)
    run_parser.add_argument("--max-model-calls", type=int, default=8)
    run_parser.add_argument("--max-tool-calls", type=int, default=20)
    run_parser.add_argument("--max-iterations", type=int, default=3)
    run_parser.add_argument("--verification-timeout-seconds", type=float, default=120)
    run_parser.add_argument(
        "--verify",
        nargs=argparse.REMAINDER,
        metavar="ARG",
        help="Allowlisted verification argv; this option must be last.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    controller_factory: ControllerFactory | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse a command, compose the application, and return a stable exit code."""
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command is None:
        parser.print_help(output)
        return 0

    from pydantic import ValidationError

    from repopilot.config import load_runtime_config
    from repopilot.errors import ConfigurationError
    from repopilot.run_models import TerminationReason

    try:
        config = load_runtime_config(
            environ,
            run_root=arguments.run_root,
            model=arguments.model,
        )
        request = _run_request(arguments)
    except (ConfigurationError, ValidationError) as error:
        print(f"repopilot: error: {_input_error_message(error)}", file=errors)
        return 2

    if controller_factory is None:
        from repopilot.composition import build_controller

        controller_factory = build_controller
    result = controller_factory(config).run(request)
    _print_result(result, stdout=output, stderr=errors)
    return 0 if result.termination_reason is TerminationReason.SUCCESS else 1


def _run_request(arguments: argparse.Namespace) -> RunRequest:
    from repopilot.errors import ConfigurationError
    from repopilot.run_models import (
        LocalRepositorySource,
        PublicRepositorySource,
        RunBudgets,
        RunRequest,
    )
    from repopilot.tool_models import RunCommandRequest

    source: LocalRepositorySource | PublicRepositorySource
    if arguments.local_repo is not None:
        source = LocalRepositorySource(path=arguments.local_repo)
    else:
        source = PublicRepositorySource(url=arguments.public_repo)

    verification = None
    if arguments.verify is not None:
        if not arguments.verify:
            raise ConfigurationError("--verify requires at least one command argument.")
        verification = RunCommandRequest(
            argv=tuple(arguments.verify),
            timeout_seconds=arguments.verification_timeout_seconds,
        )

    return RunRequest(
        source=source,
        task=arguments.task,
        verification=verification,
        budgets=RunBudgets(
            max_runtime_seconds=arguments.max_runtime_seconds,
            max_model_calls=arguments.max_model_calls,
            max_tool_calls=arguments.max_tool_calls,
            max_iterations=arguments.max_iterations,
        ),
        run_id=arguments.run_id,
    )


def _input_error_message(error: ConfigurationError | ValidationError) -> str:
    from repopilot.errors import ConfigurationError

    if isinstance(error, ConfigurationError):
        return str(error)
    issue = error.errors(include_url=False, include_input=False)[0]
    field = ".".join(str(part) for part in issue["loc"])
    return f"invalid {field}: {issue['msg']}"


def _print_result(result: RunResult, *, stdout: TextIO, stderr: TextIO) -> None:
    print(f"Run {result.run_id}: {result.termination_reason.value}", file=stdout)
    print(
        f"Iterations: {result.counters.iterations}; model calls: "
        f"{result.counters.model_calls}; tool calls: {result.counters.tool_calls}",
        file=stdout,
    )
    if result.patch:
        print("\nPatch:\n", file=stdout, end="")
        print(result.patch.rstrip(), file=stdout)
    if result.failure_message is not None:
        print(f"RepoPilot failed: {result.failure_message}", file=stderr)

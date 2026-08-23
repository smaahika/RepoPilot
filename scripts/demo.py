"""Run one deterministic end-to-end RepoPilot demonstration."""

from __future__ import annotations

import argparse
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from repopilot.application import PersistingRunApplication
from repopilot.artifacts import FilesystemArtifactWriter
from repopilot.controller import RunController
from repopilot.evaluation import (
    changed_files_from_patch,
    load_benchmark_suite,
    materialize_benchmark_repository,
)
from repopilot.repository import RepositoryService
from repopilot.run_models import LocalRepositorySource, RunRequest, TerminationReason
from repopilot.scripted_model import ScriptedModel
from repopilot.workspace import WorkspaceManager

_ROOT = Path(__file__).resolve().parents[1]
_SUITE = _ROOT / "evaluation" / "cases.json"
_DEMO_CASE_ID = "update_greeting"


def main(
    argv: Sequence[str] | None = None,
    *,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    output = sys.stdout if stdout is None else stdout
    errors = sys.stderr if stderr is None else stderr
    parser = argparse.ArgumentParser(description="Run RepoPilot's deterministic demo.")
    parser.add_argument("--output-dir", type=Path, help="New directory for retained demo evidence.")
    arguments = parser.parse_args(argv)

    if arguments.output_dir is not None:
        root = arguments.output_dir.expanduser().resolve()
        try:
            root.mkdir(parents=True, exist_ok=False, mode=0o700)
        except OSError as error:
            print(f"Demo failed: could not create output directory: {error}", file=errors)
            return 2
        exit_code = _run_demo(root, output)
        print(f"Saved demo workspace: {root}", file=output)
        return exit_code

    with tempfile.TemporaryDirectory(prefix="repopilot-demo-") as temporary:
        return _run_demo(Path(temporary), output)


def _run_demo(root: Path, output: TextIO) -> int:
    suite = load_benchmark_suite(_SUITE)
    case = next(case for case in suite.cases if case.id == _DEMO_CASE_ID)
    source = root / "source"
    run_root = root / "managed"
    materialize_benchmark_repository(case, source, root)
    controller = RunController(
        WorkspaceManager(run_root),
        RepositoryService(),
        ScriptedModel(case.scripted_responses),
    )
    application = PersistingRunApplication(
        controller,
        FilesystemArtifactWriter(run_root),
    )
    result = application.run(
        RunRequest(
            source=LocalRepositorySource(path=source),
            task=case.task,
            verification=case.verification,
            budgets=case.budgets,
            run_id="demo",
        )
    )
    assert result.artifact_path is not None
    artifacts = sorted(
        path.relative_to(result.artifact_path).as_posix()
        for path in result.artifact_path.rglob("*")
        if path.is_file()
    )

    changed_files = changed_files_from_patch(result.patch)
    statuses = tuple(item.status for item in result.verifications)
    expectation_met = (
        result.termination_reason is case.expected.termination_reason
        and changed_files == case.expected.changed_files
        and statuses == case.expected.verification_statuses
        and all(fragment in result.patch for fragment in case.expected.patch_contains)
        and all(fragment not in result.patch for fragment in case.expected.patch_excludes)
    )

    print("RepoPilot deterministic demo", file=output)
    print(f"Task: {case.task}", file=output)
    print(f"Result: {result.termination_reason.value}", file=output)
    print(f"Changed files: {', '.join(changed_files)}", file=output)
    print(f"Verification: {', '.join(status.value for status in statuses)}", file=output)
    print(
        f"Iterations: {result.counters.iterations}; model calls: "
        f"{result.counters.model_calls}; tool calls: {result.counters.tool_calls}",
        file=output,
    )
    print(f"Artifacts: {', '.join(artifacts)}", file=output)
    print("\nPatch:", file=output)
    print(result.patch.rstrip(), file=output)
    return 0 if expectation_met and result.termination_reason is TerminationReason.SUCCESS else 1


if __name__ == "__main__":
    raise SystemExit(main())

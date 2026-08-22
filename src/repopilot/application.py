"""Application services layered around deterministic run execution."""

from __future__ import annotations

from typing import Protocol

from repopilot.run_models import RunRequest, RunResult


class RunExecutor(Protocol):
    def run(self, request: RunRequest) -> RunResult: ...


class RunArtifactWriter(Protocol):
    def write(self, request: RunRequest, result: RunResult) -> None: ...


class PersistingRunApplication:
    """Execute one run and persist its terminal evidence."""

    def __init__(self, executor: RunExecutor, artifacts: RunArtifactWriter) -> None:
        self._executor = executor
        self._artifacts = artifacts

    def run(self, request: RunRequest) -> RunResult:
        result = self._executor.run(request)
        self._artifacts.write(request, result)
        return result

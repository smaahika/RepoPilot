"""Opt-in live verification of the Docker isolation contract."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from repopilot.models import RepositoryCheckout, RunWorkspace
from repopilot.sandbox import DockerCommandBackend, find_docker_executable

pytestmark = pytest.mark.skipif(
    os.environ.get("REPOPILOT_RUN_DOCKER_TESTS") != "1",
    reason="set REPOPILOT_RUN_DOCKER_TESTS=1 to run live Docker tests",
)


def test_live_container_enforces_read_only_repository_and_private_environment(
    tmp_path: Path,
) -> None:
    docker = find_docker_executable()
    if docker is None:
        pytest.fail("Docker CLI is unavailable")
    root = tmp_path / "workspace"
    repository = root / "repository"
    repository.mkdir(parents=True)
    (repository / "test_sandbox_contract.py").write_text(
        """import os
from pathlib import Path

import pytest


def test_contract() -> None:
    assert "OPENAI_API_KEY" not in os.environ
    with pytest.raises(OSError):
        Path("blocked.txt").write_text("blocked", encoding="utf-8")
    temporary = Path("/tmp/allowed.txt")
    temporary.write_text("allowed", encoding="utf-8")
    assert temporary.read_text(encoding="utf-8") == "allowed"
""",
        encoding="utf-8",
    )
    workspace = RunWorkspace(
        run_id="live-docker",
        root_path=root,
        artifact_path=tmp_path / "artifacts",
    )
    checkout = RepositoryCheckout(workspace=workspace, baseline_tree="tree")

    result = DockerCommandBackend(executable_finder=lambda: docker).run(
        checkout,
        repository,
        ("pytest", "-q"),
        30,
    )

    assert result.exit_code == 0
    assert b"1 passed" in result.stdout

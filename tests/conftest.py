"""Shared deterministic repository fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from repopilot.models import RepositoryCheckout
from repopilot.repository import RepositoryService
from repopilot.workspace import WorkspaceManager


@pytest.fixture
def prepared_repository(tmp_path: Path) -> tuple[RepositoryService, RepositoryCheckout]:
    source = tmp_path / "source"
    source.mkdir()
    subprocess.run(
        ["git", "init", "--quiet", str(source)],
        check=True,
        capture_output=True,
    )
    (source / "alpha.txt").write_text("hello world\nsecond line\n")
    nested = source / "src"
    nested.mkdir()
    (nested / "module.py").write_text("value = 'hello'\n")
    subprocess.run(
        ["git", "-C", str(source), "add", "alpha.txt", "src/module.py"],
        check=True,
        capture_output=True,
    )
    workspace = WorkspaceManager(tmp_path / "managed").create("tool-test")
    service = RepositoryService()
    return service, service.prepare_local(source, workspace)

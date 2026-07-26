"""Integration tests for patch, diff, and command tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from repopilot.models import RepositoryCheckout
from repopilot.repository import RepositoryService
from repopilot.tool_models import (
    GitDiffRequest,
    RunCommandRequest,
    ToolErrorCode,
    WritePatchRequest,
)
from repopilot.tools.git import GitTools
from repopilot.tools.patch import PatchTool
from repopilot.tools.shell import CommandPolicy, CommandRule, CommandTool

_VALID_PATCH = """diff --git a/alpha.txt b/alpha.txt
--- a/alpha.txt
+++ b/alpha.txt
@@ -1,2 +1,2 @@
-hello world
+hello RepoPilot
 second line
"""


def test_applies_validated_patch_and_reports_diff(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository

    applied = PatchTool(checkout).apply(WritePatchRequest(patch=_VALID_PATCH))
    diff = GitTools(checkout, service).diff(GitDiffRequest())

    assert applied.ok
    assert applied.data is not None
    assert applied.data.changed_paths == ("alpha.txt",)
    assert (checkout.path / "alpha.txt").read_text().startswith("hello RepoPilot")
    assert diff.ok
    assert diff.data is not None
    assert "+hello RepoPilot" in diff.data.patch


def test_patch_rejects_traversal_and_git_metadata(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    _, checkout = prepared_repository
    traversal = _VALID_PATCH.replace("alpha.txt", "../outside.txt")
    metadata = _VALID_PATCH.replace("alpha.txt", ".GIT/config")

    traversal_result = PatchTool(checkout).apply(WritePatchRequest(patch=traversal))
    metadata_result = PatchTool(checkout).apply(WritePatchRequest(patch=metadata))

    assert traversal_result.error is not None
    assert traversal_result.error.code is ToolErrorCode.POLICY_DENIED
    assert metadata_result.error is not None
    assert metadata_result.error.code is ToolErrorCode.POLICY_DENIED


def test_patch_rejects_symbolic_link_creation(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    _, checkout = prepared_repository
    patch = """diff --git a/link b/link
new file mode 120000
--- /dev/null
+++ b/link
@@ -0,0 +1 @@
+../../outside
"""

    result = PatchTool(checkout).apply(WritePatchRequest(patch=patch))

    assert result.error is not None
    assert result.error.code is ToolErrorCode.PATCH_REJECTED
    assert not (checkout.path / "link").exists()


def test_patch_rejects_existing_symbolic_link_retarget(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    _, checkout = prepared_repository
    (checkout.path / "link").symlink_to("alpha.txt")
    patch = """diff --git a/link b/link
--- a/link
+++ b/link
@@ -1 +1 @@
-alpha.txt
+../../outside
"""

    result = PatchTool(checkout).apply(WritePatchRequest(patch=patch))

    assert result.error is not None
    assert result.error.code is ToolErrorCode.POLICY_DENIED
    assert (checkout.path / "link").readlink() == Path("alpha.txt")


def test_rejected_patch_does_not_modify_file(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    _, checkout = prepared_repository
    invalid = _VALID_PATCH.replace("hello world", "content that is not present")

    result = PatchTool(checkout).apply(WritePatchRequest(patch=invalid))

    assert result.error is not None
    assert result.error.code is ToolErrorCode.PATCH_REJECTED
    assert (checkout.path / "alpha.txt").read_text().startswith("hello world")


def test_diff_enforces_caller_byte_limit(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    service, checkout = prepared_repository
    (checkout.path / "alpha.txt").write_text("changed\n")

    result = GitTools(checkout, service).diff(GitDiffRequest(max_bytes=4))

    assert result.error is not None
    assert result.error.code is ToolErrorCode.LIMIT_EXCEEDED


def test_runs_default_allowlisted_command(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    _, checkout = prepared_repository
    result = CommandTool(checkout).run(RunCommandRequest(argv=("pytest", "--version")))

    assert result.ok
    assert result.data is not None
    assert result.data.exit_code == 0
    assert "pytest" in result.data.stdout


def test_nonzero_command_exit_is_data_not_tool_failure(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    _, checkout = prepared_repository
    result = CommandTool(checkout).run(RunCommandRequest(argv=("pytest", "missing-test-file.py")))

    assert result.ok
    assert result.data is not None
    assert result.data.exit_code != 0


def test_rejects_unlisted_command_and_path_escape(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    _, checkout = prepared_repository
    shell = CommandTool(checkout).run(RunCommandRequest(argv=("sh", "-c", "echo unsafe")))
    argument = CommandTool(checkout).run(RunCommandRequest(argv=("pytest", "--rootdir=/tmp")))
    response_file = CommandTool(checkout).run(RunCommandRequest(argv=("pytest", "@/tmp/arguments")))
    cwd = CommandTool(checkout).run(RunCommandRequest(argv=("pytest",), cwd="../outside"))

    assert shell.error is not None
    assert shell.error.code is ToolErrorCode.POLICY_DENIED
    assert argument.error is not None
    assert argument.error.code is ToolErrorCode.POLICY_DENIED
    assert response_file.error is not None
    assert response_file.error.code is ToolErrorCode.POLICY_DENIED
    assert cwd.error is not None
    assert cwd.error.code is ToolErrorCode.POLICY_DENIED


def test_custom_command_still_obeys_timeout_and_output_limits(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
) -> None:
    _, checkout = prepared_repository
    policy = CommandPolicy((CommandRule(("python", "-c")),))
    timeout_tool = CommandTool(checkout, policy, timeout_limit_seconds=0.1)
    output_tool = CommandTool(checkout, policy, output_limit_bytes=32)

    timeout = timeout_tool.run(
        RunCommandRequest(
            argv=("python", "-c", "import time; time.sleep(2)"),
            timeout_seconds=0.1,
        )
    )
    output = output_tool.run(RunCommandRequest(argv=("python", "-c", "print('x' * 1000)")))

    assert timeout.error is not None
    assert timeout.error.code is ToolErrorCode.TIMEOUT
    assert output.error is not None
    assert output.error.code is ToolErrorCode.LIMIT_EXCEEDED


def test_command_environment_does_not_inherit_secret(
    prepared_repository: tuple[RepositoryService, RepositoryCheckout],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("REPOPILOT_TEST_SECRET", "sensitive")
    _, checkout = prepared_repository
    policy = CommandPolicy((CommandRule(("python", "-c")),))
    result = CommandTool(checkout, policy).run(
        RunCommandRequest(
            argv=(
                "python",
                "-c",
                "import os; print(os.getenv('REPOPILOT_TEST_SECRET'))",
            )
        )
    )

    assert result.data is not None
    assert result.data.stdout.strip() == "None"

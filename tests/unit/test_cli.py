"""Tests for the initial CLI surface."""

import pytest

from repopilot import __version__
from repopilot.cli import main


def test_version_reports_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])

    assert exc_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"repopilot {__version__}"


def test_empty_invocation_is_valid() -> None:
    assert main([]) == 0

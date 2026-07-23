"""Command-line entry point for RepoPilot."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from repopilot import __version__


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser without performing side effects."""
    parser = argparse.ArgumentParser(
        prog="repopilot",
        description="Produce a tested, reviewable patch for a scoped repository task.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the currently minimal RepoPilot CLI."""
    build_parser().parse_args(argv)
    return 0

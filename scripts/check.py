"""Run the complete local MVP checkpoint."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_QUALITY_COMMANDS = (
    (sys.executable, "-m", "ruff", "format", "--check", "."),
    (sys.executable, "-m", "ruff", "check", "."),
    (sys.executable, "-m", "mypy"),
    (sys.executable, "scripts/security_check.py"),
    (sys.executable, "-m", "pytest", "-q"),
)


def main() -> int:
    for command in _QUALITY_COMMANDS:
        if _run(command) != 0:
            return 1

    with tempfile.TemporaryDirectory(prefix="repopilot-check-") as temporary:
        temporary_path = Path(temporary)
        wheels = temporary_path / "wheels"
        if (
            _run(
                (
                    sys.executable,
                    "-m",
                    "pip",
                    "wheel",
                    "--no-build-isolation",
                    "--no-deps",
                    "--wheel-dir",
                    str(wheels),
                    str(_ROOT),
                )
            )
            != 0
        ):
            return 1

        built_wheels = tuple(wheels.glob("repopilot-*.whl"))
        if len(built_wheels) != 1:
            print("Expected exactly one RepoPilot wheel.", file=sys.stderr)
            return 1

        environment = temporary_path / "smoke-env"
        venv.EnvBuilder(with_pip=True).create(environment)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if _run((str(python), "-m", "pip", "install", "--no-deps", str(built_wheels[0]))) != 0:
            return 1
        if _run((str(python), "-m", "repopilot", "--version")) != 0:
            return 1

    return 0


def _run(command: tuple[str, ...]) -> int:
    print(f"+ {' '.join(command)}", flush=True)
    return subprocess.run(command, cwd=_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

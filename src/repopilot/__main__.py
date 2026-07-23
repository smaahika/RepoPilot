"""Allow RepoPilot to be invoked with ``python -m repopilot``."""

from repopilot.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

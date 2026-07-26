# RepoPilot

RepoPilot is a constrained coding agent that turns a narrowly scoped repository task into a tested,
reviewable patch and an inspectable execution report.

The project currently includes its design baseline, safe repository/workspace layer, and validated
filesystem, patch, diff, and command tools. It is intended to demonstrate bounded agent
orchestration, safety policy, failure handling, and evaluation—not to be a general autonomous IDE
or production security boundary.

## Development setup

RepoPilot requires Python 3.12 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --editable '.[dev]'
pytest
mypy
ruff check .
```

The initial CLI surface can be inspected with:

```bash
python -m repopilot --help
```

## Project documents

- [Product and system design](docs/design.md)
- [Architecture](docs/architecture.md)
- [Design decision log](docs/design-decisions.md)
- [Implementation backlog](BACKLOG.md)

The README will become the full quick start and demo landing page after the core workflow is
executable. Current milestones are tracked in the backlog rather than advertised as completed.

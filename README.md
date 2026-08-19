# RepoPilot

RepoPilot is a constrained coding agent that turns a narrowly scoped repository task into a tested,
reviewable patch and an inspectable execution report.

The project currently includes its design baseline, safe repository/workspace layer, validated
tools, structured model boundary, and a deterministic controller vertical slice through planning,
editing, verification, reflection, and bounded retries. It is intended to demonstrate bounded agent
orchestration, safety policy, failure handling, and evaluation—not to be a general autonomous IDE or
production security boundary.

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

The complete local checkpoint—including formatting, lint, strict typing, tests, wheel creation,
clean-environment installation, and an installed CLI smoke test—runs with:

```bash
python scripts/check.py
```

The deterministic controller demo is covered by:

```bash
pytest -q tests/integration/test_controller.py -k reflects_and_fixes
```

The initial CLI surface can be inspected with:

```bash
python -m repopilot --help
```

The controller is not yet composed into the CLI, and durable run artifacts are not yet written.
Those are explicit release gates before the project is tagged `v0.1.0`.

## Project documents

- [Product and system design](docs/design.md)
- [Architecture](docs/architecture.md)
- [Design decision log](docs/design-decisions.md)
- [Implementation backlog](BACKLOG.md)
- [MVP checkpoint](docs/mvp-checkpoint.md)

The README will become the full quick start and demo landing page after the core workflow is
executable. Current milestones are tracked in the backlog rather than advertised as completed.

# MVP Checkpoint

## Outcome

The core RepoPilot engine passes its Day 7 checkpoint. A deterministic run can copy a repository,
inspect it, create a structured plan, execute validated tools, apply a safe patch, verify it,
reflect on failure, retry within budgets, and return a categorized terminal result while preserving
the source repository.

The CLI now composes the controller with validated configuration and the real provider adapter, and
allocated runs persist the required report, patch, event, and command-log artifacts. The `v0.1.0`
release remains gated on committing this surface and passing the release checkpoint from that commit.

## Reproduction

From an installed development environment, run:

```bash
python scripts/check.py
```

The command performs, in order:

1. Ruff formatting verification.
2. Ruff linting.
3. strict mypy analysis.
4. unit and integration tests.
5. a dependency-free wheel build.
6. installation into a temporary clean virtual environment.
7. an installed `repopilot --version` smoke test.

The retry vertical slice can be run independently with:

```bash
pytest -q tests/integration/test_controller.py -k reflects_and_fixes
```

## Scope decision

The next release-critical work is:

1. Run the checkpoint through CI and tag only the commit that passes it.

Docker isolation, ranking, benchmarks, and presentation work remain important but do not replace
those missing product surfaces.

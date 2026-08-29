# Contributing to RepoPilot

RepoPilot favors small, reviewable changes that preserve its explicit safety boundaries.

## Development setup

Use Python 3.12 or newer:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --editable '.[dev]'
```

Run the same complete checkpoint used by CI:

```bash
python scripts/check.py
```

This checks formatting, linting, strict typing, repository hygiene, tests, wheel creation, clean
installation, and the installed CLI. Run `python scripts/evaluate.py` when behavior or metrics change,
then review the generated result before deliberately replacing the checked baseline.

## Change guidelines

- Keep pull requests narrow and add tests for behavior changes and failure paths.
- Preserve controller-owned budgets, typed boundaries, and shell-free command execution.
- Do not commit secrets, `.env` files, generated logs, workspaces, or `evaluation/results/latest.json`.
- Keep comments short and use them only when the reason is not clear from the code.
- Start commit subjects with a capitalized imperative category, such as `Feat:` or `Fix:`.

Security issues should follow [SECURITY.md](SECURITY.md), not the public issue tracker.

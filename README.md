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

The CLI surface can be inspected with:

```bash
python -m repopilot --help
```

To execute the controller against a local repository, export an API key and provide a narrowly
scoped task. The optional verification command is passed as an argument vector and must appear last:

```bash
export OPENAI_API_KEY="your-key"
repopilot run \
  --local-repo /path/to/repository \
  --task "Add a CLI flag and document it." \
  --verify pytest -q
```

RepoPilot copies the source into `~/.repopilot/workspaces`, removes that disposable copy after the
run, and never applies the generated patch to the source repository. Public HTTPS repositories are
accepted with `--public-repo`. Verification is optional and limited to the command allowlist.

Every allocated run preserves a report, patch, versioned transition events, and bounded verification
logs beneath `~/.repopilot/runs/<run-id>`. Known process secrets are redacted before persistence.

## Optional Docker verification

Local execution remains the default. To run allowlisted verification commands in the reference
Python sandbox, build its image and select the Docker backend:

```bash
docker build --tag repopilot-sandbox:py312 docker
repopilot run \
  --execution-backend docker \
  --local-repo /path/to/repository \
  --task "Add a CLI flag and document it." \
  --verify pytest -q
```

The container receives no network, a read-only repository mount, a writable temporary filesystem,
dropped Linux capabilities, no-new-privileges, and CPU, memory, PID, output, and runtime limits.
It does not turn Docker into a production security boundary; see the
[Docker threat model](docs/docker-sandbox.md) for guarantees and limitations.

## Project documents

- [Product and system design](docs/design.md)
- [Architecture](docs/architecture.md)
- [Design decision log](docs/design-decisions.md)
- [Implementation backlog](BACKLOG.md)
- [MVP checkpoint](docs/mvp-checkpoint.md)
- [Docker threat model](docs/docker-sandbox.md)

The README will become the full quick start and demo landing page after the core workflow is
executable. Current milestones are tracked in the backlog rather than advertised as completed.

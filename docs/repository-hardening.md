# Repository Hardening

RepoPilot uses independent local and hosted checks so one missed boundary does not silently bypass
every control.

## Local checkpoint

`python scripts/check.py` runs the quality suite, repository security scan, package build, clean
installation, and CLI smoke test. The security scan inspects tracked and non-ignored untracked files
without printing matched values. It rejects common credential formats, private keys, environment
files, generated runtime paths, and unexpectedly large files.

The scanner intentionally uses high-confidence patterns. It reduces accidental disclosure risk but
does not replace secret rotation, GitHub secret scanning, or review of the complete Git history.

## GitHub automation

- `CI` runs the complete checkpoint on the minimum supported Python and tests the current Python.
- `CodeQL` performs Python semantic analysis on changes and on a weekly schedule.
- `Dependency review` rejects pull requests that add dependencies with moderate-or-higher known
  vulnerabilities.
- Dependabot proposes weekly Python and GitHub Actions updates.

Every workflow has explicit time limits and read-only repository access. CodeQL alone receives
`security-events: write`, which it needs to upload results. Checkout credentials are not retained.
Action major versions follow each action's supported update channel, while Dependabot keeps those
references visible for review.

## GitHub settings after push

Hosted behavior cannot be proven locally. After the workflows are pushed and pass, configure branch
protection for `main` to require the CI, CodeQL, and dependency-review checks; require pull-request
review; block force pushes; and enable secret scanning and push protection when the repository plan
supports them.

An open-source license remains a separate owner decision and is intentionally not selected by this
hardening work.

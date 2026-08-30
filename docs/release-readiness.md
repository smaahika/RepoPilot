# Release Readiness

RepoPilot's first release is `0.1.0`, not `1.0`. The project has a complete, narrow MVP, but its
interfaces may evolve and its scripted evaluation does not measure live-model capability.

## Release evidence

- The final replay matches 8/8 expected behaviors, with 6/8 genuine task successes and two
  intentional safety or budget failures.
- The local checkpoint covers formatting, linting, strict typing, repository hygiene, 170 tests,
  wheel creation, clean installation, and the installed CLI.
- CI and CodeQL passed on the final-polish commit before the version promotion.
- The package uses one version source, declares the SPDX `MIT` expression, and ships the MIT text in
  its wheel.
- Limitations, evaluation semantics, failure cases, and design tradeoffs are documented.

## Personal-project release process

1. Run `python scripts/evaluate.py` and compare it with the checked baseline.
2. Run `python scripts/check.py`.
3. Commit and push the version and license changes to `main`.
4. Confirm CI and CodeQL pass on that commit.
5. Optionally create a `v0.1.0` GitHub release from [CHANGELOG.md](../CHANGELOG.md).

Branch protection, a release pull request, mandatory reviews, and automated profile management are
not required for this personal portfolio project.

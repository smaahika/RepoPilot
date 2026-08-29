# Release Readiness

## Target

The first release target is `v0.1.0`, not `v1.0`. RepoPilot has a complete, narrow MVP, but local
execution is not a security sandbox, Docker is intentionally limited, and model-capability results
are not yet measured. A `0.x` version communicates that the public interface and security model may
still change while allowing a real, reproducible release.

The package remains `0.1.0.dev0` until every owner-controlled gate below is resolved. The version is
defined once in `src/repopilot/__init__.py`; build metadata reads that value and the clean-install
checkpoint verifies they match.

## Verified evidence

As of August 28, 2026:

- The final scripted benchmark reproduced 8/8 expected behaviors and 6/8 successful tasks. Its two
  failures intentionally validate patch rejection and budget exhaustion.
- The local checkpoint passed formatting, linting, strict typing, repository hygiene, 170 tests,
  wheel creation, clean installation, metadata consistency, and the installed CLI smoke test. The
  optional live Docker integration test was skipped because it is environment-dependent.
- [CI](https://github.com/smaahika/RepoPilot/actions/runs/33236730314) and
  [CodeQL](https://github.com/smaahika/RepoPilot/actions/runs/33236730310) passed for commit `a9ef002`.
- GitHub secret scanning and push protection are enabled.
- The public repository has no detected license, Dependabot security updates are disabled, and
  `main` has no branch protection. These are recorded as open gates rather than hidden.

The final-polish commit will require its own hosted run; success on an earlier commit is supporting
evidence, not proof that a later release candidate is green.

## Release gates

- [x] Deterministic demo runs without an API key or network access.
- [x] Final offline benchmark matches the checked baseline.
- [x] Local quality, security, package, installation, and CLI checks pass.
- [x] CI and CodeQL have passed on the pre-release codebase.
- [x] Secret scanning and push protection are enabled.
- [x] Limitations, evaluation semantics, failure cases, and design tradeoffs are documented.
- [ ] Select and add an open-source license.
- [ ] Enable Dependabot security updates.
- [ ] Protect `main` with required hosted checks and pull-request review.
- [ ] Validate dependency review on a pull request.
- [ ] Record and add the planned short demo video or GIF.
- [ ] Change `__version__` from `0.1.0.dev0` to `0.1.0`.
- [ ] Run local and hosted checks on the exact release commit.
- [ ] Create and push the annotated `v0.1.0` tag.
- [ ] Create a GitHub release from [CHANGELOG.md](../CHANGELOG.md).
- [ ] Pin RepoPilot on the owner's GitHub profile.

## Release procedure

After the owner-controlled gates are resolved:

1. Change `src/repopilot/__init__.py` to `0.1.0` and date the changelog.
2. Run `python scripts/evaluate.py` and compare the result with the checked baseline.
3. Run `python scripts/check.py` from the development environment.
4. Commit the release candidate and push it without tagging.
5. Wait for CI, CodeQL, and dependency review to pass on the exact commit.
6. Create an annotated `v0.1.0` tag on that commit and push the tag.
7. Publish the changelog section as the GitHub release notes and verify the fresh-clone quick start.

Tagging comes after hosted verification so a failed commit never becomes the immutable release
reference.

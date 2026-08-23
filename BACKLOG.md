# RepoPilot Backlog

The backlog follows the two-week plan but is ordered by dependency and risk. Each item should land
as a small, tested commit. Scope may be reduced after the Day 7 checkpoint.

## Day 1 — Scope and design

- [x] Record problem statement, user story, success criteria, and non-goals.
- [x] Define architecture, state lifecycle, trust boundaries, and initial budgets.
- [x] Record initial tool contracts and design decisions.
- [x] Create package, test, and quality-tool skeleton.

## Day 2 — Repository and workspace layer

- [x] Define workspace/repository models and typed failures.
- [x] Create and clean up unique per-run directories.
- [x] Copy a local repository without mutating its source.
- [x] Clone a public repository through an injectable Git adapter.
- [x] Resolve paths safely and reject traversal and symlink escapes.
- [x] Build a bounded, ignore-aware file inventory.
- [x] Generate a unified diff against the initial checkout.
- [x] Test isolation, cleanup, path attacks, limits, and Git failures.

## Day 3 — Tool and policy layer

- [x] Implement validated list, search, read, patch, diff, and command contracts.
- [x] Enforce command allowlists, timeouts, cwd checks, and output limits.
- [x] Add success and adversarial policy tests.

## Day 4 — Model adapter and planning

- [x] Define provider-neutral model and usage protocols.
- [x] Implement structured plan and tool-call schemas.
- [x] Add a scripted fake model and malformed-response tests.
- [x] Implement the first direct provider adapter behind the protocol.

## Day 5 — Controller vertical slice

- [x] Implement states, events, transition table, and run budgets.
- [x] Orchestrate initialize, inspect, plan, edit, and verify phases.
- [x] Log every transition.
- [x] Complete one deterministic end-to-end run with fakes.

## Day 6 — Verification and retry loop

- [x] Normalize test and lint outcomes.
- [x] Add reflect/retry behavior, no-progress detection, and termination reasons.
- [x] Fix one intentionally broken fixture repository end to end.

## Day 7 — MVP checkpoint

- [x] Resolve architectural debt and strengthen exception boundaries.
- [x] Run formatting, lint, typing, unit, and integration checks.
- [x] Review scope using the working vertical slice.
- [ ] Tag `v0.1.0` after CLI composition and durable run artifacts are complete.

## Days 8–14 — Prioritized after checkpoint

- [x] Wire validated configuration, the real provider adapter, and the controller into the CLI.
- [x] Persist reports, diffs, JSONL events, command logs, timing, and usage.
- [ ] Select and add an open-source license before public release.
- [x] Add and document Docker isolation.
- [x] Add context ranking, compaction, and measurements.
- [ ] Build 6–10 deterministic benchmark tasks and a metrics runner.
- [ ] Produce the demo-focused README and architecture visuals.
- [ ] Add CI, installation verification, and repository security checks.
- [ ] Run final benchmarks, document failures, and prepare interview stories.

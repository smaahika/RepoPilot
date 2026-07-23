# RepoPilot Product and System Design

## Problem statement

Small repository changes are often easy to describe but costly to execute reliably. An engineer
must locate the relevant code, understand local conventions, make a scoped edit, run the correct
checks, and communicate the result. General-purpose coding agents can attempt this workflow, but
their behavior is difficult to trust when execution is unbounded or opaque.

RepoPilot accepts a repository and a narrowly scoped engineering task, works only in a disposable
copy, and returns a tested patch plus an inspectable execution report. The product is a reference
implementation of a bounded agent workflow, not a replacement for an IDE or human review.

## Primary user story

As a developer, I can provide a local or public Git repository and a small task, then receive a
reviewable patch, verification results, and a transparent record of what the agent attempted.

## Success criteria

The first release is successful when it can:

1. preserve the source repository while creating an isolated per-run workspace;
2. inspect a small supported repository and produce a structured implementation plan;
3. apply a non-empty, path-safe patch through validated tools;
4. execute explicitly allowed verification commands with bounded resources;
5. stop predictably on success, failure, budget exhaustion, or lack of progress; and
6. emit a patch, report, event log, and useful failure details for every completed run.

Product quality will be measured using deterministic benchmark tasks. The main metrics are task
success rate, regression rate, iteration count, runtime, tool failures, and model usage.

## MVP scope

### Must have

- A CLI accepting a repository, task, optional verification command, and run budgets.
- Repository copy or clone into a generated per-run workspace.
- Bounded inventory, text search, file read, patch write, diff, and command tools.
- A provider-independent model interface and structured planner output.
- An explicit run state machine and bounded edit/verify/reflection loop.
- Normalized verification results and failure-aware termination.
- Filesystem artifacts, JSONL events, automated tests, and a reproducible demo.

### Deferred until the core loop is reliable

- Docker execution and operating-system resource limits.
- File-ranking and context-compaction heuristics.
- A benchmark runner, cost reporting, and richer run summaries.
- GitHub integration, a web interface, and additional model providers.

### Non-goals

- Supporting arbitrary languages and repositories.
- Giving the model unrestricted shell or filesystem access.
- Deploying changes, opening or merging pull requests, or modifying the source repository.
- Running a long-lived service or background agent.
- Building a multi-agent framework or a general autonomous IDE.
- Claiming production-grade isolation from path checks or Docker alone.

## Trust boundaries

Model output, repository contents, repository-provided configuration, patches, command arguments,
and subprocess output are untrusted. They cross into the system only through typed validation and
policy checks. The run controller is trusted to enforce policy and budgets; it never delegates
those responsibilities to a prompt.

The original repository is read-only from RepoPilot's perspective. All model-directed reads,
writes, and commands target a generated workspace whose canonical path is known to the repository
service. Paths are resolved before access and rejected if they escape that root, including through
symbolic links.

## Initial budgets

Defaults are conservative starting points and will be tuned using benchmarks rather than intuition.

| Budget | Initial default | Enforcement owner |
| --- | ---: | --- |
| End-to-end runtime | 10 minutes | Run controller |
| Edit/verify iterations | 3 | Run controller |
| Model calls | 8 | Model adapter and controller |
| Single command runtime | 2 minutes | Command runner |
| Captured command output | 1 MiB | Command runner |
| Single text file read | 256 KiB | Filesystem tools |
| Inventory entries | 5,000 | Repository service |

Every limit is configurable within a system-defined maximum. Reaching a limit produces a typed
result and explicit termination reason rather than an unhandled exception.

## Initial tool contracts

All tools return a normalized result containing success status, duration, and either typed data or
a structured error. User-facing errors may include safe paths and bounded output; they must not
include environment secrets.

| Tool | Accepted input | Required guarantees |
| --- | --- | --- |
| `list_files` | Optional relative root and count limit | Ignore rules, stable ordering, bounded count, no traversal |
| `search_text` | Query, relative roots, regex flag, result limit | Bounded output, text files only, no shell interpolation |
| `read_file` | Relative path and optional line range | Regular text file, byte cap, no symlink escape |
| `write_patch` | Unified diff | Workspace-only paths, patch validation, atomic failure |
| `run_command` | Tokenized argv, relative cwd, timeout | Allowlist, no shell, output cap, timeout, normalized exit |
| `git_diff` | Optional path filters | Workspace diff only, bounded output, no mutation |
| `test_status` | Command result collection | Stable passed/failed/error/timeout classification |

`run_command` receives an argument vector rather than a shell string. Commands are selected from a
policy allowlist, working directories are resolved under the workspace, and shell expansion is not
available. Docker will later strengthen process isolation; it will not replace application policy.

## Termination rules

A run completes successfully only when its diff is non-empty and required verification passes. It
fails when initialization or planning cannot produce valid input for the next phase, when a safety
policy rejects an unrecoverable action, or when verification still fails after the retry budget.
It stops with a distinct budget-exhausted reason when a hard limit is reached. Two consecutive
iterations with no meaningful diff change terminate as no-progress.

Regardless of outcome, finalization attempts to write the report and all safe artifacts collected
so far.

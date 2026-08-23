# Evaluation Harness

RepoPilot's offline evaluation suite measures complete controller runs against versioned repository
fixtures. It is deliberately separate from unit tests: unit tests establish component correctness,
while evaluation records whether the assembled agent reaches expected repository outcomes.

Run the baseline from the repository root:

```bash
python scripts/evaluate.py
```

The runner loads `evaluation/cases.json`, materializes a fresh Git repository per case, executes the
real repository service, controller, tools, patch path, and verification command, and atomically
writes the ignored `evaluation/results/latest.json`. It exits unsuccessfully when an observed result
differs from the versioned expectation.

The checked-in reference is updated only deliberately:

```bash
python scripts/evaluate.py --output evaluation/results/baseline.json
```

This prevents an ordinary failing run from silently redefining the baseline while still preserving
its complete latest report for diagnosis.

## Metrics semantics

The report keeps two success measurements separate:

- **Expectation pass rate** is a regression metric. It asks whether the observed termination,
  changed files, verification sequence, and required or forbidden patch fragments match the case.
- **Task success rate** counts only runs that terminate with `success`. Expected safety or budget
  failures remain failed tasks even when the harness correctly predicts them.

The report also records model calls, tool calls, iterations, elapsed time, provider input tokens when
available, and context characters before and after selection. Scripted replay has no provider usage,
so token totals are `null` rather than invented.

## Offline replay v1

| Case | Behavior | Expected task outcome |
| --- | --- | --- |
| `update_greeting` | Read and update one function | Success |
| `fix_double` | Repair arithmetic behavior | Success |
| `implement_slugify` | Implement a missing function | Success |
| `raise_retry_limit` | Search for and update configuration | Success |
| `update_two_modules` | Coordinate a two-file patch | Success |
| `recover_after_failure` | Reflect after a failed test and correct the patch | Success |
| `reject_ungrounded_patch` | Reject a patch whose source context is false | Edit failure |
| `exhaust_retry_budget` | Stop after a failed change consumes the edit budget | Budget exhaustion |

The checked-in baseline records:

- 8/8 expected outcomes matched;
- 6/8 tasks succeeded, for a 75% task-success rate;
- 24 model calls, 31 tool calls, and 8 edit iterations; and
- 9,984 original context characters versus 12,462 selected characters.

The context increase is intentional evidence, not a favorable result: on tiny repositories and
short histories, selection metadata adds about 25% overhead. Day 11 stress cases show substantial
reductions at large inputs, so a future threshold could bypass compaction for small requests.

## What this baseline does not prove

The scripted responses encode fixed actions for deterministic replay. Therefore, this suite measures
orchestration, policy, verification, retry, and metrics regressions; it does not measure a real
model's coding ability or compare providers. A live-model benchmark can reuse the case and report
schemas, but must record model identity, repeated trials, token usage, cost, and variance before its
success rate is presented as a capability result.

# RepoPilot Interview Guide

Use this guide as evidence, not a script to memorize word for word. Keep the distinction between
deterministic orchestration results and real-model capability explicit.

## Two-minute explanation

RepoPilot is a constrained coding agent for small repository tasks. A user supplies one task and a
local repository or credential-free public HTTPS URL. RepoPilot creates a disposable copy, selects
bounded context, asks a provider through typed schemas for a plan and one action at a time, validates
every tool request, applies a constrained patch, and runs an allowlisted verification command.

The main design choice is that the controller—not the language model—owns authority. It enforces the
state machine, model and tool budgets, timeouts, edit retries, path policy, and termination. Model
output is treated as untrusted data. A run can use local verification or an opt-in Docker backend
with no network and resource limits, although Docker is documented as risk reduction rather than a
complete security boundary.

Every terminal outcome produces a patch, report, events, command logs, timing, usage, and an explicit
termination reason. An eight-case offline replay exercises the production controller and matches all
expected behaviors; six tasks succeed and two deliberately remain failures to prove patch rejection
and budget exhaustion. That 75% is task success, not a model score. The project is protected by 170
tests, strict typing, package-install smoke tests, CI, CodeQL, dependency review, and secret checks.

## Ten-minute walkthrough

1. **Problem and scope — 1 minute:** one dependable patch workflow, not a general autonomous IDE.
2. **Authority boundaries — 2 minutes:** disposable workspace, typed model output, validated tools,
   shell-free argument vectors, command allowlist, and source-repository preservation.
3. **Control loop — 2 minutes:** explicit states, budgets, verification normalization, reflection,
   retry eligibility, no-progress detection, and categorized terminal outcomes.
4. **Observability — 1 minute:** atomic report, patch, JSONL events, bounded command logs, redaction,
   timing, and provider-reported usage.
5. **Evaluation — 2 minutes:** replay versus task success, the six successful cases, the two honest
   failures, and why tiny-input context overhead was retained in the results.
6. **Tradeoffs and next step — 2 minutes:** local execution versus Docker, heuristics versus semantic
   retrieval, one tool call per turn versus latency, and repeated live-model trials as the next
   evidence-generating experiment.

## Evidence-backed engineering stories

### Preserving pre-existing user changes

- **Problem:** Diffing a copied dirty repository against its `HEAD` would incorrectly label the
  user's staged, unstaged, and untracked work as RepoPilot output.
- **Decision:** Build a private Git baseline from the copied repository's current visible contents
  and diff later edits against that immutable tree.
- **Result:** The source and copied index remain untouched, while generated patches contain only the
  agent's changes. The cost is extra baseline storage and explicit submodule/worktree limitations.

### Separating process success from verification success

- **Problem:** `pytest` returning exit code 1 means the command ran successfully but tests failed. If
  that were represented as a tool crash, the controller would lose the output needed to reflect.
- **Decision:** Return ordinary command exits as tool results, then normalize them separately into
  passed, failed, timeout, or error verification outcomes.
- **Result:** Retries respond to test evidence, while policy denial and infrastructure failures keep
  distinct termination reasons and metrics.

### Preventing useless retry loops

- **Problem:** A model can make mechanically valid edits that leave the same failing patch, consuming
  budget without progress.
- **Decision:** Compare visible diffs after failed verification attempts and terminate when two
  consecutive attempts are identical.
- **Result:** The stopping rule is deterministic and cheap. It does not claim to detect semantically
  equivalent rewrites, which would require stronger evidence and more complexity.

### Reporting an unfavorable context result

- **Problem:** Context selection was expected to reduce prompts, but the tiny benchmark grew from
  9,984 to 12,462 characters because metadata cost more than the selected content saved.
- **Decision:** Keep the result, document why large stress fixtures still benefit, and identify a
  future small-input bypass threshold instead of tuning the metric after seeing it.
- **Result:** The evaluation demonstrates honest measurement and leads to a concrete optimization
  hypothesis without overstating current performance.

### Keeping expected failures out of the success rate

- **Problem:** A regression harness can correctly predict a safety rejection and accidentally count
  that expected failure as a successful coding task.
- **Decision:** Report expectation conformance and task success as separate metrics.
- **Result:** The suite shows 8/8 behavioral matches and 6/8 task successes, preserving useful failure
  coverage without inflating capability claims.

## Resume bullets

- Built a Python coding agent with a controller-owned state machine, typed model/tool boundaries,
  disposable Git workspaces, bounded patch and command execution, and optional network-disabled
  Docker verification.
- Designed durable run observability—atomic reports, diffs, JSONL events, bounded command logs,
  timing, usage, and explicit termination reasons—across success and failure paths.
- Created an eight-case deterministic evaluation harness with 100% behavioral conformance and 75%
  task completion, explicitly separating expected safety failures from successful code changes.
- Hardened packaging and delivery with 170 automated tests, strict type and lint checks, clean-wheel
  installation verification, Python 3.12/3.14 CI, CodeQL, dependency review, and secret scanning.

## Questions to answer precisely

- **Why not use an agent framework?** The orchestration and safety behavior are the portfolio signal;
  a direct adapter keeps budgets, retries, schemas, and state transitions visible and testable.
- **Is Docker a sandbox?** It removes network access and applies mount, capability, privilege, PID,
  CPU, memory, output, and time limits, but it shares the host kernel and is not a multi-tenant
  isolation guarantee.
- **Does 75% mean the model solved 75%?** No. Scripted responses make it an orchestration regression
  metric. Real-model claims require repeated trials, provider identity, token usage, cost, and
  variance.
- **What would you build next?** Repeated live-model evaluation first, because it creates evidence for
  whether context policy, retry strategy, or provider behavior is actually the next bottleneck.

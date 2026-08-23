# Deterministic Demo

The demo is a no-network presentation path for RepoPilot's real orchestration. It materializes a
temporary Git repository, supplies a fixed sequence of model decisions, and exercises the production
controller, repository service, tools, patch validation, pytest verification, cleanup, and artifact
writer.

Run it from an installed development environment:

```bash
python scripts/demo.py
```

By default, its temporary files are cleaned up after the transcript is printed. Preserve the fixture
and artifacts at a new path when demonstrating their contents:

```bash
python scripts/demo.py --output-dir /tmp/repopilot-demo
```

The report will be available at `/tmp/repopilot-demo/managed/runs/demo/report.md`.

## Canonical transcript

```text
RepoPilot deterministic demo
Task: Change greeting() to return hello RepoPilot.
Result: success
Changed files: greeting.py
Verification: passed
Iterations: 1; model calls: 3; tool calls: 4
Artifacts: commands/001-test.log, events.jsonl, patch.diff, report.md

Patch:
diff --git a/greeting.py b/greeting.py
index a09f784..e0d1808 100644
--- a/greeting.py
+++ b/greeting.py
@@ -1,2 +1,2 @@
 def greeting() -> str:
-    return "hello"
+    return "hello RepoPilot"
```

An integration test runs this command path and asserts its status, changed file, verification result,
artifact set, and added patch line. Timing and temporary paths are intentionally omitted so the
presentation stays stable across machines.

## 60–90 second walkthrough

1. **Problem, 10 seconds:** “RepoPilot turns one scoped repository task into a tested patch while
   keeping the source repository unchanged.”
2. **Command, 10 seconds:** Run `python scripts/demo.py` and point out that it needs no API key
   because the presentation uses deterministic model decisions.
3. **Control flow, 20 seconds:** Explain that the real controller inventories a disposable copy,
   requests a structured plan, allows one validated tool call per turn, applies the patch, and runs
   pytest.
4. **Evidence, 20 seconds:** Highlight the successful verification, bounded call counters, unified
   diff, and four persisted artifacts.
5. **Honest boundary, 15 seconds:** Clarify that scripted replay proves orchestration behavior, not
   model intelligence; the eight-case suite reports task success separately from expected failures.

## What is real and what is scripted

The repository copy, Git baseline, state machine, budgets, context assembly, tool execution, patch
validation, pytest subprocess, cleanup, and artifact writes are real. Only the model responses are
preselected. That split makes the demo reproducible while keeping its claim precise.

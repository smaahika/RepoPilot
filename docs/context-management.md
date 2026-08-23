# Context Management

RepoPilot treats model context as a bounded application resource. A fresh `ContextSession` owns
selection for one run, so measurements never leak between runs and provider adapters remain unaware
of repository heuristics.

## Selection strategy

Planning ranks inventory entries using deterministic path evidence:

1. paths explicitly named in the task;
2. task terms appearing in path components;
3. project entry points such as `pyproject.toml`, `package.json`, and `README.md`;
4. tests; and
5. stable lexical ordering for ties.

Generated, vendored, lock, source-map, and minified paths receive a lower score. The planner receives
at most 200 entries and 40,000 serialized characters. Ranking does not read files or claim semantic
relevance; the model must still use search and read tools to gather evidence.

During editing, the current plan remains visible. The three newest tool observations retain bounded
head-and-tail evidence, while older observations become status summaries containing the call ID,
tool name, success state, truncation state, and original output size. RepoPilot deliberately calls
these completed actions rather than completed plan steps because tool calls do not prove that a plan
objective is finished.

Reflection retains diff headers, hunk locations, and changed lines instead of taking an arbitrary
prefix. Command stdout and stderr keep their tails because test and compiler summaries commonly
appear at the end. These are heuristics, not guarantees; Day 12 benchmarks will test whether their
defaults preserve enough evidence.

## Measurement

Every model request records the exact UTF-8-independent Python character count of its unselected and
selected JSON input, plus the number of entries or evidence items compacted. The run report includes
per-operation and aggregate measurements. Character counts are a deterministic provider-neutral
proxy, while provider-reported input tokens remain the authoritative usage measurement.

A deterministic synthetic stress sample produced these values with the default policy:

| Operation | Before | After | Compacted items |
| --- | ---: | ---: | ---: |
| Plan over 5,000 files | 303,951 chars | 12,322 chars | 4,800 |
| Edit after 10 maximum-size observations | 501,052 chars | 51,232 chars | 10 |
| Reflect on a large diff and command output | 1,200,348 chars | 20,472 chars | 3 |

These figures demonstrate enforcement, not model quality. The evaluation harness must measure task
success and compare policy variants before the heuristic weights are treated as tuned.

## Limits and tradeoffs

- Filename ranking cannot discover relevance that is absent from the task and path names.
- Older action summaries intentionally discard content; a later action may need to reread a file.
- Diff-focused reflection omits unchanged context lines.
- Character budgets do not map exactly to tokens across providers or languages.
- Context compaction adds small structural metadata, so tiny requests can become slightly larger.

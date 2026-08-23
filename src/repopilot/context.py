"""Deterministic selection, compaction, and measurement of model context."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from repopilot.model_models import ImplementationPlan, Reflection
from repopilot.models import FileEntry, RepositoryInventory
from repopilot.run_models import ContextMetric

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
_PROJECT_FILES = {
    "cargo.toml": 14,
    "go.mod": 14,
    "package.json": 14,
    "pyproject.toml": 14,
    "readme.md": 10,
    "requirements.txt": 12,
}
_LOW_VALUE_PARTS = {"dist", "generated", "node_modules", "vendor"}


class ContextPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    max_planning_entries: int = Field(default=200, ge=1, le=1_000)
    max_planning_chars: int = Field(default=40_000, ge=20_000, le=150_000)
    recent_observations: int = Field(default=3, ge=1, le=10)
    max_observation_chars: int = Field(default=20_000, ge=1_000, le=50_000)
    max_observation_chars_total: int = Field(default=50_000, ge=2_000, le=100_000)
    max_diff_chars: int = Field(default=40_000, ge=2_000, le=100_000)
    max_command_output_chars: int = Field(default=10_000, ge=1_000, le=50_000)


class ContextSession:
    """Build bounded inputs and retain per-call reduction measurements."""

    def __init__(self, policy: ContextPolicy | None = None) -> None:
        self._policy = policy or ContextPolicy()
        self._metrics: list[ContextMetric] = []

    @property
    def metrics(self) -> tuple[ContextMetric, ...]:
        return tuple(self._metrics)

    def planning_input(self, task: str, inventory: RepositoryInventory) -> str:
        original = {
            "task": task,
            "repository_inventory": [_inventory_item(entry) for entry in inventory.entries],
        }
        selected_entries: list[dict[str, object]] = []
        ranked = sorted(inventory.entries, key=lambda entry: _inventory_rank(task, entry))
        for entry in ranked[: self._policy.max_planning_entries]:
            candidate = [*selected_entries, _inventory_item(entry)]
            payload = _planning_payload(task, candidate, len(inventory.entries))
            if len(_serialize(payload)) > self._policy.max_planning_chars:
                break
            selected_entries = candidate

        selected = _planning_payload(task, selected_entries, len(inventory.entries))
        return self._record(
            "create_plan",
            original,
            selected,
            compacted_items=len(inventory.entries) - len(selected_entries),
        )

    def editing_input(
        self,
        task: str,
        plan: ImplementationPlan,
        observations: Sequence[BaseModel],
        reflection: Reflection | None,
    ) -> str:
        serialized_observations = [
            observation.model_dump(mode="json") for observation in observations
        ]
        original = {
            "task": task,
            "plan": plan.model_dump(mode="json"),
            "observations": serialized_observations,
            "reflection": None if reflection is None else reflection.model_dump(mode="json"),
        }
        split_at = max(0, len(serialized_observations) - self._policy.recent_observations)
        older = serialized_observations[:split_at]
        recent = serialized_observations[split_at:]
        summaries = [_observation_summary(observation) for observation in older]
        compacted_recent, clipped = self._compact_recent_observations(recent)
        selected = {
            "task": task,
            "plan": _compact_plan(plan),
            "action_history": {
                "completed_action_summaries": summaries,
                "recent_evidence": compacted_recent,
            },
            "reflection": None if reflection is None else reflection.model_dump(mode="json"),
        }
        return self._record(
            "select_tool",
            original,
            selected,
            compacted_items=len(older) + clipped,
        )

    def reflection_input(
        self,
        task: str,
        plan: ImplementationPlan,
        patch: str,
        *,
        status: str,
        check_kind: str,
        message: str,
        stdout: str,
        stderr: str,
    ) -> str:
        original = {
            "task": task,
            "plan": plan.model_dump(mode="json"),
            "patch": patch,
            "status": status,
            "check_kind": check_kind,
            "message": message,
            "stdout": stdout,
            "stderr": stderr,
        }
        focused_patch = _compact_diff(patch, self._policy.max_diff_chars)
        focused_stdout = _tail_text(stdout, self._policy.max_command_output_chars)
        focused_stderr = _tail_text(stderr, self._policy.max_command_output_chars)
        selected = {
            **original,
            "plan": _compact_plan(plan),
            "patch": focused_patch,
            "stdout": focused_stdout,
            "stderr": focused_stderr,
            "evidence_compaction": {
                "patch": focused_patch != patch,
                "stdout": focused_stdout != stdout,
                "stderr": focused_stderr != stderr,
            },
        }
        compacted = sum(
            original_value != selected_value
            for original_value, selected_value in (
                (patch, focused_patch),
                (stdout, focused_stdout),
                (stderr, focused_stderr),
            )
        )
        return self._record(
            "reflect_on_failure",
            original,
            selected,
            compacted_items=compacted,
        )

    def _compact_recent_observations(
        self,
        observations: Sequence[dict[str, object]],
    ) -> tuple[list[dict[str, object]], int]:
        remaining = self._policy.max_observation_chars_total
        selected: list[dict[str, object]] = []
        clipped = 0
        for observation in reversed(observations):
            output = str(observation.get("output", ""))
            limit = min(self._policy.max_observation_chars, remaining)
            compacted = _head_tail_text(output, limit)
            if compacted != output:
                clipped += 1
            selected.append(
                {
                    **observation,
                    "output": compacted,
                    "truncated": bool(observation.get("truncated")) or compacted != output,
                }
            )
            remaining = max(0, remaining - len(compacted))
        selected.reverse()
        return selected, clipped

    def _record(
        self,
        operation: str,
        original: object,
        selected: object,
        *,
        compacted_items: int,
    ) -> str:
        original_input = _serialize(original)
        selected_input = _serialize(selected)
        self._metrics.append(
            ContextMetric(
                operation=operation,
                original_chars=len(original_input),
                selected_chars=len(selected_input),
                compacted_items=compacted_items,
            )
        )
        return selected_input


def _inventory_rank(task: str, entry: FileEntry) -> tuple[int, str]:
    task_lower = task.casefold()
    path_lower = entry.path.casefold()
    path_tokens = set(_TOKEN_PATTERN.findall(path_lower))
    task_tokens = set(_TOKEN_PATTERN.findall(task_lower))
    basename = path_lower.rsplit("/", 1)[-1]
    parts = set(path_lower.split("/"))
    score = 100 if len(path_lower) >= 3 and path_lower in task_lower else 0
    score += 12 * len(task_tokens & path_tokens)
    score += _PROJECT_FILES.get(basename, 0)
    score += 3 if basename.startswith("test_") or basename.endswith("_test.py") else 0
    score -= 20 if basename.endswith((".lock", ".min.js", ".map")) else 0
    score -= 20 if parts & _LOW_VALUE_PARTS else 0
    return -score, entry.path


def _inventory_item(entry: FileEntry) -> dict[str, object]:
    return {"path": entry.path, "size_bytes": entry.size_bytes, "kind": entry.kind.value}


def _planning_payload(
    task: str,
    entries: list[dict[str, object]],
    total_entries: int,
) -> dict[str, object]:
    return {
        "task": task,
        "inventory_summary": {
            "total_entries": total_entries,
            "selected_entries": len(entries),
            "omitted_entries": total_entries - len(entries),
        },
        "repository_inventory": entries,
    }


def _observation_summary(observation: dict[str, object]) -> dict[str, object]:
    return {
        "call_id": observation.get("call_id"),
        "tool_name": observation.get("tool_name"),
        "ok": observation.get("ok"),
        "output_chars": len(str(observation.get("output", ""))),
        "truncated": observation.get("truncated"),
    }


def _compact_plan(plan: ImplementationPlan) -> dict[str, object]:
    return {
        "summary": plan.summary,
        "steps": [
            {
                "id": step.id,
                "objective": step.objective,
                "files": [_head_text(path, 300) for path in step.files[:8]],
                "files_omitted": max(0, len(step.files) - 8),
                "verification": [_head_text(check, 300) for check in step.verification[:5]],
                "checks_omitted": max(0, len(step.verification) - 5),
            }
            for step in plan.steps
        ],
        "assumptions": [_head_text(value, 500) for value in plan.assumptions[:5]],
        "assumptions_omitted": max(0, len(plan.assumptions) - 5),
    }


def _compact_diff(value: str, limit: int) -> str:
    prefixes = (
        "diff --git ",
        "index ",
        "new file mode ",
        "deleted file mode ",
        "rename from ",
        "rename to ",
        "Binary files ",
        "GIT binary patch",
        "literal ",
        "delta ",
        "--- ",
        "+++ ",
        "@@",
        "+",
        "-",
    )
    focused = "\n".join(line for line in value.splitlines() if line.startswith(prefixes))
    if value.endswith("\n") and focused:
        focused += "\n"
    return _head_tail_text(focused or value, limit)


def _head_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 0:
        return ""
    marker = "\n...[truncated]"
    if limit <= len(marker):
        return value[:limit]
    return value[: max(0, limit - len(marker))] + marker


def _tail_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 0:
        return ""
    marker = "[truncated]...\n"
    if limit <= len(marker):
        return value[-limit:]
    return marker + value[-(limit - len(marker)) :]


def _head_tail_text(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 0:
        return ""
    marker = "\n...[truncated]...\n"
    if limit <= len(marker):
        return value[-limit:]
    available = max(0, limit - len(marker))
    head = available // 2
    tail = available - head
    return value[:head] + marker + value[-tail:]


def _serialize(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

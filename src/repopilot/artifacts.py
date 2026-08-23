"""Bounded, atomic filesystem persistence for terminal run evidence."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from repopilot.errors import ArtifactPersistenceError
from repopilot.run_models import RunRequest, RunResult
from repopilot.verification import VerificationResult

_REPORT_LIMIT_BYTES = 262_144
_EVENTS_LIMIT_BYTES = 262_144
_PATCH_LIMIT_BYTES = 1_048_576
_COMMAND_LOG_LIMIT_BYTES = 1_100_000
_REDACTION = "[REDACTED]"


class FilesystemArtifactWriter:
    """Write a complete, no-overwrite artifact set beneath one trusted run root."""

    def __init__(self, run_root: Path, *, redactions: tuple[str, ...] = ()) -> None:
        self._run_root = run_root.resolve()
        self._redactions = tuple(
            sorted({value for value in redactions if value}, key=len, reverse=True)
        )

    def write(self, request: RunRequest, result: RunResult) -> None:
        artifact_path = self._validated_artifact_path(result)
        try:
            command_directory = artifact_path / "commands"
            command_directory.mkdir(mode=0o700)
            command_names = self._write_command_logs(command_directory, result)
            self._write_text(
                artifact_path / "events.jsonl",
                self._events_jsonl(result),
                _EVENTS_LIMIT_BYTES,
            )
            self._write_text(
                artifact_path / "patch.diff",
                result.patch,
                _PATCH_LIMIT_BYTES,
            )
            self._write_text(
                artifact_path / "report.md",
                self._report(request, result, command_names),
                _REPORT_LIMIT_BYTES,
            )
        except ArtifactPersistenceError:
            raise
        except OSError as error:
            raise ArtifactPersistenceError(
                f"Could not persist artifacts for run {result.run_id!r}: {error}."
            ) from error

    def _validated_artifact_path(self, result: RunResult) -> Path:
        if result.artifact_path is None:
            raise ArtifactPersistenceError(
                f"Run {result.run_id!r} failed before an artifact directory was allocated."
            )
        expected_parent = self._run_root / "runs"
        expected = expected_parent / result.run_id
        path = result.artifact_path
        if path != expected or path.is_symlink() or not path.is_dir():
            raise ArtifactPersistenceError("Refusing to write outside the allocated run directory.")
        try:
            if path.resolve(strict=True).parent != expected_parent.resolve(strict=True):
                raise ArtifactPersistenceError(
                    "Refusing to write outside the allocated run directory."
                )
        except OSError as error:
            raise ArtifactPersistenceError(
                "Could not validate the run artifact directory."
            ) from error
        return path

    def _write_command_logs(
        self,
        directory: Path,
        result: RunResult,
    ) -> dict[int, str]:
        names: dict[int, str] = {}
        sequence = 0
        for verification_index, verification in enumerate(result.verifications, start=1):
            if not verification.argv:
                continue
            sequence += 1
            name = f"{sequence:03d}-{verification.check_kind.value.replace('_', '-')}.log"
            names[verification_index] = name
            self._write_text(
                directory / name,
                self._command_log(verification),
                _COMMAND_LOG_LIMIT_BYTES,
            )
        return names

    def _write_text(self, path: Path, content: str, limit: int) -> None:
        redacted = self._redact(content)
        payload = redacted.encode("utf-8")
        if len(payload) > limit:
            raise ArtifactPersistenceError(
                f"Artifact {path.name!r} exceeds its {limit} byte limit."
            )

        descriptor, temporary_name = tempfile.mkstemp(prefix=".repopilot-", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _redact(self, content: str) -> str:
        for secret in self._redactions:
            content = content.replace(secret, _REDACTION)
        return content

    @staticmethod
    def _events_jsonl(result: RunResult) -> str:
        records = []
        for transition in result.transitions:
            records.append(
                json.dumps(
                    {
                        "elapsed_ms": transition.elapsed_ms,
                        "event": transition.event.value,
                        "event_type": "state_transition",
                        "next_phase": transition.next_phase.value,
                        "previous_phase": transition.previous_phase.value,
                        "run_id": transition.run_id,
                        "schema_version": 1,
                        "sequence": transition.sequence,
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
        return "" if not records else "\n".join(records) + "\n"

    @staticmethod
    def _command_log(verification: VerificationResult) -> str:
        argv = json.dumps(verification.argv, ensure_ascii=False)
        exit_code = "none" if verification.exit_code is None else str(verification.exit_code)
        return (
            f"argv: {argv}\n"
            f"status: {verification.status.value}\n"
            f"exit_code: {exit_code}\n"
            f"duration_ms: {verification.duration_ms}\n"
            f"message: {verification.message}\n\n"
            f"--- stdout ---\n{verification.stdout}\n"
            f"--- stderr ---\n{verification.stderr}\n"
        )

    @staticmethod
    def _report(
        request: RunRequest,
        result: RunResult,
        command_names: dict[int, str],
    ) -> str:
        lines = [
            "# RepoPilot Run Report",
            "",
            f"- Run ID: `{result.run_id}`",
            f"- Status: `{result.termination_reason.value}`",
            f"- Final phase: `{result.phase.value}`",
            f"- Elapsed: {result.counters.elapsed_ms} ms",
            f"- Model calls: {result.counters.model_calls}",
            f"- Tool calls: {result.counters.tool_calls}",
            f"- Edit iterations: {result.counters.iterations}",
            "",
            "## Task",
            "",
            *_indented(request.task),
        ]
        if result.failure_message is not None:
            lines.extend(["", "## Failure", "", *_indented(result.failure_message)])
        if result.plan is not None:
            lines.extend(["", "## Plan", "", result.plan.summary, ""])
            for step in result.plan.steps:
                lines.append(f"- `{step.id}`: {step.objective}")
        lines.extend(["", "## Verification", ""])
        if not result.verifications:
            lines.append("No verification result was captured.")
        for index, verification in enumerate(result.verifications, start=1):
            command = (
                json.dumps(verification.argv, ensure_ascii=False)
                if verification.argv
                else "repository diff"
            )
            detail = f"; log: `commands/{command_names[index]}`" if index in command_names else ""
            lines.append(
                f"- `{verification.status.value}` {verification.check_kind.value}: "
                f"{command} — {verification.message}{detail}"
            )
        lines.extend(["", "## Model Usage", ""])
        if result.usage is None:
            lines.append("Provider usage was unavailable.")
        else:
            lines.extend(
                [
                    f"- Input tokens: {result.usage.input_tokens}",
                    f"- Cached input tokens: {result.usage.cached_input_tokens}",
                    f"- Output tokens: {result.usage.output_tokens}",
                    f"- Reasoning tokens: {result.usage.reasoning_tokens}",
                    f"- Total tokens: {result.usage.total_tokens}",
                ]
            )
        lines.extend(["", "## Context Selection", ""])
        if not result.context_metrics:
            lines.append("No model context was assembled.")
        else:
            original = sum(metric.original_chars for metric in result.context_metrics)
            selected = sum(metric.selected_chars for metric in result.context_metrics)
            change = 0 if original == 0 else round((1 - selected / original) * 100)
            change_label = (
                f"Character reduction: {change}%"
                if change >= 0
                else f"Character increase: {-change}%"
            )
            lines.extend(
                [
                    f"- Original input characters: {original}",
                    f"- Selected input characters: {selected}",
                    f"- {change_label}",
                    "- Compacted items: "
                    f"{sum(metric.compacted_items for metric in result.context_metrics)}",
                ]
            )
            for metric in result.context_metrics:
                lines.append(
                    f"- `{metric.operation}`: {metric.original_chars} → "
                    f"{metric.selected_chars} characters"
                )
        if result.reflections:
            lines.extend(["", "## Reflections", ""])
            for reflection in result.reflections:
                lines.append(f"- {reflection.diagnosis} Next: {reflection.next_step}")
        lines.extend(
            [
                "",
                "## Artifacts",
                "",
                "- `report.md`",
                "- `patch.diff`",
                "- `events.jsonl`",
                "- `commands/`",
                "",
            ]
        )
        return "\n".join(lines)


def _indented(value: str) -> list[str]:
    return [f"    {line}" for line in value.splitlines()] or ["    "]

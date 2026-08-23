"""Exhaustive dispatch from validated model calls to safe tools."""

from __future__ import annotations

from typing import assert_never

from repopilot.model_models import (
    GitDiffCall,
    ListFilesCall,
    ModelToolCall,
    ReadFileCall,
    RunCommandCall,
    SearchTextCall,
    WritePatchCall,
)
from repopilot.models import RepositoryCheckout
from repopilot.repository import RepositoryService
from repopilot.tool_models import (
    GitDiffData,
    GitDiffRequest,
    ListFilesData,
    ReadFileData,
    RunCommandData,
    RunCommandRequest,
    SearchTextData,
    ToolResult,
    WritePatchData,
)
from repopilot.tools.filesystem import FilesystemTools
from repopilot.tools.git import GitTools
from repopilot.tools.patch import PatchTool
from repopilot.tools.shell import CommandBackend, CommandPolicy, CommandTool

type AnyToolResult = (
    ToolResult[ListFilesData]
    | ToolResult[SearchTextData]
    | ToolResult[ReadFileData]
    | ToolResult[WritePatchData]
    | ToolResult[RunCommandData]
    | ToolResult[GitDiffData]
)


class ToolExecutor:
    """Route each validated call without string-based dynamic dispatch."""

    def __init__(
        self,
        checkout: RepositoryCheckout,
        repository: RepositoryService,
        command_policy: CommandPolicy | None = None,
        command_backend: CommandBackend | None = None,
    ) -> None:
        self._filesystem = FilesystemTools(checkout, repository)
        self._patch = PatchTool(checkout)
        self._command = CommandTool(checkout, command_policy, backend=command_backend)
        self._git = GitTools(checkout, repository)

    def execute(self, call: ModelToolCall) -> AnyToolResult:
        if isinstance(call, ListFilesCall):
            return self._filesystem.list_files(call.arguments)
        if isinstance(call, SearchTextCall):
            return self._filesystem.search_text(call.arguments)
        if isinstance(call, ReadFileCall):
            return self._filesystem.read_file(call.arguments)
        if isinstance(call, WritePatchCall):
            return self._patch.apply(call.arguments)
        if isinstance(call, RunCommandCall):
            return self._command.run(call.arguments)
        if isinstance(call, GitDiffCall):
            return self._git.diff(call.arguments)
        assert_never(call)

    def run_command(self, request: RunCommandRequest) -> ToolResult[RunCommandData]:
        return self._command.run(request)

    def diff(self, request: GitDiffRequest) -> ToolResult[GitDiffData]:
        return self._git.diff(request)

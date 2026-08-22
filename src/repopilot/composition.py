"""Production dependency composition for RepoPilot runs."""

from openai import OpenAI

from repopilot.application import PersistingRunApplication
from repopilot.artifacts import FilesystemArtifactWriter
from repopilot.config import RuntimeConfig
from repopilot.controller import RunController
from repopilot.openai_model import OpenAIResponsesModel
from repopilot.repository import RepositoryService
from repopilot.workspace import WorkspaceManager


def build_controller(config: RuntimeConfig) -> RunController:
    """Compose the controller with production repository and provider adapters."""
    client = OpenAI(api_key=config.api_key.get_secret_value())
    model = OpenAIResponsesModel(client, config.model)
    return RunController(
        WorkspaceManager(config.run_root),
        RepositoryService(),
        model,
    )


def build_application(config: RuntimeConfig) -> PersistingRunApplication:
    """Compose production execution with durable artifact persistence."""
    return PersistingRunApplication(
        build_controller(config),
        FilesystemArtifactWriter(
            config.run_root,
            redactions=(config.api_key.get_secret_value(),),
        ),
    )

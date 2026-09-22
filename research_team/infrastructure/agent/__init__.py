"""Agent adapters: deepagents, langchain, and the model endpoint."""

from research_team.infrastructure.agent.activity_stream import (
    MAIN_AGENT_NODE,
    describe_activity,
    to_activity_delta,
    to_activity_message,
)
from research_team.infrastructure.agent.backend import EventSourcedBackend
from research_team.infrastructure.agent.deep_agent import DeepAgentTurnExecutor
from research_team.infrastructure.agent.model_providers import (
    build_embedding_provider,
    build_extraction_model,
    build_model,
)

__all__ = [
    "MAIN_AGENT_NODE",
    "DeepAgentTurnExecutor",
    "EventSourcedBackend",
    "build_embedding_provider",
    "build_extraction_model",
    "build_model",
    "describe_activity",
    "to_activity_delta",
    "to_activity_message",
]

"""Agent adapters: deepagents, langchain, and the model endpoint."""

from research_team.infrastructure.agent.backend import EventSourcedBackend
from research_team.infrastructure.agent.deep_agent import (
    DeepAgentTurnExecutor,
    build_model,
    describe_activity,
)

__all__ = [
    "DeepAgentTurnExecutor",
    "EventSourcedBackend",
    "build_model",
    "describe_activity",
]

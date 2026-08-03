"""The composition root: the one place that picks concrete adapters.

Every other module receives what it needs. This module is where SQLite,
deepagents, and the environment are chosen and wired to the ports -- so
swapping any of them is an edit here and nowhere else.
"""

from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel

from research_team.application import DEFAULT_SYSTEM_PROMPT, LiveFeed, SessionService
from research_team.infrastructure import config
from research_team.infrastructure.agent import DeepAgentTurnExecutor, build_model
from research_team.infrastructure.persistence import EventStoreSessionRepository


@dataclass(frozen=True)
class Application:
    """The wired application: use cases, plus a live view of the same log."""

    service: SessionService
    feed: LiveFeed

    async def close(self) -> None:
        await self.service.close()


def build_application(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
) -> Application:
    """Wire everything over one event store.

    Creates no session: which session a caller is working on is the caller's
    business, and one application serves as many of them as ask.

    The repository backs both ports -- it is one connection to one log, read
    two ways -- so the service and the feed are always looking at the same
    events, with no chance of a live view lagging a different database.
    """
    resolved_path = db_path if db_path is not None else config.default_db_path()
    repository = EventStoreSessionRepository.open(resolved_path)
    executor = DeepAgentTurnExecutor(model if model is not None else build_model())
    return Application(
        service=SessionService(
            repository, executor, default_system_prompt=system_prompt
        ),
        feed=LiveFeed(repository),
    )


def build_service(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
) -> SessionService:
    """Just the use cases, for callers with no use for a live feed."""
    return build_application(
        model=model, system_prompt=system_prompt, db_path=db_path
    ).service

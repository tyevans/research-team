"""The composition root: the one place that picks concrete adapters.

Every other module receives what it needs. This module is where SQLite,
deepagents, and the environment are chosen and wired to the ports -- so
swapping any of them is an edit here and nowhere else.
"""

from uuid import UUID

from langchain_core.language_models import BaseChatModel

from research_team.application import DEFAULT_SYSTEM_PROMPT, SessionService, create_session
from research_team.infrastructure import config
from research_team.infrastructure.agent import DeepAgentTurnExecutor, build_model
from research_team.infrastructure.persistence import EventStoreSessionRepository


async def build_service(
    *,
    model: BaseChatModel | None = None,
    system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    db_path: str | None = None,
    session_id: UUID | None = None,
) -> SessionService:
    """Open a session service. Passing `session_id` resumes an existing session.

    Resuming appends no `SessionStarted` event and keeps the stored system
    prompt, so the resumed stream stays a faithful continuation rather than a
    session with two beginnings.
    """
    resolved_path = db_path if db_path is not None else config.default_db_path()
    repository = EventStoreSessionRepository.open(resolved_path)
    executor = DeepAgentTurnExecutor(model if model is not None else build_model())

    if session_id is not None:
        aggregate = await repository.load(session_id)
        return SessionService(
            repository,
            executor,
            session_id=session_id,
            system_prompt=aggregate.state.system_prompt or system_prompt,
        )

    new_id = await create_session(
        repository, system_prompt=system_prompt, model_name=executor.model_name
    )
    return SessionService(
        repository, executor, session_id=new_id, system_prompt=system_prompt
    )

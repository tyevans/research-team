"""The use cases: everything you can do to a coding session.

This layer orchestrates. It owns transaction boundaries (a turn is all-or-
nothing) and the ordering rules between commands, but no domain invariants
(those live on the aggregate) and no I/O details (those live behind the ports).

Every operation names the session it acts on. The service holds no "current
session": that is a property of whoever is driving -- one terminal has exactly
one, and a web server has one per request -- so it belongs to the caller.
"""

import logging
from collections.abc import Mapping
from typing import Any
from uuid import UUID, uuid4

from eventsource import DomainEvent, OptimisticLockError
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.observability import Tracer, create_tracer

from research_team.curriculum.application.learner_progress import (
    LearnerProgressService,
    LearnerProgressState,
)
from research_team.curriculum.domain import LearnerProgress
from research_team.knowledge.application.knowledge_attachment import (
    KnowledgeAttachment,
)
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.platform.shared.context import ContextStrategy, FullHistory
from research_team.session.application.ports import (
    ActivityReporter,
    SessionRepository,
    SessionSummaries,
    SummaryHealth,
    TurnExecutor,
)
from research_team.session.application.session_inspection import (
    SessionQueries,
    SessionStats,
)
from research_team.session.application.summaries import SessionSummary
from research_team.session.application.turn_runner import (
    _FILE_EVENT_TYPES,
    _INHERITED_EVENT_FIELDS,
    FILE_EVENT_TYPES,
    INHERITED_EVENT_FIELDS,
    TurnOutcome,
    TurnRunner,
    fork_session,
    project_context,
)
from research_team.session.domain import (
    ChangeAutonomy,
    Session,
    SessionPurpose,
    WriteFile,
)
from research_team.tenancy.application.project_sessions import (
    ProjectSessions,
    catch_up_project_tip,
    delete_project_aggregate,
    ensure_session_project_attached,
    fork_session_files,
    release_session_project,
    resolve_project_files,
)
from research_team.tenancy.application.project_sessions import (
    start_session_in_project as _tenancy_start_session_in_project,
)
from research_team.tenancy.domain import (
    Project,
    ProjectState,
)

__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "FILE_EVENT_TYPES",
    "INHERITED_EVENT_FIELDS",
    "NO_SEARCH_CLAUSE",
    "_FILE_EVENT_TYPES",
    "_INHERITED_EVENT_FIELDS",
    "ProjectSessions",
    "SessionQueries",
    "SessionService",
    "SessionStats",
    "TurnOutcome",
    "TurnRunner",
    "catch_up_project_tip",
    "delete_project_aggregate",
    "ensure_session_project_attached",
    "fork_session",
    "fork_session_files",
    "project_context",
    "release_session_project",
    "resolve_project_files",
    "start_session_in_project",
]

logger = logging.getLogger(__name__)


async def start_session_in_project(
    projects: AggregateRepository[Project],
    repository: SessionRepository,
    project_id: UUID,
    purpose: SessionPurpose,
    *,
    default_system_prompt: str = "",
    knowledge_prompt: str = "",
    model_name: str = "",
    session_id: UUID | None = None,
) -> UUID:
    """Start a session in a project, generating a session ID if not provided."""
    return await _tenancy_start_session_in_project(
        projects,
        repository,
        project_id,
        purpose,
        default_system_prompt=default_system_prompt,
        knowledge_prompt=knowledge_prompt,
        model_name=model_name,
        session_id=session_id if session_id is not None else uuid4(),
    )


DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent working in an in-memory filesystem. "
    "Use the provided file tools to read and write code. "
    "There is no shell."
)
"""Framework-free by construction: which network tools exist is a
composition-root decision. Saying anything about them unconditionally would
tell the model a lie on some installs, and a model told it has no network will
not use a tool it was just given."""

NO_SEARCH_CLAUSE = " You cannot search the web, though you can read a page you have a URL for."
"""What composition appends when no SearXNG instance is configured.

Says what is missing rather than "there is no network", which stopped being
true when `fetch` became unconditional. The distinction matters to the model:
without search it cannot *find* a page, but it can still read one a person
pastes into the conversation, and a model told it is offline will not try."""


class SessionService:
    """The application's whole surface, over one event store."""

    def __init__(
        self,
        repository: SessionRepository,
        executor: TurnExecutor,
        summaries: SessionSummaries,
        projects: AggregateRepository[Project],
        *,
        default_system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        context: ContextStrategy | None = None,
        tracer: Tracer | None = None,
        knowledge_prompt: str = "",
        attachment: KnowledgeAttachment | None = None,
        progress: (
            "AggregateRepository[LearnerProgress] | LearnerProgressService | None"
        ) = None,
        graphs: ProjectGraphs | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._summaries = summaries
        self._projects = projects
        if isinstance(progress, LearnerProgressService):
            self._learner_progress = progress
        else:
            self._learner_progress = LearnerProgressService(progress)
        self._tracer = tracer if tracer is not None else create_tracer(__name__, False)
        self._default_system_prompt = default_system_prompt
        self._context = context if context is not None else FullHistory()
        self._knowledge_prompt = knowledge_prompt
        self._attachment = attachment
        self._graphs = graphs
        self._queries = SessionQueries(repository=repository, summaries=summaries)
        self._project_sessions = ProjectSessions(
            repository=repository,
            projects=projects,
            default_system_prompt=default_system_prompt,
            knowledge_prompt=knowledge_prompt,
            executor=executor,
            attachment=attachment,
            graphs=graphs,
        )
        self._turn_runner = TurnRunner(
            repository=repository,
            executor=executor,
            default_system_prompt=default_system_prompt,
            context=self._context,
            tracer=self._tracer,
        )

    @property
    def tracer(self) -> Tracer:
        """The tracer spans are opened on. No-op unless one was supplied."""
        return self._tracer

    @property
    def context_strategy(self) -> str:
        """Which context strategy this instance runs under."""
        return self._context.name

    @property
    def tools(self) -> tuple[Any, ...]:
        """The tools available to the session executor."""
        return self._executor.tools

    @property
    def _progress(self) -> "AggregateRepository[LearnerProgress] | None":
        return self._learner_progress.repository

    @property
    def learner_progress_service(self) -> LearnerProgressService:
        """The learner progress application service."""
        return self._learner_progress

    @property
    def projects(self) -> AggregateRepository[Project]:
        """The `Project` aggregate repository, for callers that need it directly."""
        return self._projects

    # ---------------- learner progress ----------------

    async def learner_progress(self, session_id: UUID) -> LearnerProgressState:
        """What this learner has done with this course's components."""
        return await self._learner_progress.get_progress(session_id)

    async def record_attempt(
        self,
        session_id: UUID,
        *,
        path: str,
        component_id: str,
        component_type: str,
        digest: str,
        response: Any = None,
        correct: bool = False,
        score: float = 0.0,
        at: int | None = None,
    ) -> LearnerProgressState:
        """Record that an item was answered, and how it was marked."""
        return await self._learner_progress.record_attempt(
            session_id,
            path=path,
            component_id=component_id,
            component_type=component_type,
            digest=digest,
            response=response,
            correct=correct,
            score=score,
            at=at,
        )

    async def record_checklist(
        self, session_id: UUID, *, path: str, component_id: str, checked: list[int]
    ) -> LearnerProgressState:
        """Remember which boxes are ticked on a `persist: true` checklist."""
        return await self._learner_progress.record_checklist(
            session_id,
            path=path,
            component_id=component_id,
            checked=checked,
        )

    # ---------------- projects ----------------

    async def list_projects(self) -> list[tuple[UUID, str]]:
        """Every project's id and name, for `/project`'s listing."""
        return await self._project_sessions.list_projects()

    async def project_state(self, project_id: UUID) -> ProjectState:
        """One project's folded state: who holds it, and where its tip is."""
        return await self._project_sessions.project_state(project_id)

    async def project_files(self, project_id: UUID) -> dict[str, dict[str, Any]]:
        """The project's filesystem, from whichever stream currently carries it."""
        return await self._project_sessions.project_files(project_id)

    async def delete_project(self, project_id: UUID) -> None:
        """Retire a project: no more joins, and gone from every listing."""
        await self._project_sessions.delete_project(project_id)

    async def close(self) -> None:
        await self._repository.close()

    # ---------------- reads & queries ----------------

    async def load(self, session_id: UUID) -> Session:
        """One session's aggregate, folded from its events."""
        return await self._queries.load(session_id)

    async def history(self, session_id: UUID) -> list[DomainEvent]:
        """Every event on one session's stream, in order."""
        return await self._queries.history(session_id)

    async def state_at(self, session_id: UUID, at: int) -> Session:
        """The session as it stood after its first `at` events."""
        return await self._queries.state_at(session_id, at)

    async def list_sessions(self) -> list[SessionSummary]:
        """Every session in the store, newest first."""
        return await self._queries.list_sessions()

    async def summaries_health(self) -> SummaryHealth:
        """Whether `list_sessions` can currently be trusted."""
        return await self._queries.summaries_health()

    async def rebuild_summaries(self) -> None:
        """Derive the session list from the log again. Safe at any time."""
        await self._queries.rebuild_summaries()

    async def session_stats(self, session_id: UUID) -> SessionStats:
        """High-level summary metrics for a session."""
        return await self._queries.session_stats(session_id)

    async def find_messages(
        self,
        session_id: UUID,
        *,
        role: str | None = None,
        query: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Search and filter messages recorded in a session."""
        return await self._queries.find_messages(
            session_id, role=role, query=query, limit=limit
        )

    async def diff_session_files(
        self, session_id: UUID, other_session_id: UUID
    ) -> dict[str, Any]:
        """Diff files between two sessions."""
        return await self._queries.diff_session_files(session_id, other_session_id)

    # ---------------- lifecycle & project binding ----------------

    async def start_in_project(
        self,
        project_id: UUID,
        purpose: SessionPurpose,
        *,
        session_id: UUID | None = None,
    ) -> UUID:
        """Begin a session that shares the project's filesystem."""
        return await self._project_sessions.start_in_project(
            project_id,
            purpose,
            session_id=session_id if session_id is not None else uuid4(),
        )

    async def _catch_up_tip(self, project: Any) -> None:
        """Move the tip to the end of the stream it already names."""
        await self._project_sessions.catch_up_tip(project)

    async def _fork_files_from(
        self,
        session_id: UUID,
        *,
        source_session_id: UUID,
        at_event: int,
        project_id: UUID,
        purpose: SessionPurpose,
        project_name: str = "",
    ) -> None:
        """Start `session_id`, carrying only the source's file history in."""
        await self._project_sessions.fork_files_from(
            session_id,
            source_session_id=source_session_id,
            at_event=at_event,
            project_id=project_id,
            purpose=purpose,
            project_name=project_name,
        )

    async def release_project(self, session_id: UUID) -> None:
        """Hand the project's filesystem tip back, if this session holds it."""
        await self._project_sessions.release_project(session_id)

    async def record_autonomy_change(
        self, session_id: UUID, tool_name: str, level: str
    ) -> None:
        """Note in the log that a tool's autonomy level was changed."""
        await self.record_autonomy_changes(session_id, {tool_name: level})

    async def record_autonomy_changes(
        self, session_id: UUID, levels: Mapping[str, str]
    ) -> None:
        """Note several tools' autonomy levels in one append."""
        if not levels:
            return
        aggregate = await self._repository.load(session_id)
        for tool_name, level in levels.items():
            aggregate.execute(ChangeAutonomy(tool_name=tool_name, level=level))
        await self._repository.save(aggregate)

    async def write_file(self, session_id: UUID, path: str, content: str) -> None:
        """Put one file on a session's filesystem, outside any turn."""
        aggregate = await self._repository.load(session_id)
        aggregate.execute(WriteFile(path=path, file_data={"content": content}))
        await self._repository.save(aggregate)

    @property
    def current_knowledge(self) -> object | None:
        """Whichever project's graph is attached right now, or None."""
        return self._project_sessions.current_knowledge

    @property
    def attached_project_id(self) -> UUID | None:
        """Which project's graph is attached right now, or None."""
        return self._project_sessions.attached_project_id

    async def ensure_project_attached(self, session_id: UUID) -> bool:
        """Make `session_id`'s own project the attached one. Returns whether it is."""
        return await self._project_sessions.ensure_project_attached(session_id)

    async def attach_project(self, project_id: UUID) -> None:
        """Open `project_id`'s knowledge graph and give the executor its tools."""
        await self._project_sessions.attach_project(project_id)

    async def detach_project(self) -> None:
        """Close whatever knowledge graph is attached and restore the plain tools."""
        await self._project_sessions.detach_project()

    # ---------------- turns ----------------

    async def run_turn(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        """One user turn. All events append atomically at the end, or not at all."""
        return await self._turn_runner.run_turn(session_id, user_input, on_activity)

    async def _run_turn(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        return await self._turn_runner._run_turn(session_id, user_input, on_activity)

    async def _save_turn(self, session_id: UUID, aggregate: Session) -> Session:
        return await self._turn_runner._save_turn(session_id, aggregate)

    async def _refuse_unrebasable(
        self, session_id: UUID, base_version: int, lost: OptimisticLockError | None
    ) -> None:
        return await self._turn_runner._refuse_unrebasable(session_id, base_version, lost)

    async def _record_failure(self, session_id: UUID, error: BaseException) -> None:
        await self._turn_runner._record_failure(session_id, error)

    async def _append_failure(self, session_id: UUID, error: BaseException) -> None:
        await self._turn_runner._append_failure(session_id, error)

    # ---------------- time travel ----------------

    async def fork(
        self,
        session_id: UUID,
        at: int,
        *,
        purpose: SessionPurpose | None = None,
    ) -> UUID:
        """Replay the first `at` events onto a fresh stream. Nothing is destroyed."""
        return await fork_session(self._repository, session_id, at, purpose=purpose)

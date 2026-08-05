"""The use cases: everything you can do to a coding session.

This layer orchestrates. It owns transaction boundaries (a turn is all-or-
nothing) and the ordering rules between commands, but no domain invariants
(those live on the aggregate) and no I/O details (those live behind the ports).

Every operation names the session it acts on. The service holds no "current
session": that is a property of whoever is driving -- one terminal has exactly
one, and a web server has one per request -- so it belongs to the caller.
"""

import asyncio
import logging
from dataclasses import dataclass
from uuid import UUID, uuid4

from eventsource import DomainEvent
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.observability import Tracer, create_tracer
from eventsource.observability.attributes import (
    ATTR_AGGREGATE_ID,
    ATTR_AGGREGATE_TYPE,
)

from research_team.application.context import ContextStrategy, FullHistory
from research_team.application.knowledge_attachment import KnowledgeAttachment
from research_team.application.ports import (
    ActivityReporter,
    SessionRepository,
    SessionSummaries,
    SummaryHealth,
    TurnAccountingError,
    TurnExecutor,
)
from research_team.application.summaries import SessionSummary
from research_team.domain import (
    AdvanceTip,
    ChangeAutonomy,
    CodingSession,
    CompactConversation,
    CompleteTurn,
    FailTurn,
    FileDeleted,
    FileEdited,
    FileWritten,
    JoinProject,
    Project,
    RecordAssistantMessage,
    RecordForkSource,
    RecordToolResult,
    SendUserMessage,
    StartSession,
)

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = (
    "You are a coding agent working in an in-memory filesystem. "
    "Use the provided file tools to read and write code. "
    "There is no shell."
)
"""Framework-free by construction: whether *network* belongs on the end of
this depends on whether a search tool was actually registered, which is a
composition-root decision. Appending "and no network" unconditionally would
tell the model a lie on any install with search configured, and a model told
it has no network will not use a tool it was just given."""

NO_NETWORK_CLAUSE = " There is no network."
"""What composition appends when no search tool is registered. Kept here,
next to the prompt it modifies, rather than duplicated at the call site."""


@dataclass(frozen=True)
class TurnOutcome:
    """What one turn produced: the reply, and where it landed in the log.

    `from_index`/`to_index` are inclusive 1-based event numbers, matching the
    numbering the REPL prints and the web timeline shows.
    """

    reply: str
    turn_index: int
    from_index: int
    to_index: int

    @property
    def event_count(self) -> int:
        return self.to_index - self.from_index + 1


_INHERITED_EVENT_FIELDS = frozenset(
    {
        "event_id",
        "event_type",
        "occurred_at",
        "aggregate_id",
        "aggregate_type",
        "aggregate_version",
    }
)

_FILE_EVENT_TYPES = (FileWritten, FileEdited, FileDeleted)
"""What "inheriting a project's filesystem" copies. Deliberately narrower
than `fork()`'s replay: a project shares a workspace, not a chat history, so
`UserMessageSent` and friends never cross into the new stream."""


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
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._summaries = summaries
        self._projects = projects
        # `create_tracer` returns a no-op when OpenTelemetry is not installed,
        # which is the normal case here -- so spans cost a couple of attribute
        # lookups and are thrown away, and nothing has to be conditional.
        self._tracer = tracer if tracer is not None else create_tracer(__name__, False)
        self._default_system_prompt = default_system_prompt
        self._context = context if context is not None else FullHistory()
        # Appended only for sessions started in a project: a session with no
        # project gets no knowledge tools, so telling it about `remember` and
        # `graph_search` would describe tools it does not have.
        self._knowledge_prompt = knowledge_prompt
        # None when the composition root wired no knowledge subsystem at all
        # -- `attach_project`/`detach_project` are then no-ops, the same
        # posture `search` has without an instance configured.
        self._attachment = attachment

    @property
    def tracer(self) -> Tracer:
        """The tracer spans are opened on. No-op unless one was supplied."""
        return self._tracer

    @property
    def context_strategy(self) -> str:
        """Which context strategy this instance runs under."""
        return self._context.name

    @property
    def default_system_prompt(self) -> str:
        """The prompt new sessions are started with. Existing ones keep their own."""
        return self._default_system_prompt

    @property
    def projects(self) -> AggregateRepository[Project]:
        """The `Project` aggregate repository, for callers that need it directly.

        `/project new` has to `create_new` and `save` a `Project` -- neither
        of which is a session use case -- so it is exposed here rather than
        left for a caller to reach past this service into its own repository
        attribute (BACKLOG B8: a second private hop was the trigger for
        fixing the pattern instead of repeating it).
        """
        return self._projects

    async def list_projects(self) -> list[tuple[UUID, str]]:
        """Every project's id and name, for `/project`'s listing."""
        return await self._repository.list_projects()

    async def close(self) -> None:
        await self._repository.close()

    # ---------------- reads ----------------

    async def load(self, session_id: UUID) -> CodingSession:
        """One session's aggregate, folded from its events."""
        return await self._repository.load(session_id)

    async def history(self, session_id: UUID) -> list[DomainEvent]:
        """Every event on one session's stream, in order."""
        return await self._repository.events_for(session_id)

    async def state_at(self, session_id: UUID, at: int) -> CodingSession:
        """The session as it stood after its first `at` events.

        A pure fold of a prefix -- nothing is written, nothing is forked. This
        is what makes scrubbing a timeline cheap: the log is the state, so any
        point in it can be reconstituted just by stopping the fold early.
        """
        events = await self.history(session_id)
        if not 1 <= at <= len(events):
            raise ValueError(f"cannot fold at {at}: session has {len(events)} events")
        aggregate = self._repository.create(session_id)
        aggregate.load_from_history(events[:at])
        return aggregate

    async def list_sessions(self) -> list[SessionSummary]:
        """Every session in the store, newest first.

        Read straight out of the projection's table. What this used to do --
        fold every event in the database, per request -- is still the
        definition of a summary, and still lives in `summarize_sessions`; it is
        just applied once per event now instead of once per page view.
        """
        return await self._summaries.list()

    async def summaries_health(self) -> SummaryHealth:
        """Whether `list_sessions` can currently be trusted.

        Exposed as a use case rather than left to the composition root because
        every front end that shows the list has the same question about it,
        and the answer decides whether to show a warning next to it.
        """
        return await self._summaries.health()

    async def rebuild_summaries(self) -> None:
        """Derive the session list from the log again. Safe at any time."""
        await self._summaries.rebuild()

    # ---------------- lifecycle ----------------

    async def create_session(self, system_prompt: str | None = None) -> UUID:
        """Start a new session and return its id."""
        session_id = uuid4()
        aggregate = self._repository.create(session_id)
        aggregate.execute(
            StartSession(
                system_prompt=(
                    system_prompt if system_prompt is not None else self._default_system_prompt
                ),
                model_name=self._executor.model_name,
            )
        )
        await self._repository.save(aggregate)
        return session_id

    async def start_in_project(self, project_id: UUID) -> UUID:
        """Begin a session that shares the project's filesystem.

        Joining is decided by the `Project` aggregate, which rejects a second
        concurrent session by name. That rejection propagates: a caller
        finding out the project is busy is the point, and swallowing it here
        would let two sessions diverge silently.

        Inheritance reuses forking rather than copying. The project stores a
        pointer -- whose stream, and how far in -- so a new session forks
        from exactly that point and its filesystem still folds out of one
        stream. Only files come across; the conversation does not, because a
        project shares a workspace and not a chat history.

        The new session is created (or forked) before the project is saved as
        held by it: a project marked held by a session that was never
        created is a project nothing can take back.
        """
        project = await self._projects.load(project_id)
        session_id = uuid4()
        project.execute(JoinProject(session_id=session_id))

        state = project.state
        if state.tip_session_id is None:
            session = self._repository.create(session_id)
            session.execute(
                StartSession(
                    system_prompt=self._default_system_prompt + self._knowledge_prompt,
                    model_name=self._executor.model_name,
                    project_id=project_id,
                )
            )
            await self._repository.save(session)
        else:
            await self._fork_files_from(
                session_id,
                source_session_id=state.tip_session_id,
                at_event=state.tip_at_event,
                project_id=project_id,
            )

        await self._projects.save(project)
        return session_id

    async def _fork_files_from(
        self,
        session_id: UUID,
        *,
        source_session_id: UUID,
        at_event: int,
        project_id: UUID,
    ) -> None:
        """Start `session_id`, carrying only the source's file history in.

        Follows the same replay `fork()` uses -- copying each historical
        event's own fields onto the fresh stream with `create_event`, since
        these are already-decided facts being replayed rather than new
        decisions -- but filtered to `_FILE_EVENT_TYPES`. `SessionStarted` is
        not copied from the source: it is this session's own genuine start,
        produced through `execute` like any other, carrying *this* session's
        project_id. Lineage is recorded the same way `fork()` records it, so
        `forked_from` still answers "whose filesystem is this".
        """
        events = await self.history(source_session_id)
        if not 1 <= at_event <= len(events):
            raise ValueError(f"cannot inherit at {at_event}: source has {len(events)} events")

        session = self._repository.create(session_id)
        session.execute(
            StartSession(
                system_prompt=self._default_system_prompt + self._knowledge_prompt,
                model_name=self._executor.model_name,
                project_id=project_id,
            )
        )
        for event in events[:at_event]:
            if isinstance(event, _FILE_EVENT_TYPES):
                session.create_event(
                    type(event), **event.model_dump(exclude=set(_INHERITED_EVENT_FIELDS))
                )
        session.execute(
            RecordForkSource(source_session_id=source_session_id, at_event=at_event)
        )
        await self._repository.save(session)

    async def release_project(self, session_id: UUID) -> None:
        """Hand the project's filesystem tip back, if this session holds it.

        A no-op whenever there is nothing to release: a session with no
        `project_id`, or one whose project is no longer (or never was)
        actively held by it. That second case is ordinary, not exceptional --
        a REPL switching away from a session, or resuming an old session
        that named a project long since handed to someone else, both reach
        it -- so this stays quiet rather than raising `AdvanceTip`'s
        "you do not hold this" rejection. That is what lets every
        session-switch path call this unconditionally, and keeps the
        rejection from ever escaping a caller's exit/cleanup path.
        """
        session = await self._repository.load(session_id)
        if session.state.project_id is None:
            return
        project = await self._projects.load(session.state.project_id)
        if project.state.active_session_id != session_id:
            return
        project.execute(AdvanceTip(session_id=session_id, at_event=session.version))
        await self._projects.save(project)

    async def record_autonomy_change(
        self, session_id: UUID, tool_name: str, level: str
    ) -> None:
        """Note in the log that a tool's autonomy level was changed.

        The policy object itself is what the executor consults, and it is
        mutated by whoever owns it -- but a level that changed mid-session and
        left no trace makes the surrounding decisions unreadable afterwards.
        Recording it is a use case, so the adapters do not have to reach past
        the service for a repository to write through.
        """
        aggregate = await self._repository.load(session_id)
        aggregate.execute(ChangeAutonomy(tool_name=tool_name, level=level))
        await self._repository.save(aggregate)

    @property
    def current_knowledge(self) -> object | None:
        """Whichever project's graph is attached right now, or None.

        A read, not a use case -- callers that need to act on the graph go
        through the `KnowledgePort` behind the executor's tools, not through
        here. This exists for callers that only need to know *whether* one is
        attached (a front end showing state, a test asserting on it).
        """
        return self._attachment.current if self._attachment is not None else None

    async def attach_project(self, project_id: UUID) -> None:
        """Open `project_id`'s knowledge graph and give the executor its tools.

        A no-op when the composition root wired no knowledge subsystem --
        the same posture `search` has without an instance configured. A
        caller that wants to know whether attaching actually happened has
        `current_knowledge` for that; this does not raise on "there is
        nothing to attach to".

        Delegates to `KnowledgeAttachment` for the atomicity guarantee: if
        opening the graph fails, nothing here is left half-attached.
        """
        if self._attachment is not None:
            await self._attachment.attach(project_id)

    async def detach_project(self) -> None:
        """Close whatever knowledge graph is attached and restore the plain tools.

        Safe to call whether or not anything is attached, and whether or not
        a knowledge subsystem was wired at all -- so every caller leaving a
        project can call this unconditionally.
        """
        if self._attachment is not None:
            await self._attachment.detach()

    # ---------------- turns ----------------

    async def run_turn(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        """One user turn. All events append atomically at the end, or not at all.

        The prompt comes from the session's own `SessionStarted` event, so a
        session resumed in a differently-configured process still runs under
        the prompt it was started with.

        Reports the span of events the turn produced. A caller showing the log
        would otherwise have to diff it against a snapshot taken beforehand to
        answer "which of these did my turn write?" -- a question the aggregate
        can answer exactly, because an aggregate's version *is* its event count.

        Traced as one span. `eventsource` traces its own loads and appends, but
        those are leaves: without a parent naming the turn, a trace shows a
        pile of database calls with nothing to say which turn they served or
        how much of the wall clock was the model rather than the store. The
        span covers a failed turn too -- ending only on success would report
        every failure as a span that never closed.
        """
        with self._tracer.span(
            "research_team.turn",
            {ATTR_AGGREGATE_ID: str(session_id), ATTR_AGGREGATE_TYPE: "CodingSession"},
        ):
            return await self._run_turn(session_id, user_input, on_activity)

    async def _run_turn(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        aggregate = await self._repository.load(session_id)
        first_index = aggregate.version + 1
        aggregate.execute(
            SendUserMessage(message=self._executor.encode_user_message(user_input))
        )

        # What the model sees is decided here, before the turn, and any
        # decision that needs remembering becomes an event of its own -- so a
        # replay of this log reproduces this context, not merely this outcome.
        prepared = await self._context.prepare(aggregate.state)
        if prepared.compaction is not None:
            aggregate.execute(
                CompactConversation(
                    summary=prepared.compaction.summary,
                    through_index=prepared.compaction.through_index,
                    strategy=self._context.name,
                    tokens_before=prepared.compaction.tokens_before,
                    tokens_after=prepared.compaction.tokens_after,
                )
            )
        if on_activity is not None:
            for note in prepared.notes:
                on_activity(f"· {note}")

        try:
            result = await self._executor.execute(
                aggregate,
                messages=prepared.messages,
                system_prompt=aggregate.state.system_prompt or self._default_system_prompt,
                on_activity=on_activity,
            )
        except TurnAccountingError:
            # Not an ordinary failure: our accounting of what the agent added
            # has drifted, so even a marker would be a claim we cannot stand
            # behind. Leave the log untouched and let it surface.
            raise
        except BaseException as error:
            # The aggregate above is discarded with all of the failed turn's
            # events, so the turn stays all-or-nothing. What gets appended is a
            # single marker on a freshly loaded aggregate -- the log records
            # that an attempt happened without a half-applied turn.
            await self._record_failure(session_id, error)
            raise

        for message in result.messages:
            if message.kind == "tool":
                aggregate.execute(
                    RecordToolResult(message=message.payload, is_error=message.is_error)
                )
            else:
                aggregate.execute(RecordAssistantMessage(message=message.payload))

        aggregate.execute(CompleteTurn())
        last_index = aggregate.version
        await self._repository.save(aggregate)
        return TurnOutcome(
            reply=result.reply_text,
            turn_index=aggregate.state.turn_index,
            from_index=first_index,
            to_index=last_index,
        )

    async def _record_failure(self, session_id: UUID, error: BaseException) -> None:
        """Append a TurnFailed marker. Never masks the original error.

        Shielded, because the most common reason to be here is cancellation --
        and a cancelled coroutine's next await would be cancelled too, which
        would lose the very marker that records the attempt.
        """
        writing = asyncio.ensure_future(self._append_failure(session_id, error))
        try:
            await asyncio.shield(writing)
        except asyncio.CancelledError:
            # We are being cancelled; the write is not. Wait for it anyway, so
            # the marker is on disk before the cancellation carries on -- a
            # fire-and-forget write can be lost if the process is shutting down.
            await writing
            raise

    async def _append_failure(self, session_id: UUID, error: BaseException) -> None:
        try:
            clean = await self._repository.load(session_id)
            # Whether this was a deliberate stop is an asyncio fact, which the
            # aggregate has no business knowing -- so it is decided here.
            clean.execute(
                FailTurn.from_error(error, cancelled=isinstance(error, asyncio.CancelledError))
            )
            await self._repository.save(clean)
        except Exception:
            logger.exception("could not record TurnFailed for %s", session_id)

    # ---------------- time travel ----------------

    async def fork(self, session_id: UUID, at: int) -> UUID:
        """Replay the first `at` events onto a fresh stream. Nothing is destroyed."""
        events = await self.history(session_id)
        if not 1 <= at <= len(events):
            raise ValueError(f"cannot fork at {at}: session has {len(events)} events")

        new_id = uuid4()
        forked = self._repository.create(new_id)
        for event in events[:at]:
            forked.create_event(
                type(event), **event.model_dump(exclude=set(_INHERITED_EVENT_FIELDS))
            )
        forked.execute(RecordForkSource(source_session_id=session_id, at_event=at))
        await self._repository.save(forked)
        return new_id

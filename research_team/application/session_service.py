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
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from eventsource import DomainEvent, OptimisticLockError
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.observability import Tracer, create_tracer
from eventsource.observability.attributes import (
    ATTR_AGGREGATE_ID,
    ATTR_AGGREGATE_TYPE,
)

from research_team.application.context import ContextStrategy, FullHistory
from research_team.application.knowledge_attachment import KnowledgeAttachment
from research_team.application.ports import (
    ActivityRemark,
    ActivityReporter,
    SessionRepository,
    SessionSummaries,
    SummaryHealth,
    TurnAccountingError,
    TurnExecutor,
)
from research_team.application.project_graphs import ProjectGraphs
from research_team.application.retry import with_retry
from research_team.application.stage_exit import EvaluatedCheck
from research_team.application.summaries import SessionSummary
from research_team.domain import (
    AdvanceTip,
    AutonomyChanged,
    ChangeAutonomy,
    CompactConversation,
    CompleteTurn,
    DeleteProject,
    FailTurn,
    FileDeleted,
    FileEdited,
    FileWritten,
    JoinProject,
    LearnerProgress,
    LearnerProgressState,
    Project,
    ProjectState,
    RecordAssistantMessage,
    RecordAttempt,
    RecordChecklistState,
    RecordForkSource,
    RecordStageReview,
    RecordToolDecision,
    RecordToolResult,
    SendUserMessage,
    Session,
    SessionPurpose,
    StartSession,
    WriteFile,
)
from research_team.domain.learner import initial_state as learner_initial_state

logger = logging.getLogger(__name__)

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


def project_context(name: str) -> str:
    """What project this session is in, for a session that is in one.

    Every other project-scoped clause in this build describes a *tool* -- the
    graph, the corpus, the topic queue -- and none of them said what the
    project is about. An agent joined to a project could not name it, which is
    the second half of why a topic question like "typical physical traits"
    goes unnoticed: even an agent that wanted to disambiguate had nothing to
    disambiguate against.

    Built per session rather than folded into the static `knowledge_prompt`,
    because the name is per project and that string is one constant shared by
    every project in the process. It lands in `SessionStarted.system_prompt`
    like the rest of the prompt, so a session resumed after a project is
    renamed still runs under the name it started with -- deliberate: replaying
    a session under a prompt it never saw is the failure that field exists to
    prevent, and a stale project name is a much smaller cost than that.

    Empty string for a project created without one. `ProjectState.name`
    defaults to `""` and nothing forbids it, and "This project is called ``."
    is worse than silence -- it reads as a bug in the prompt builder rather
    than as a project nobody named.
    """
    if not name.strip():
        return ""
    return (
        f"\n\nThis session is working in a project called {name!r}. That is the "
        "subject everything here is about. It is context for you, not a "
        "substitute for saying so: anything you write down -- a topic "
        "question, a finding, a file -- is read later by someone who does not "
        "have it."
    )


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


class _TurnConflict(Exception):
    """Private: "do not retry this turn, and raise `cause` instead".

    Exists only to get a decision out of `with_retry`'s `attempt`, which
    retries every `OptimisticLockError` it sees and has no vocabulary for "this
    one is real". Never escapes `_save_turn`, which unwraps it -- callers see
    the `OptimisticLockError` they would have seen without any retrying.
    """

    def __init__(self, cause: OptimisticLockError) -> None:
        super().__init__(str(cause))
        self.cause = cause


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
        progress: "AggregateRepository[LearnerProgress] | None" = None,
        graphs: ProjectGraphs | None = None,
    ) -> None:
        self._repository = repository
        self._executor = executor
        self._summaries = summaries
        self._projects = projects
        # None for a build that wired no progress repository. Recording is then
        # a no-op and reading answers "nothing recorded", which is exactly what
        # this surface did before the aggregate existed -- so an older caller
        # keeps working rather than failing on an attribute it never passed.
        self._progress = progress
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
        # None on the same posture: a build with no graph subsystem has
        # nothing for `delete_project` to evict, so eviction is a no-op
        # rather than an attribute error on a caller that never wired one.
        self._graphs = graphs

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

    # ---------------- learner progress ----------------

    async def learner_progress(self, session_id: UUID) -> LearnerProgressState:
        """What this learner has done with this course's components.

        An empty state for a session nobody has answered anything in, which is
        the ordinary case rather than an error -- so this never raises for a
        stream that does not exist yet.
        """
        if self._progress is None:
            return learner_initial_state()
        return (await self._progress.load_or_create(session_id)).state

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
        """Record that an item was answered, and how it was marked.

        Retried on a lost compare-and-swap for the same reason the corpus is:
        a learner submitting two answers at once is rarer than a model doing
        it, but the window is the same one, and the whole operation re-runs so
        the second attempt folds onto what the winner wrote -- which matters
        here, because whether an answer *completes* an item depends on whether
        an earlier one already did.
        """
        if self._progress is None:
            return learner_initial_state()

        async def record() -> LearnerProgressState:
            aggregate = await self._progress.load_or_create(session_id)
            aggregate.execute(
                RecordAttempt(
                    progress_id=session_id,
                    path=path,
                    component_id=component_id,
                    component_type=component_type,
                    digest=digest,
                    response=response,
                    correct=correct,
                    score=score,
                    at=at,
                )
            )
            await self._progress.save(aggregate)
            return aggregate.state

        return await with_retry(record, what=f"recording an attempt at {component_id!r}")

    async def record_checklist(
        self, session_id: UUID, *, path: str, component_id: str, checked: list[int]
    ) -> LearnerProgressState:
        """Remember which boxes are ticked on a `persist: true` checklist."""
        if self._progress is None:
            return learner_initial_state()

        async def record() -> LearnerProgressState:
            aggregate = await self._progress.load_or_create(session_id)
            aggregate.execute(
                RecordChecklistState(
                    progress_id=session_id,
                    path=path,
                    component_id=component_id,
                    checked=checked,
                )
            )
            await self._progress.save(aggregate)
            return aggregate.state

        return await with_retry(record, what=f"recording checklist {component_id!r}")

    async def list_projects(self) -> list[tuple[UUID, str]]:
        """Every project's id and name, for `/project`'s listing."""
        return await self._repository.list_projects()

    async def project_state(self, project_id: UUID) -> ProjectState:
        """One project's folded state: who holds it, and where its tip is.

        A read for front ends. "Held by another session" is the single fact
        that decides what a user can do with a project next, and a UI that
        cannot see it can only offer an action and let it fail.
        """
        return (await self._projects.load(project_id)).state

    async def project_files(self, project_id: UUID) -> dict[str, dict[str, Any]]:
        """The project's filesystem, from whichever stream currently carries it.

        A project's files are never the project's own: they fold out of one
        session's stream, and which session that is changes as sessions join
        and release. Two cases, and the order matters. A session holding the
        project has work in it that the tip does not yet know about -- the tip
        only advances on release -- so the holder is the newer answer and is
        asked first.

        With nobody holding it, the tip *session* is the truth and the tip
        *offset* is not. `at_event` is where that session was when it was
        released, and releasing neither closes the session nor stops it
        accepting turns, so anything written afterwards sits past the offset
        on the very stream this is folding. Reading to the offset is what
        made a project answer with an empty file list while four artifacts
        were sitting in the stream it was pointing at. The offset earns its
        keep only once something else has forked from it, and by then the tip
        names that fork rather than this session.

        A project that has never been joined has no stream at all and answers
        with nothing, which is different from a project whose files are empty
        only in that nothing here needs to tell them apart.

        Resolved once, here, because every surface that shows a project's files
        needs the same answer -- and two of them computing it separately is two
        answers that will eventually disagree about which session was newer.
        """
        state = await self.project_state(project_id)
        if state.active_session_id is not None:
            session = await self.load(state.active_session_id)
            return dict(session.state.files)
        if state.tip_session_id is None or state.tip_at_event < 1:
            return {}
        session = await self.load(state.tip_session_id)
        return dict(session.state.files)

    async def delete_project(self, project_id: UUID) -> None:
        """Retire a project: no more joins, and gone from every listing.

        A tombstone, not an erasure -- see `ProjectDeleted`. What this does
        *not* touch is deliberate: the sessions that were in the project keep
        their streams, their files and their readable history, because those
        live on the session's own stream and were never the project's to
        delete. The knowledge graph's data is left in place too; dropping a
        tenant's contents is a destructive, unreplayable act, and nothing
        here asks for it.

        Rejects a project still held by a session. Releasing is the caller's
        move to make, because releasing advances the tip -- a write to the
        holder's session -- and deletion doing that silently would hide a
        real change behind an unrelated verb.

        Evicts the project's graph store from `graphs` after the tombstone
        commits, not before: a rejected `DeleteProject` (still held) must
        leave a live project's cached store exactly as it was, and evicting
        first would have to be undone on every rejection path this or a
        future one grows.
        """
        project = await self._projects.load(project_id)
        project.execute(DeleteProject())
        await self._projects.save(project)
        if self._graphs is not None:
            await self._graphs.close(project_id)

    async def close(self) -> None:
        await self._repository.close()

    # ---------------- reads ----------------

    async def load(self, session_id: UUID) -> Session:
        """One session's aggregate, folded from its events."""
        return await self._repository.load(session_id)

    async def history(self, session_id: UUID) -> list[DomainEvent]:
        """Every event on one session's stream, in order."""
        return await self._repository.events_for(session_id)

    async def state_at(self, session_id: UUID, at: int) -> Session:
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

    # `create_session` was here, and is deleted rather than given a
    # `project_id` parameter. A session now belongs to a project always, and
    # the way to make that true is for there to be no method that can produce
    # one without: a parameterised `create_session` would sit beside
    # `start_in_project` doing the same job less completely -- minting a
    # session that names a project without the project having agreed to it, so
    # no `JoinProject`, no holder, no inherited filesystem. Callers that
    # wanted "a session, quickly" want `start_in_project` and a project.
    async def start_in_project(self, project_id: UUID, purpose: SessionPurpose) -> UUID:
        """Begin a session that shares the project's filesystem.

        `purpose` is required and undefaulted so that every caller states what
        it is starting. Six call sites do, and the type checker is what stops a
        seventh from quietly inheriting whichever default looked harmless --
        see `SessionPurpose` for why the harmless-looking one is `CHAT` and why
        that is the bug rather than the fallback.

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

        The tip is caught up *before* joining, and that ordering is the whole
        of it: `JoinProject` stamps `inherited_at` from the tip, and the fork
        copies to the same point, so a catch-up that ran afterwards would
        leave both of them naming a point that is not where anything was
        copied from. See `_catch_up_tip` for what is being caught up and why
        there is anything to catch.
        """
        project = await self._projects.load(project_id)
        await self._catch_up_tip(project)
        session_id = uuid4()
        project.execute(JoinProject(session_id=session_id))

        state = project.state
        if state.tip_session_id is None:
            session = self._repository.create(session_id)
            session.execute(
                StartSession(
                    session_id=session_id,
                    system_prompt=self._default_system_prompt
                    + self._knowledge_prompt
                    + project_context(state.name),
                    model_name=self._executor.model_name,
                    project_id=project_id,
                    purpose=purpose,
                )
            )
            await self._repository.save(session)
        else:
            await self._fork_files_from(
                session_id,
                source_session_id=state.tip_session_id,
                at_event=state.tip_at_event,
                project_id=project_id,
                # Threaded rather than re-loaded inside the fork: this is the
                # *second and later* session of a project, so a build that
                # named the project only on the first-join branch would leave
                # every project past its first session unnamed -- and every
                # test that creates one session would pass.
                project_name=state.name,
                # Same shape of mistake as project_name above, and checked for
                # the same reason: a build that threaded `purpose` only into
                # the first-join branch would give every session past a
                # project's first the default purpose, and every test that
                # creates a single session would still pass.
                purpose=purpose,
            )

        await self._projects.save(project)
        return session_id

    async def _catch_up_tip(self, project: Any) -> None:
        """Move the tip to the end of the stream it already names.

        Releasing a project records `at_event=session.version` -- where that
        session was at that instant -- and then lets the session carry on.
        Everything it writes afterwards lands past the recorded point, on a
        stream the project is still pointing at, and detaches: the next
        session forks from the old offset and inherits a prefix of a
        filesystem rather than the filesystem.

        That is not hypothetical. It is what happened to project "Tollers" in
        the owner's database: an auto-research run started a session, stopped,
        released the project in its `after` hook, and the person kept working
        in the session the run had left them in. Four `/course` artifacts
        written afterwards were unreachable from the project the moment they
        were written, and the session that came next forked three events short
        of the first of them.

        Called on load rather than on write. Advancing the tip after every
        turn would be a second aggregate saved on the hot path of every turn
        in every project, for a pointer only two callers read; catching it up
        where those callers read it costs one append at a join and nothing at
        all when there is nothing to catch. The trade is that the tip is
        briefly behind, which no reader can observe -- `project_files` folds
        the whole stream for exactly this reason.

        A no-op unless the tip names a session, nobody holds the project, and
        that session has grown. `execute` refuses everything else anyway; this
        checks first so a join does not append a `ProjectTipAdvanced` saying
        nothing changed.
        """
        state = project.state
        if state.active_session_id is not None or state.tip_session_id is None:
            return
        at = len(await self.history(state.tip_session_id))
        if at <= state.tip_at_event:
            return
        project.execute(AdvanceTip(session_id=state.tip_session_id, at_event=at))

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
                session_id=session_id,
                system_prompt=self._default_system_prompt
                + self._knowledge_prompt
                + project_context(project_name),
                model_name=self._executor.model_name,
                project_id=project_id,
                purpose=purpose,
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
        await self.record_autonomy_changes(session_id, {tool_name: level})

    async def record_autonomy_changes(
        self, session_id: UUID, levels: Mapping[str, str]
    ) -> None:
        """Note several tools' autonomy levels in one append.

        Still one `AutonomyChanged` per tool -- the log says what a person
        decided, and "relax everything" is a decision about each tool it moved.
        What collapses is the *append*, not the events.

        The distinction is not tidiness. "Allow all" moves several tools at
        once, and recording them one at a time was one load-and-save per tool
        against the session's own stream, issued as fast as the loop could
        manage. A turn is holding a version of that stream for as long as the
        model runs, so each of those appends was a chance for the turn to lose
        its compare-and-swap; the turn now retries, but a burst of `n` appends
        is `n` chances rather than one, and the retry is bounded. Removing the
        burst is the half of the fix that stops the contention rather than
        surviving it.

        An empty map appends nothing. `AutonomyPolicy.relax_all` returns what
        actually moved, and nothing moves when everything is already relaxed --
        a save there would be a write recording no decision.
        """
        if not levels:
            return
        aggregate = await self._repository.load(session_id)
        for tool_name, level in levels.items():
            aggregate.execute(ChangeAutonomy(tool_name=tool_name, level=level))
        await self._repository.save(aggregate)

    async def write_file(self, session_id: UUID, path: str, content: str) -> None:
        """Put one file on a session's filesystem, outside any turn.

        The agent's own `write_file` goes through the executor's tools and lands
        on the aggregate a turn is holding. This is for the caller that has no
        turn: a stage runner writing the `check-findings` report between turns,
        which must be in the store before the gate is posed rather than
        whenever the next turn happens to commit.

        Deliberately narrow. This is not a general filesystem API for the
        application layer -- a caller writing a *stage's artifact* this way
        would be producing course content with no model, no stage prompt and no
        record of a turn behind it, which is the provenance failure the whole
        workflow engine exists to prevent.
        """
        aggregate = await self._repository.load(session_id)
        aggregate.execute(WriteFile(path=path, file_data={"content": content}))
        await self._repository.save(aggregate)

    async def record_tool_decision(
        self,
        session_id: UUID,
        tool_name: str,
        args: dict[str, Any],
        decision: str,
        decided_by: str,
        review_id: UUID | None = None,
    ) -> None:
        """Note in the log that a gated call was allowed, refused, or amended.

        The turn executor records this on the aggregate it is already holding,
        mid-turn, and needs no use case for it. A caller deciding
        something *between* turns holds no aggregate, and this is the seam for
        it -- a stage runner posing an advance through `ApprovalPort` is the
        only one today.

        Appends immediately rather than deferring to a turn, because there is
        no turn to defer to: the decision is made and acted on before the next
        one starts, and a decision that reached the store only if some later
        turn succeeded would be missing from exactly the runs that went wrong.

        `review_id` names the stage review this decision answered, when it
        answered one. None for every gated call that is not an advance.
        """
        aggregate = await self._repository.load(session_id)
        aggregate.execute(
            RecordToolDecision(
                tool_name=tool_name,
                args=args,
                decision=decision,
                decided_by=decided_by,
                review_id=review_id,
            )
        )
        await self._repository.save(aggregate)

    async def record_stage_review(
        self,
        session_id: UUID,
        review_id: UUID,
        project_id: UUID,
        stage: str,
        preset: str,
        preset_version: str,
        evaluated: tuple[EvaluatedCheck, ...],
        unimplemented: tuple[EvaluatedCheck, ...],
        posed_by: str,
    ) -> None:
        """Note what the checks were asked at a gate, and what they answered.

        Appends immediately, for `record_tool_decision`'s reason and one of its
        own: the decision that answers this review is appended separately a
        moment later, and the gap between the two `occurred_at` values is the
        only measurement of how long a reviewer took. Deferring either to a
        turn would collapse that gap into a commit boundary.

        Takes `EvaluatedCheck`s and flattens them to dicts here rather than
        making the caller do it, so that the event's payload shape is decided
        in one place; `domain` cannot name `EvaluatedCheck`, which is why the
        event carries dicts at all.
        """
        aggregate = await self._repository.load(session_id)
        aggregate.execute(
            RecordStageReview(
                review_id=review_id,
                project_id=project_id,
                stage=stage,
                preset=preset,
                preset_version=preset_version,
                evaluated=[
                    {
                        "check": entry.check,
                        "severity": entry.severity,
                        "findings": entry.findings,
                    }
                    for entry in evaluated
                ],
                unimplemented=[
                    {"check": entry.check, "severity": entry.severity}
                    for entry in unimplemented
                ],
                posed_by=posed_by,
            )
        )
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

    @property
    def attached_project_id(self) -> UUID | None:
        """Which project's graph is attached right now, or None."""
        return self._attachment.attached_project_id if self._attachment is not None else None

    async def ensure_project_attached(self, session_id: UUID) -> bool:
        """Make `session_id`'s own project the attached one. Returns whether it is.

        A session's recorded `SessionStarted` prompt describes
        `remember`/`graph_search`/`unmerge` whenever it belongs to a project,
        so the executor has to have those tools every time that session takes
        a turn -- not only on the one request that happened to join. The REPL
        gets this from `switch_session`, which detaches and re-attaches on
        every switch; a front end with no single "current session" has no
        such moment, and needs to ask per turn instead.

        Attaching is skipped when the right graph is already attached, so the
        common case costs a comparison rather than reopening a graph. Returns
        False for a session in no project, and for a project whose graph would
        not open -- the caller decides whether that is worth reporting, since
        a turn without knowledge tools is degraded but not broken.
        """
        session = await self._repository.load(session_id)
        project_id = session.state.project_id
        if project_id is None:
            return False
        if self.attached_project_id == project_id:
            return True
        await self.attach_project(project_id)
        return self.attached_project_id == project_id

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
            {ATTR_AGGREGATE_ID: str(session_id), ATTR_AGGREGATE_TYPE: "Session"},
        ):
            return await self._run_turn(session_id, user_input, on_activity)

    async def _run_turn(
        self,
        session_id: UUID,
        user_input: str,
        on_activity: ActivityReporter | None = None,
    ) -> TurnOutcome:
        aggregate = await self._repository.load(session_id)
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
                on_activity(ActivityRemark(text=note))

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
        appended = len(aggregate.uncommitted_events)
        saved = await self._save_turn(session_id, aggregate)
        return TurnOutcome(
            reply=result.reply_text,
            turn_index=saved.state.turn_index,
            # Read off the saved aggregate, not off the one the turn built: a
            # retry renumbers the turn's events onto whatever version the
            # winner left, so the indices computed before the save can be
            # wrong by however much landed underneath it.
            from_index=saved.version - appended + 1,
            to_index=saved.version,
        )

    async def _save_turn(self, session_id: UUID, aggregate: Session) -> Session:
        """Append the turn's events, re-appending them if the save loses.

        A turn holds a version for as long as the model runs, which can be
        minutes, so anything else appending to the session -- an autonomy
        switch flipped from the UI is the one that did it in production --
        makes the save fail and throws the whole turn away. That is the worst
        possible thing to discard: it has already been paid for.

        **Only the append repeats.** `with_retry`'s contract is that `attempt`
        reloads and re-*decides*, which is right for a short write and wrong
        here: re-deciding means re-running the model, so a retry would bill a
        second turn and could repeat every tool call the first one made --
        writing a file twice to avoid a lock error is not a trade worth making.
        So the retry re-applies the events the turn already produced onto a
        freshly loaded aggregate instead. `with_retry` is still what counts and
        bounds the attempts; the deviation is in what `attempt` does, and it is
        safe for the same reason a rebase is: none of the turn's events decide
        anything against the state the interloper changed. `AutonomyChanged`
        moves a policy the *executor* consulted while the turn ran, and the
        turn's own events are records of what already happened.

        The bound is `with_retry`'s. What it costs is that a session under
        genuinely continuous write pressure loses the turn with the lock error
        it would have raised anyway -- but that is a stream nobody could take a
        turn on, and an unbounded retry there is a hang instead of an error.
        """
        events = list(aggregate.uncommitted_events)
        base_version = aggregate.version - len(events)
        pending: Session | None = aggregate
        lost: OptimisticLockError | None = None

        async def attempt() -> Session:
            # The first attempt saves the aggregate the turn ran on; every
            # later one rebuilds it, because an aggregate that lost a save
            # still holds the version it lost at and would lose again.
            nonlocal pending, lost
            target = pending
            pending = None
            if target is None:
                await self._refuse_unrebasable(session_id, base_version, lost)
                target = await self._repository.load(session_id)
                for event in events:
                    target.apply_event(
                        event.model_copy(
                            update={"aggregate_version": target.get_next_version()}
                        ),
                        is_new=True,
                    )
            try:
                await self._repository.save(target)
            except OptimisticLockError as error:
                lost = error
                raise
            return target

        try:
            return await with_retry(attempt, what=f"the turn on session {session_id}")
        except _TurnConflict as conflict:
            # The lock error itself, unwrapped: a caller mapping it to a 409
            # should not have to learn that something tried to rebase first.
            raise conflict.cause from None

    async def _refuse_unrebasable(
        self, session_id: UUID, base_version: int, lost: OptimisticLockError | None
    ) -> None:
        """Give up rather than rebase over a write the turn contradicts.

        The danger in retrying a turn is that a lock error means two different
        things. An autonomy switch flipped mid-turn is bookkeeping that
        happened *beside* the turn, and re-appending over it loses nothing. A
        second turn on the same session is the opposite: both turns read the
        same conversation and answered it independently, so appending both
        interleaves two replies to one message -- the all-or-nothing breakage
        the compare-and-swap exists to prevent, laundered into a success.
        `test_two_turns_at_once_on_one_session_conflict_rather_than_interleave`
        is what fails if this check goes.

        So the allowance is a named list of one, rather than "anything that is
        not a turn". The cost is that a new benign concurrent writer will make
        turns fail until someone adds it here -- which is the direction to be
        wrong in: a spurious 409 is visible and recoverable, a silently
        interleaved conversation is neither.
        """
        landed = (await self.history(session_id))[base_version:]
        if all(isinstance(event, AutonomyChanged) for event in landed):
            return
        assert lost is not None, "only reached after a save has lost its version"
        raise _TurnConflict(lost)

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

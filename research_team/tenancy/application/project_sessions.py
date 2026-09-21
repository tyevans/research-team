"""Project session and lifecycle logic.

Extracts joining, file inheritance, tip catch-up, and attachment.
"""

from typing import Any
from uuid import UUID, uuid4

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.knowledge.application.knowledge_attachment import (
    KnowledgeAttachment,
)
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.platform.shared.ports import SessionRepository, TurnExecutor
from research_team.session.application.turn_runner import (
    _FILE_EVENT_TYPES,
    _INHERITED_EVENT_FIELDS,
    project_context,
)
from research_team.session.domain import (
    RecordForkSource,
    SessionPurpose,
    StartSession,
)
from research_team.tenancy.domain import (
    AdvanceTip,
    DeleteProject,
    JoinProject,
    Project,
    ProjectState,
)

__all__ = [
    "ProjectSessions",
    "catch_up_project_tip",
    "delete_project_aggregate",
    "ensure_session_project_attached",
    "fork_session_files",
    "release_session_project",
    "resolve_project_files",
    "start_session_in_project",
]


async def resolve_project_files(
    projects: AggregateRepository[Project],
    repository: SessionRepository,
    project_id: UUID,
) -> dict[str, dict[str, Any]]:
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

    They did. `presenters.topic_documents_view` grew a second resolution
    that sent `tip_at_event` as the scrub point beside the list this
    builds, so one response listed a file written after a release and then
    handed the reader routes a point at which it does not exist. Settled
    on 2026-08-27 in favour of this one, and the criterion was
    `_catch_up_tip` rather than an argument: that method exists to drag a
    stale tip up to `len(history)`, which is HEAD, so an offset below HEAD
    is never a statement about what the project has. Measured against a
    `local_copy` of `~/.research-team/sessions.db` -- every live project
    there had `tip_at_event` exactly equal to its tip session's stream
    length, so the real data could not separate the two, and the
    divergence had to be reproduced synthetically. See that function's
    docstring for the paths.
    """
    state = (await projects.load(project_id)).state
    if state.active_session_id is not None:
        session = await repository.load(state.active_session_id)
        return dict(session.state.files)
    if state.tip_session_id is None or state.tip_at_event < 1:
        return {}
    session = await repository.load(state.tip_session_id)
    return dict(session.state.files)


async def delete_project_aggregate(
    projects: AggregateRepository[Project],
    project_id: UUID,
    *,
    graphs: ProjectGraphs | None = None,
) -> None:
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
    project = await projects.load(project_id)
    project.execute(DeleteProject())
    await projects.save(project)
    if graphs is not None:
        await graphs.close(project_id)


async def catch_up_project_tip(project: Any, repository: SessionRepository) -> None:
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
    at = len(await repository.events_for(state.tip_session_id))
    if at <= state.tip_at_event:
        return
    project.execute(AdvanceTip(session_id=state.tip_session_id, at_event=at))


async def fork_session_files(
    repository: SessionRepository,
    session_id: UUID,
    *,
    source_session_id: UUID,
    at_event: int,
    project_id: UUID,
    purpose: SessionPurpose,
    system_prompt: str,
    model_name: str,
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
    events = await repository.events_for(source_session_id)
    if not 1 <= at_event <= len(events):
        raise ValueError(f"cannot inherit at {at_event}: source has {len(events)} events")

    session = repository.create(session_id)
    session.execute(
        StartSession(
            session_id=session_id,
            system_prompt=system_prompt + project_context(project_name),
            model_name=model_name,
            project_id=project_id,
            purpose=purpose,
        )
    )
    for event in events[:at_event]:
        if isinstance(event, _FILE_EVENT_TYPES):
            session.create_event(
                type(event), **event.model_dump(exclude=set(_INHERITED_EVENT_FIELDS))
            )
    session.execute(RecordForkSource(source_session_id=source_session_id, at_event=at_event))
    await repository.save(session)


async def start_session_in_project(
    projects: AggregateRepository[Project],
    repository: SessionRepository,
    project_id: UUID,
    purpose: SessionPurpose,
    *,
    default_system_prompt: str = "",
    knowledge_prompt: str = "",
    model_name: str = "",
) -> UUID:
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
    project = await projects.load(project_id)
    await catch_up_project_tip(project, repository)
    import research_team.session.application.session_service as _session_service

    uuid_func = getattr(_session_service, "uuid4", uuid4)
    session_id = uuid_func()
    project.execute(JoinProject(session_id=session_id))

    state = project.state
    base_prompt = default_system_prompt + knowledge_prompt
    if state.tip_session_id is None:
        session = repository.create(session_id)
        session.execute(
            StartSession(
                session_id=session_id,
                system_prompt=base_prompt + project_context(state.name),
                model_name=model_name,
                project_id=project_id,
                purpose=purpose,
            )
        )
        await repository.save(session)
    else:
        await fork_session_files(
            repository,
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
            system_prompt=base_prompt,
            model_name=model_name,
        )

    await projects.save(project)
    return session_id


async def release_session_project(
    projects: AggregateRepository[Project],
    repository: SessionRepository,
    session_id: UUID,
) -> None:
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
    session = await repository.load(session_id)
    if session.state.project_id is None:
        return
    project = await projects.load(session.state.project_id)
    if project.state.active_session_id != session_id:
        return
    project.execute(AdvanceTip(session_id=session_id, at_event=session.version))
    await projects.save(project)


async def ensure_session_project_attached(
    repository: SessionRepository,
    attachment: KnowledgeAttachment | None,
    session_id: UUID,
) -> bool:
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
    if attachment is None:
        return False
    session = await repository.load(session_id)
    project_id = session.state.project_id
    if project_id is None:
        return False
    if attachment.attached_project_id == project_id:
        return True
    await attachment.attach(project_id)
    return attachment.attached_project_id == project_id


class ProjectSessions:
    """Project session and lifecycle operations over repository and aggregates."""

    def __init__(
        self,
        repository: SessionRepository,
        projects: AggregateRepository[Project],
        *,
        default_system_prompt: str = "",
        knowledge_prompt: str = "",
        model_name: str = "",
        executor: TurnExecutor | None = None,
        attachment: KnowledgeAttachment | None = None,
        graphs: ProjectGraphs | None = None,
    ) -> None:
        self._repository = repository
        self._projects = projects
        self._default_system_prompt = default_system_prompt
        self._knowledge_prompt = knowledge_prompt
        self._model_name = executor.model_name if executor is not None else model_name
        self._executor = executor
        self._attachment = attachment
        self._graphs = graphs

    @property
    def projects(self) -> AggregateRepository[Project]:
        """The `Project` aggregate repository, for callers that need it directly."""
        return self._projects

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

        They did. `presenters.topic_documents_view` grew a second resolution
        that sent `tip_at_event` as the scrub point beside the list this
        builds, so one response listed a file written after a release and then
        handed the reader routes a point at which it does not exist. Settled
        on 2026-08-27 in favour of this one, and the criterion was
        `_catch_up_tip` rather than an argument: that method exists to drag a
        stale tip up to `len(history)`, which is HEAD, so an offset below HEAD
        is never a statement about what the project has. Measured against a
        `local_copy` of `~/.research-team/sessions.db` -- every live project
        there had `tip_at_event` exactly equal to its tip session's stream
        length, so the real data could not separate the two, and the
        divergence had to be reproduced synthetically. See that function's
        docstring for the paths.
        """
        return await resolve_project_files(self._projects, self._repository, project_id)

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
        await delete_project_aggregate(self._projects, project_id, graphs=self._graphs)

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
        return await start_session_in_project(
            self._projects,
            self._repository,
            project_id,
            purpose,
            default_system_prompt=self._default_system_prompt,
            knowledge_prompt=self._knowledge_prompt,
            model_name=self._model_name,
        )

    async def catch_up_tip(self, project: Any) -> None:
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
        await catch_up_project_tip(project, self._repository)

    async def _catch_up_tip(self, project: Any) -> None:
        await self.catch_up_tip(project)

    async def fork_files_from(
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
        await fork_session_files(
            self._repository,
            session_id,
            source_session_id=source_session_id,
            at_event=at_event,
            project_id=project_id,
            purpose=purpose,
            system_prompt=self._default_system_prompt + self._knowledge_prompt,
            model_name=self._model_name,
            project_name=project_name,
        )

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
        await self.fork_files_from(
            session_id,
            source_session_id=source_session_id,
            at_event=at_event,
            project_id=project_id,
            purpose=purpose,
            project_name=project_name,
        )

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
        await release_session_project(self._projects, self._repository, session_id)

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
        return await ensure_session_project_attached(
            self._repository, self._attachment, session_id
        )

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

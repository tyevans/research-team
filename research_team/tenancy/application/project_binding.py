"""Session-project binding, tip catch-up, and file inheritance logic.

Extracted from `project_sessions.py` to isolate the mechanics of joining a
project, inheriting its filesystem via stream forking, catching up tip
pointers, releasing project claims, and attaching project knowledge graphs.
"""

import logging
from typing import Any
from uuid import UUID, uuid4

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.knowledge.application.knowledge_attachment import (
    KnowledgeAttachment,
)
from research_team.platform.shared.ports import SessionRepository
from research_team.session.domain import (
    FILE_EVENT_TYPES,
    INHERITED_EVENT_FIELDS,
    RecordForkSource,
    SessionPurpose,
    StartSession,
)
from research_team.tenancy.domain import (
    AdvanceTip,
    JoinProject,
    Project,
)

logger = logging.getLogger(__name__)

__all__ = [
    "catch_up_project_tip",
    "ensure_session_project_attached",
    "fork_session_files",
    "project_context",
    "release_session_project",
    "resolve_project_files",
    "start_session_in_project",
]


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
        if isinstance(event, FILE_EVENT_TYPES):
            session.create_event(
                type(event), **event.model_dump(exclude=set(INHERITED_EVENT_FIELDS))
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
    session_id: UUID | None = None,
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

    if session_id is None:
        session_id = uuid4()
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
            project_name=state.name,
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
        logger.warning(
            "session %s with project %s attempted to release, but project is held by %s",
            session_id,
            session.state.project_id,
            project.state.active_session_id,
        )
        return
    project.execute(AdvanceTip(session_id=session_id, at_event=session.version))
    await projects.save(project)


async def ensure_session_project_attached(
    repository: SessionRepository,
    attachment: KnowledgeAttachment | None,
    session_id: UUID,
    *,
    projects: AggregateRepository[Project] | None = None,
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
    if projects is not None:
        project = await projects.load(project_id)
        if project.state.status in ("deleted", "archived"):
            if attachment.attached_project_id == project_id:
                await attachment.detach()
            return False
    if attachment.attached_project_id == project_id:
        return True
    await attachment.attach(project_id)
    return attachment.attached_project_id == project_id

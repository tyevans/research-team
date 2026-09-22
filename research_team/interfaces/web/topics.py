"""The Topics, Dispatch, and Worker Roster HTTP surface.

Its own module and its own router, following `catalog.py`, `dialogues.py`,
`sources.py`, and `interactions.py`: `create_app` is thousands of lines of
closures and modularizing these routes extracts hundreds of lines from `app.py`.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from eventsource import AggregateRepository, CommandRejectedError
from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.presenters import (
    seeding_view,
    topic_detail_view,
    topic_documents_view,
    topic_view,
)
from research_team.interfaces.web.seeding import RunAlreadyActive, SeedingActivity
from research_team.interfaces.web.topic_dispatch import (
    MAX_BULK_DISPATCH,
    BulkDispatch,
    DispatchDeps,
    NewDispatch,
    dispatch_router,
)
from research_team.research.application.media_curation import (
    CurationUnavailable,
    MediaCurationService,
    MediaCurationTextPort,
    MediaSearchPort,
)
from research_team.research.application.topic_dispatch import (
    TopicDispatcher,
    topic_directory,
)
from research_team.research.application.topic_read import TopicReadPort
from research_team.research.application.topic_seeding import TopicSeeder
from research_team.research.application.topics import TopicService
from research_team.research.domain.media_proposals import MediaProposals
from research_team.research.domain.topic import (
    AddSubQuestion,
    ResolveSubQuestion,
    RestateTopicQuestion,
    SetTopicStatus,
    Topic,
    TopicStatus,
)
from research_team.session.application.session_service import SessionService
from research_team.session.application.workers import WorkerRoster

TopicReaders = Callable[[UUID], TopicReadPort]
"""One project's `TopicReadPort`, built on demand.

A callable rather than a bare port because a `TopicReadPort` is bound to one
project's stream prefix -- passing a single reader into `create_app` would either
force one project's view across all routes or leak topic state across project
boundaries.
"""


class StatusChange(BaseModel):
    """A human's decision to move a topic, with the reason `decide` requires.

    `justification` cannot be blank, and whitespace does not count as
    content: `Field(min_length=1)` alone would let `"   "` through, and the
    aggregate went out of its way to make an unexplained status change
    impossible -- a transport that let whitespace past that gate would
    quietly undo it. The strip happens here, before the aggregate is even
    loaded, so a blank justification is a 422 rather than a 409 the aggregate
    would raise anyway; the outcome the caller needs to fix is the same
    either way, but failing before a write was attempted is the honest report
    of what happened.
    """

    to_status: TopicStatus
    justification: str = Field(min_length=1)

    @field_validator("justification")
    @classmethod
    def _justification_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("a status change requires a justification")
        return stripped


class QuestionRestatement(BaseModel):
    """A human's decision to clarify or restate a topic's question."""

    question: str = Field(min_length=1)
    rationale: str = ""

    @field_validator("question")
    @classmethod
    def _question_is_not_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("a topic question cannot be blank")
        return stripped


class NewSubQuestion(BaseModel):
    """A question worth tracking under a topic, addressed by its own key."""

    key: str
    question: str


class SubQuestionAnswer(BaseModel):
    """An answer to one sub-question, named in the path rather than the body.

    Mirrors `Attempt`'s reasoning for keeping the target out of the body only
    where it does not apply: a sub-question key has no slashes, so there is
    no encoding hazard in putting it in the path, and doing so is what makes
    `/sub-questions/{key}/resolve` a URL a client can build without first
    parsing a body shape.
    """

    answer: str


class NewSeed(BaseModel):
    """What one seeding turn is asked to name topics for.

    `max_topics` defaults to 8 rather than being required, matching every
    other cap in this file (`NewRun.max_rounds` above): a caller that wants
    the ordinary amount says nothing about it, and the number this layer
    defaults to is the one `TopicSeeder`'s own tests exercise.
    """

    subject: str = Field(min_length=1)
    max_topics: int = 8


@dataclass(frozen=True)
class TopicDeps:
    """What the topic, dispatch, and worker routes need from `create_app`'s closure.

    A record rather than a long parameter list, matching `SourceDeps`, `ExportDeps`,
    `SettingsDeps`, and `CatalogDeps`.
    """

    require_project: Callable[[UUID], Awaitable[None]] | None = None
    topics: TopicReaders | None = None
    topic_repository: AggregateRepository[Topic] | None = None
    topic_service: TopicService | None = None
    service: SessionService | None = None
    topic_seeder: TopicSeeder | None = None
    seeding: SeedingActivity | None = None
    dispatcher: TopicDispatcher | None = None
    dispatch: DispatchQueue | None = None
    workers: WorkerRoster | None = None
    media_proposal_repository: AggregateRepository[MediaProposals] | None = None
    curation_text: MediaCurationTextPort | None = None
    curation_search: MediaSearchPort | None = None
    topic_reader: Callable[[UUID], TopicReadPort] | None = None


def topic_router(deps: TopicDeps) -> APIRouter:
    """The topics, dispatch, and workers router, ready for `app.include_router`."""
    router = APIRouter()

    async def _check_project(project_id: UUID) -> None:
        if deps.require_project is not None:
            await deps.require_project(project_id)

    def _topic_reader(project_id: UUID) -> TopicReadPort:
        """This project's topics, through the port composition assembled.

        503 rather than 404 when `topics` was not wired, matching `_reader`:
        a build with no topic read model is a valid thing to serve, and the
        caller needs to know the server cannot answer rather than that the
        project has none.
        """
        if deps.topic_reader is not None:
            return deps.topic_reader(project_id)
        if deps.topics is None:
            raise HTTPException(status_code=503, detail="no topic read model is configured")
        return deps.topics(project_id)

    def _topic_repo() -> AggregateRepository[Topic]:
        """The `Topic` aggregate repository, for routes that change a topic.

        503 rather than 404 when `topic_repository` was not wired, matching
        `_topic_reader`: a build with no write model configured is a valid
        thing to serve read-only, and the caller needs to know the server
        cannot answer rather than that the topic is missing.
        """
        if deps.topic_repository is None:
            raise HTTPException(status_code=503, detail="no topic write model is configured")
        return deps.topic_repository

    def _topic_service() -> TopicService:
        """The `TopicService`, for operations that manage a topic's lifecycle.

        503 rather than 404 when neither `topic_service` nor `topic_repository` was wired:
        a build with no write model configured is a valid thing to serve read-only.
        """
        if deps.topic_service is not None:
            return deps.topic_service
        if deps.topic_repository is not None:
            return TopicService(deps.topic_repository)
        raise HTTPException(status_code=503, detail="no topic write model is configured")

    def _curation_service(project_id: UUID) -> MediaCurationService:
        """The three-stage chain, wired for one project's topics.

        Built per request rather than held on the app, mirroring `_reader`
        and `_editor`: `MediaCurationService.topics` is one project's
        `TopicReadPort` (`_topic_reader`), and a single shared instance
        would either leak one project's topics into another's `curate` call
        or have to take the project as a second argument the port refuses to
        accept for exactly this reason.

        503 when any of the three optional dependencies it needs --
        `media_proposal_repository`, `curation_text`, `curation_search` --
        was not wired, matching every other optional feature in this module.
        """
        if (
            deps.media_proposal_repository is None
            or deps.curation_text is None
            or deps.curation_search is None
        ):
            raise HTTPException(status_code=503, detail="media curation is not configured")
        return MediaCurationService(
            text=deps.curation_text,
            search=deps.curation_search,
            proposals=deps.media_proposal_repository,
            topics=_topic_reader(project_id),
        )

    async def _change_topic(project_id: UUID, topic_id: UUID, command) -> dict[str, Any]:
        """Apply one command to a topic, the same way every write route below does.

        The three routes below (status, add sub-question, resolve sub-question)
        share this rather than repeating it, because all three have the same
        shape: confirm the topic is this project's before touching anything,
        let `decide` accept or refuse the command, and answer with the page the
        read route already draws -- so a write and the read that follows it can
        never disagree about what the topic now looks like.

        The existence check goes through `_topic_reader` rather than a bare
        `try/except` on the repository load, because it is what makes a
        foreign topic's 404 byte-identical to an unknown one here too: the
        reader's `read_topic` already collapses both to `None` (see its
        docstring), and repeating that collapse against the aggregate
        directly would risk drifting from it as either evolves.
        """
        reader = _topic_reader(project_id)
        await _check_project(project_id)
        detail = await reader.read_topic(topic_id)
        if detail is None:
            raise HTTPException(
                status_code=404, detail=f"no such topic in project {project_id}"
            )
        repo = _topic_repo()
        topic = await repo.load(topic_id)
        try:
            topic.execute(command)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await repo.save(topic)
        updated = await reader.read_topic(topic_id)
        # `detail` above already proved the topic exists in this project, and
        # nothing between that read and this one can make it stop existing --
        # so a `None` here would mean the reader and the repository disagree
        # about a write this route just made, not a caller's mistake.
        assert updated is not None
        return topic_detail_view(updated)

    @router.get("/api/projects/{project_id}/topics")
    async def list_topics(project_id: UUID):
        """Every topic this project tracks, ranked on nothing -- the queue does that."""
        await _check_project(project_id)
        reader = _topic_reader(project_id)
        return [topic_view(view) for view in await reader.list_topics()]

    @router.post("/api/projects/{project_id}/topics/seed")
    async def seed_topics(project_id: UUID, body: NewSeed):
        """Start one seeding turn that names this project's first topics.

        Registered ahead of `/topics/{topic_id}` below -- FastAPI matches
        routes in declaration order, and `seed` would otherwise be parsed as
        a topic id and 422 on every call.

        202, matching `dispatch_topic`: the turn has not finished when
        this answers, and what it hands back is the id of a run that has
        *begun*. The topics it opens arrive over the log like any other
        `open_topic` call -- a client that wants them invalidates its topic
        list on those frames rather than reading this response for them.

        503 rather than 404 when unwired, matching `_topic_reader` above:
        this build is missing configuration, not the project this id names.
        409 when a seed is already running on this project -- see
        `seeding.py`'s `SeedingActivity.start` for why `RunAlreadyActive` is
        the right exception for a control that appears once on a page.
        """
        if deps.topic_seeder is None or deps.seeding is None:
            raise HTTPException(status_code=503, detail="topic seeding is not configured")
        await _check_project(project_id)
        try:
            frame = deps.seeding.start(
                project_id,
                lambda run_id: deps.topic_seeder.seed(
                    project_id, body.subject, body.max_topics, run_id=run_id
                ),
            )
        except RunAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=seeding_view(frame))

    @router.get("/api/projects/{project_id}/topics/seed")
    async def get_seed(project_id: UUID):
        """What the running seed has done so far, and the last one's account.

        A tab that arrived mid-run, or one whose connection dropped, has no
        other way back -- see `seeding.py`'s module docstring. 200 with both
        halves `None` when nothing has run, matching `get_extraction`'s own
        reasoning: an absent seed is a state, not a missing resource.
        """
        await _check_project(project_id)
        if deps.seeding is None:
            return {"current": None, "last": None}
        return {
            "current": seeding_view(deps.seeding.current(project_id)),
            "last": seeding_view(deps.seeding.last(project_id)),
        }

    @router.get("/api/projects/{project_id}/topics/{topic_id}/documents")
    async def list_topic_documents(project_id: UUID, topic_id: UUID):
        """Everything a dispatch has written about one topic, and where to read it.

        Registered ahead of `/topics/{topic_id}`, matching every other
        sub-path here: FastAPI matches in declaration order.

        **This is what makes a dispatch's output findable at all.** A dispatch
        writes on a session it creates and releases, and the research view has
        no handle on that session -- so without this route the file exists,
        is on the feed, is scrubbable, and is reachable only by someone who
        already knows which session id to look under.

        The directory is recomputed from the topic's *current* position rather
        than stored, which is the one real cost of numbering by position: a
        topic that moved in the list since its document was written will have
        this route look in a directory that does not exist, and answer an
        empty listing. The alternative was a stored number, which means a new
        field on an event, and this design adds none. Worth revisiting if
        topic order turns out to churn.

        An empty listing rather than a 404 for a topic nobody has dispatched
        at: that is the ordinary case, and the directory it *would* be written
        to is what an empty state wants to name. 404 is reserved for a topic
        this project does not have.
        """
        await _check_project(project_id)
        views = await _topic_reader(project_id).list_topics()
        position = next(
            (index for index, view in enumerate(views) if view.summary.topic_id == topic_id),
            None,
        )
        if position is None:
            raise HTTPException(
                status_code=404, detail=f"no such topic in project {project_id}"
            )
        if deps.service is None:
            raise HTTPException(status_code=503, detail="session service is not configured")
        return topic_documents_view(
            topic_directory(position, views[position].summary.question),
            await deps.service.project_files(project_id),
            await deps.service.project_state(project_id),
        )

    router.include_router(dispatch_router(deps))

    @router.post("/api/projects/{project_id}/topics/{topic_id}/media-proposals")
    async def run_media_curation(project_id: UUID, topic_id: UUID):
        """Run the three-stage chain once for this topic. 202: what changed
        is a fact on the log by the time this answers, not a promise the
        caller waits on -- but the interesting state (the proposals
        themselves) is read back through `GET .../media-proposals`, not this
        response, the way `dispatch_topic` above treats its own 202.
        """
        await _check_project(project_id)
        service = _curation_service(project_id)
        try:
            outcome = await service.curate(project_id, topic_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CurationUnavailable as error:
            raise HTTPException(status_code=502, detail=str(error)) from error
        return JSONResponse(
            status_code=202,
            content={
                "needs": outcome.needs,
                "candidates": outcome.candidates,
                "ignored": outcome.ignored,
                "rejected_parses": outcome.rejected_parses,
                "searched_empty": outcome.searched_empty,
                "judged_out": outcome.judged_out,
            },
        )

    @router.patch("/api/projects/{project_id}/topics/{topic_id}/question")
    async def restate_topic_question(
        project_id: UUID, topic_id: UUID, body: QuestionRestatement
    ):
        """Restate or clarify a topic's question (B39).

        Human-only, for the same reason `set_topic_status` is: shaping what a
        topic is asking is a reader's editorial decision, not a finding an
        autonomous run records.
        """
        return await _change_topic(
            project_id,
            topic_id,
            RestateTopicQuestion(question=body.question, rationale=body.rationale),
        )

    @router.post("/api/projects/{project_id}/topics/{topic_id}/status")
    async def set_topic_status(project_id: UUID, topic_id: UUID, body: StatusChange):
        """Move a topic to a new status, with the reason `decide` requires.

        Human-only: there is no agent tool for this and none should be added.
        `application/topics.py` documents closing as a decision a person makes,
        not the model recording what it found -- an autonomous run can learn
        that a question is answered, but only a reader gets to say the project
        is done asking it. Reopening an answered topic is legal here for the
        same reason it is legal in the aggregate: `decide` refuses only a
        no-op transition, and a reader who closed a topic too early has no
        other way back in.
        """
        return await _change_topic(
            project_id,
            topic_id,
            SetTopicStatus(to_status=body.to_status, justification=body.justification),
        )

    @router.post("/api/projects/{project_id}/topics/{topic_id}/sub-questions/{key}/resolve")
    async def resolve_sub_question(
        project_id: UUID, topic_id: UUID, key: str, body: SubQuestionAnswer
    ):
        """Answer a tracked sub-question. Human-only, for the same reason above."""
        return await _change_topic(
            project_id, topic_id, ResolveSubQuestion(key=key, answer=body.answer)
        )

    @router.post("/api/projects/{project_id}/topics/{topic_id}/sub-questions")
    async def add_sub_question(project_id: UUID, topic_id: UUID, body: NewSubQuestion):
        """Track a question under a topic, addressed by `key` rather than an index.

        Human-only, for the same reason `set_topic_status` is: shaping what a
        topic is asking is a reader's editorial decision, not a finding an
        autonomous run records. `key` rather than a position because a
        sub-question, once resolved, is referred back to by name -- a client
        showing "does it hold for motor skills?" needs a stable handle to
        resolve it against later, and a list position shifts under it the
        moment another sub-question is added or removed.
        """
        return await _change_topic(
            project_id,
            topic_id,
            AddSubQuestion(key=body.key, question=body.question),
        )

    @router.get("/api/projects/{project_id}/topics/{topic_id}")
    async def read_topic(project_id: UUID, topic_id: UUID):
        """One topic's own page. 404 for an unknown id and for a foreign one alike.

        `ProjectTopicReader.read_topic` already collapses those two cases to
        `None` -- see its docstring -- so this route has nothing left to
        distinguish; doing so here would leak the very thing the port exists
        to withhold. The message deliberately does not echo `topic_id` back:
        doing so would make the response for "this id belongs to another
        project" differ, byte for byte, from the response for "this id was
        never opened" whenever the two cases are compared with different
        ids -- which is the only way to compare them, since an id cannot be
        both foreign and never-opened at once. Naming only the project keeps
        every 404 under it identical, which is what actually keeps the two
        cases indistinguishable rather than merely both being 404s.
        """
        reader = _topic_reader(project_id)
        await _check_project(project_id)
        detail = await reader.read_topic(topic_id)
        if detail is None:
            raise HTTPException(
                status_code=404, detail=f"no such topic in project {project_id}"
            )
        return topic_detail_view(detail)

    return router


topics_router = topic_router


def mount_topic_routes(app: FastAPI, deps: TopicDeps) -> None:
    """Mount the topic router on the given FastAPI app."""
    app.include_router(topic_router(deps))


__all__ = [
    "MAX_BULK_DISPATCH",
    "BulkDispatch",
    "DispatchDeps",
    "NewDispatch",
    "NewSeed",
    "NewSubQuestion",
    "QuestionRestatement",
    "StatusChange",
    "SubQuestionAnswer",
    "TopicDeps",
    "TopicReaders",
    "dispatch_router",
    "mount_topic_routes",
    "topic_router",
    "topics_router",
]

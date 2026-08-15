"""HTTP + SSE adapter over the same use cases the REPL drives.

Stateless by construction: every route names the session it acts on, so any
number of browsers can look at any number of sessions at once. That is the
whole reason the application layer stopped holding a "current session".
"""

import asyncio
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from eventsource import CommandRejectedError, OptimisticLockError
from eventsource.application.aggregates.repository import AggregateRepository
from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from research_team.application import (
    ApprovalDecision,
    AutonomyPolicy,
    LiveFeed,
    ResearchSupervisor,
    RunAlreadyActive,
    SessionService,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
    WorkerRoster,
    build_fork_tree,
)
from research_team.application.ask import AskAnswer, AskInFlight, AskService
from research_team.application.blobs import BlobStorePort
from research_team.application.components import View, parse_document, project
from research_team.application.corpus_editing import CorpusEditor, DocumentExists, NotDropped
from research_team.application.corpus_spans import quote
from research_team.application.course import course_progress
from research_team.application.document_extraction import DocumentExtractor, UnknownDocument
from research_team.application.entity_definitions import DefinitionService
from research_team.application.grading import GradingError, grade
from research_team.application.graph_read import (
    MAX_GRAPH_NODES,
    MAX_NEIGHBORHOOD_DEPTH,
    MAX_USAGES,
    GraphReadPort,
)
from research_team.application.knowledge import KnowledgeError
from research_team.application.ports import ActivityDelta, ActivityMessage
from research_team.application.project_graphs import ProjectGraphs
from research_team.application.timeline_read import (
    MAX_TIMELINE_BANDS,
    TimelineInterval,
    TimelineReadPort,
)
from research_team.application.topic_dispatch import (
    DISPATCH_ACTIONS,
    TopicDispatcher,
    topic_directory,
)
from research_team.application.topic_read import TopicReadPort
from research_team.application.topic_seeding import TopicSeeder
from research_team.domain import Corpus, CreateProject, Project, ProjectState, SelectWorkflow
from research_team.domain.project import current_stage_of
from research_team.domain.research_run import Budget
from research_team.domain.topic import (
    AddSubQuestion,
    ResolveSubQuestion,
    SetTopicStatus,
    Topic,
    TopicStatus,
)
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader
from research_team.infrastructure.knowledge.usage_reader import UsageReader
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.event_store import KNOWLEDGE_CATEGORIES
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import UnknownApproval, WebApprovals
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue
from research_team.interfaces.web.presenters import (
    autonomy_view,
    corpus_change,
    course_view,
    definition_view,
    dispatch_view,
    entity_page_view,
    event_rows,
    feed_event,
    file_history,
    graph_change,
    graph_view,
    item_view,
    neighborhood_view,
    preset_view,
    progress_view,
    project_change,
    project_view,
    roster_view,
    run_view,
    seeding_view,
    session_view,
    source_text_view,
    source_view,
    stage_view,
    summary_view,
    timeline_view,
    topic_change,
    topic_detail_view,
    topic_documents_view,
    topic_view,
    tree_view,
    usages_view,
)
from research_team.interfaces.web.seeding import SeedingActivity
from research_team.workflows import PRESETS

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"


class _RevalidatedStatics(StaticFiles):
    """`StaticFiles`, plus the one response header its filenames now require.

    The console's chunks are emitted without a content hash in their names, so
    that rebuilding them is an edit rather than a rename and two branches can be
    merged without a conflict per chunk -- `frontend/vite.config.ts` carries
    that argument. The consequence is that a given URL no longer names fixed
    bytes, and a browser must be told to check.

    Starlette sends `ETag` and `Last-Modified` and no `Cache-Control` at all
    (measured against starlette 1.3.1, not assumed). With no explicit freshness,
    a browser is entitled to *heuristic* freshness -- conventionally a tenth of
    the file's age -- and applies it without asking the server. That is harmless
    for a hashed filename, which is never reused for different bytes. Here it is
    the whole bug: a chunk untouched for a month may be served from cache for
    days after it changes, beside an `index.html` that did change, and the pair
    do not run. The failure is a blank console, not an error.

    `no-cache` does not mean "do not store" -- it means "revalidate before
    reuse". The cost is one conditional request per asset per load, answered
    `304` with no body, against a server that is normally on the same machine.
    That is the right trade for a console whose whole job is showing the state
    of a running system.

    What a test would fail on: `test_web_static_caching.py` asserts the header
    is present on an asset. Delete this class and it goes red rather than
    quietly reopening the window above.
    """

    async def get_response(self, path: str, scope: Any) -> Response:
        response = await super().get_response(path, scope)
        # Set on 404s and 304s too, which costs nothing and avoids a rule about
        # which status codes carry it.
        response.headers["Cache-Control"] = "no-cache"
        return response


KEEPALIVE_SECONDS = 15.0

DISCONNECT_CHECK = 0.5
"""How long we may sit unaware that the browser has gone."""

MAX_UPLOAD_BYTES = 2 * 1024**3
"""The largest media upload this will accept, in bytes.

Streaming the upload bounds *memory*; only this bounds *disk*. A two-hour
recording is comfortably under it and a runaway client is not, which is the
line it is drawn at -- there is no measurement behind the exact number, and
raising it is a one-line change with no other consequence.

Enforced by wrapping the chunk iterator handed to `BlobStorePort.put`, not by
checking a total after `put` returns: by then the bytes are already on disk,
which is the one thing a ceiling exists to prevent. `put`'s own
`except BaseException` unlinks its temporary file when the wrapper raises
through it, so a refused upload leaves nothing behind.
"""

UPLOAD_CHUNK_BYTES = 1024 * 1024
"""How much is read from the request per iteration, matching
`FilesystemBlobStore.CHUNK_SIZE` for its reasons."""


class _UploadTooLarge(Exception):
    """The ceiling was crossed mid-stream. Raised from inside `put`'s loop."""


#: Leading bytes that identify a format, for the cases a browser gets wrong.
#: Deliberately short: this is not a content-type database, it is a correction
#: for `application/octet-stream`, which is what a browser sends for anything
#: the operating system has no association for -- `.mkv` and `.webm` on a bare
#: machine, most often. A format missing from here is stored under whatever the
#: browser said, which is the same behaviour as before sniffing existed.
_MAGIC_NUMBERS: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"GIF87a", "image/gif"),
    (b"GIF89a", "image/gif"),
    (b"%PDF-", "application/pdf"),
    (b"OggS", "audio/ogg"),
    (b"ID3", "audio/mpeg"),
    (b"fLaC", "audio/flac"),
    # EBML, which is Matroska *and* WebM -- the magic number cannot tell them
    # apart, and reading far enough to find the DocType is more parsing than a
    # correction for a wrong header is worth. `video/webm` is the deliberate
    # choice of the two: it is the same container family, it is what a browser
    # will attempt, and being wrong costs a `<video>` that fails on codec
    # rather than one that never tries. `video/x-matroska` would be the
    # honest label for a `.mkv` and Chromium refuses to play it outright, so
    # the accurate answer is the less useful one here.
    (b"\x1a\x45\xdf\xa3", "video/webm"),
)


def _sniff_media_type(head: bytes) -> str | None:
    """What the leading bytes say this is, or `None` if they say nothing.

    The two container formats that cannot be a prefix table are handled first:
    ISO base media (`.mp4`, `.m4a`, `.mov`) puts `ftyp` at offset 4 behind a
    length, and RIFF puts its real form at offset 8.
    """
    if head[4:8] == b"ftyp":
        return "video/mp4"
    if head[:4] == b"RIFF":
        if head[8:12] == b"WAVE":
            return "audio/wav"
        if head[8:12] == b"AVI ":
            return "video/x-msvideo"
        return None
    for prefix, media_type in _MAGIC_NUMBERS:
        if head.startswith(prefix):
            return media_type
    return None


class _RangeNotSatisfiable(Exception):
    """A range starting past the end. 416, with the real length attached."""

    def __init__(self, total: int) -> None:
        super().__init__(f"range starts past the end of {total} bytes")
        self.total = total


def _parse_byte_range(header: str, total: int) -> tuple[int, int] | None:
    """`Range: bytes=…` as an inclusive `(start, end)`, or `None` to ignore it.

    `None` for anything this does not understand -- multiple ranges, a unit
    that is not `bytes`, a malformed header -- because RFC 9110 says a
    recipient that cannot satisfy a Range must ignore it and answer 200 with
    the whole representation. Answering 400 instead would break a client that
    was entitled to ask.

    An end below the start (`bytes=2-1`) is ignored too, and that is a
    distinction worth keeping straight: RFC 9110 §14.1.1 makes a
    `last-byte-pos` below `first-byte-pos` an *invalid* byte-range-spec, and
    an invalid ranges-specifier must be ignored rather than refused. Only a
    range starting at or past the end is genuinely *unsatisfiable*, and that
    is what raises `_RangeNotSatisfiable` -- there the client asked for bytes
    that do not exist and a 200 would silently give it different ones.

    The three forms, all of which a browser sends: `bytes=2-5` (both ends),
    `bytes=2-` (open-ended, what a `<video>` sends first), and `bytes=-500`
    (the last 500 bytes, which is how a player finds an MP4's trailing
    `moov` atom).

    **Every form is decided against `total` in one place, at the bottom.** The
    suffix branch used to return before reaching it, and against a zero-byte
    blob that produced `(0, -1)` and a response header of
    `content-range: bytes 0--1/0` -- not a valid `Content-Range`, and a strict
    client is entitled to call the response broken.
    `test_a_suffix_range_against_an_empty_blob_answers_416` is what fails if
    any branch takes a short cut past the guard again.
    """
    unit, _, spec = header.partition("=")
    if unit.strip().lower() != "bytes" or "," in spec:
        return None
    first, sep, last = spec.strip().partition("-")
    if not sep:
        return None
    try:
        if not first:
            if not last:
                return None
            length = int(last)
            if length <= 0:
                return None
            # Suffix form: the last N bytes, which for a blob shorter than N
            # begins at byte zero. Its end is `None` -- "to the last byte" --
            # rather than `total - 1`, so that an empty blob reaches the
            # unsatisfiable check below instead of arriving there as an end of
            # -1 that looks like the invalid spec it is not.
            start, requested_end = max(0, total - length), None
        else:
            start = int(first)
            requested_end = None if not last else int(last)
    except ValueError:
        return None
    if requested_end is not None and requested_end < start:
        return None
    if start >= total:
        raise _RangeNotSatisfiable(total)
    # An absent end means "to the last byte", and an end past the last byte is
    # clamped rather than refused -- a client that asks for more than there is
    # gets what there is, which is what a player expects.
    return start, total - 1 if requested_end is None else min(requested_end, total - 1)


async def _first_bytes(stream: AsyncIterator[bytes], length: int) -> AsyncIterator[bytes]:
    """The first `length` bytes of a stream, then stop.

    Only the *tail* is trimmed here. The head is `BlobStorePort.open`'s
    `start`, which is a real `seek` -- this used to discard the prefix chunk
    by chunk instead, which made a seek into a 400MB film a ~300MB read, per
    seek, per viewer, while every byte-for-byte test stayed green. The
    trimming that remains cannot be pushed down the same way: the store reads
    in megabyte chunks and a range rarely ends on one.

    What a test would fail on: the arithmetic is off-by-one-prone in both
    directions -- an inclusive end read as exclusive truncates every seek by
    one byte -- and `test_the_range_forms_a_browser_actually_sends` holds it
    at both edges, open-ended, suffix and clamped.
    """
    sent = 0
    async for part in stream:
        remaining = length - sent
        if len(part) >= remaining:
            yield part[:remaining]
            return
        sent += len(part)
        yield part


DefinitionReaders = Callable[[UUID], Awaitable["DefinitionService | None"]]
"""One project's `DefinitionService`, built on demand, or `None` when this
build cannot make one.

A callable for `TopicReaders`' reason, awaitable for one more: a
`DefinitionService` is assembled from that project's graph store, that
project's chunk store and a project-bound view of the definition cache, and
opening the graph store is asynchronous. `project_id` is in the route's path
and has to reach all three -- a single shared `DefinitionService` would
answer every project out of whichever one it was built for, and because the
cache port takes no project argument (deliberately; see
`application/entity_definitions.py`) it would write those answers into that
project's rows too."""

TopicReaders = Callable[[UUID], TopicReadPort]
"""One project's `TopicReadPort`, built on demand.

A callable rather than a bare port because a `TopicReadPort` is bound to one
project at construction (see `ProjectTopicReader`), and a route serves every
project from one running app -- so what the route layer holds is the thing
that builds the bound reader, not a reader itself. Composition owns what the
callable closes over; `app.py` only calls it, the same division `_reader`
below keeps for `CorpusRunner`."""


# `NewSession` was here, with `POST /api/sessions`. Both are gone: a session
# belongs to a project, so the only way to make one is
# `POST /api/projects/{id}/join`, which is where the project agrees to be
# joined. A body carrying a `project_id` would have been the same endpoint
# with the project as a parameter instead of as the route, and two ways in is
# how one of them ends up not enforcing the rule.
#
# `system_prompt` had no replacement and needed none: it was only ever set by
# tests, and `start_in_project` composes the default prompt with the knowledge
# prompt, which a caller-supplied override would have silently dropped.


class NewTurn(BaseModel):
    input: str


class NewFork(BaseModel):
    at: int


class NewProject(BaseModel):
    name: str


class JoinOptions(BaseModel):
    """Whether a join may end the session currently holding the project."""

    take_over: bool = False


class WorkflowChoice(BaseModel):
    """Which preset a project runs. Chosen once; `decide` refuses a second."""

    preset_id: str


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


class Attempt(BaseModel):
    """One learner's answer to one component, addressed in the body.

    The component is named in the body rather than in the path because a file
    path contains slashes, and a route of `/files/{path}/components/{id}` would
    make every caller double-encode one to reach the other. Nothing else about
    the shape depends on that.

    `at` grades against the file as it stood at that event rather than at HEAD.
    Without it, an author revising a question would silently re-mark attempts
    made against the version the learner actually read.
    """

    path: str
    component_id: str
    response: Any = None
    at: int | None = None


class ChecklistState(BaseModel):
    """Which boxes are ticked on one checklist, addressed like an `Attempt`.

    Absolute rather than a toggle: the client sends the full set every time, so
    a dropped request costs one stale render rather than a box that is ticked
    in the log and clear on the screen forever.
    """

    path: str
    component_id: str
    checked: list[int] = Field(default_factory=list)
    at: int | None = None


class NewRun(BaseModel):
    """What an autonomous run is allowed to spend.

    Every field is optional and every default is the domain's, so a caller
    that wants a run says `{}` and gets the budget the aggregate documents
    rather than one this layer invented. Only the two limits a person
    actually reaches for are exposed: the others are shapes of the same
    backstop and would be four numbers nobody tunes.
    """

    max_rounds: int | None = None
    quiet_rounds: int | None = None

    fetch_hosts: list[str] = Field(default_factory=list)
    """Named hosts this run may fetch from, unattended. See `fetch_grant`.

    No wildcards, matched exactly (after lowercasing) against a URL's
    hostname -- `FetchGrant.covers` in `application/grants.py` is what
    actually enforces this; this layer only carries what a person typed.
    """

    fetch_budget: int = 0
    """How many of those fetches this run may spend, total. See `fetch_grant`."""

    def budget(self) -> Budget | None:
        """None when nothing was asked for, so the driver applies its own."""
        asked = {
            key: value
            for key, value in (
                ("max_rounds", self.max_rounds),
                ("quiet_rounds", self.quiet_rounds),
            )
            if value is not None
        }
        if not asked:
            return None
        # `max_turns` follows `max_rounds` rather than staying at its default:
        # a run capped at two rounds and fifty turns is capped at fifty turns,
        # and a caller asking for two rounds means two rounds' worth of work.
        if "max_rounds" in asked:
            asked.setdefault("max_turns", asked["max_rounds"] * 2)
        return Budget(**asked)

    def fetch_grant(self) -> tuple[list[str], int]:
        """The `(hosts, budget)` pair to start this run with, or a refusal.

        Both fields default to "nothing granted" (`[]`, `0`), which is the
        common case and needs no validation. Half a grant -- hosts named with
        no budget, or a budget with no hosts named -- is refused rather than
        silently coerced into "nothing granted" or "unlimited": whichever
        half a person supplied is the half that suggests they believed the
        other one was implied, and coercing either way would grant something
        nobody asked for or silently grant nothing at all. Raises `ValueError`
        so the route can turn it into a 422 naming the missing half, the same
        shape `service.start_in_project`'s `CommandRejectedError` already
        turns into a 409.
        """
        has_hosts = bool(self.fetch_hosts)
        has_budget = self.fetch_budget > 0
        if has_hosts and not has_budget:
            raise ValueError(
                "fetch_hosts was given without fetch_budget; a grant needs both "
                "or neither -- how many fetches should these hosts get?"
            )
        if has_budget and not has_hosts:
            raise ValueError(
                "fetch_budget was given without fetch_hosts; a grant needs both "
                "or neither -- which hosts should this budget cover?"
            )
        return list(self.fetch_hosts), self.fetch_budget


class NewSeed(BaseModel):
    """What one seeding turn is asked to name topics for.

    `max_topics` defaults to 8 rather than being required, matching every
    other cap in this file (`NewRun.max_rounds` above): a caller that wants
    the ordinary amount says nothing about it, and the number this layer
    defaults to is the one `TopicSeeder`'s own tests exercise.
    """

    subject: str = Field(min_length=1)
    max_topics: int = 8


class NewDispatch(BaseModel):
    """What an agent dispatched at one topic is being asked to do.

    Plain `str` rather than a `Literal`, so a bad value comes back from the
    route naming the actions that exist -- the same reasoning `AutonomyChoice`
    gives for its two fields. FastAPI's 422 for a `Literal` mismatch is
    machine-readable and names none of them, and `research` and `lesson` are
    exactly the values a caller will reasonably try: both are designed, in
    `docs/design/topic-dispatch.md`, and neither is built.

    Defaults to the one action that exists rather than being required. A
    client pressing the only button on offer should not have to name it.
    """

    action: str = "understanding"


class AskRequest(BaseModel):
    """One question on one ephemeral chat.

    `chat_id` is the browser's, not the server's: nothing persists a chat, so
    there is no id for a server to have issued. `ConversationRegistry` checks
    the project it was opened under rather than trusting it.
    """

    chat_id: str
    question: str


class Decision(BaseModel):
    """A human's answer to a parked approval. `type` is langchain's vocabulary."""

    type: str
    edited_args: dict | None = None
    message: str | None = None


class AutonomyChoice(BaseModel):
    """One tool's new autonomy level.

    Both fields are plain `str` rather than the `Level` literal and a tool
    enum, so that a bad value reaches `AutonomyPolicy.set` and comes back as
    that method's own complaint -- which names the offending value and says
    whether the problem was the level or the tool. FastAPI's 422 for a
    `Literal` mismatch is machine-readable and says neither, and this is a
    message a person reads off a switch they just flipped.
    """

    tool: str
    level: str


class AllowAll(BaseModel):
    """Whether "stop asking me" also crosses the workflow review gates.

    Defaults to false, and the default is the point: see
    `AutonomyPolicy.relax_all` for why `advance_stage` is not swept along with
    the hazards. A client that wants it says so.
    """

    include_stage_gates: bool = False


def create_app(
    service: SessionService,
    feed: LiveFeed,
    turns: TurnSupervisor,
    lifespan=None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
    corpus: CorpusRunner | None = None,
    blob_store: BlobStorePort | None = None,
    research: ResearchSupervisor | None = None,
    workers: WorkerRoster | None = None,
    extraction: ExtractionActivity | None = None,
    policy: AutonomyPolicy | None = None,
    topics: TopicReaders | None = None,
    topic_repository: AggregateRepository[Topic] | None = None,
    graphs: ProjectGraphs | None = None,
    topic_seeder: TopicSeeder | None = None,
    seeding: SeedingActivity | None = None,
    dispatcher: TopicDispatcher | None = None,
    dispatch: DispatchQueue | None = None,
    ask: AskService | None = None,
    extractor: DocumentExtractor | None = None,
    extract_queue: ExtractionQueue | None = None,
    definitions: DefinitionReaders | None = None,
    editor: CorpusEditor | None = None,
) -> FastAPI:
    """Build the app around an already-wired service. Composition stays outside.

    `lifespan` is how the composition root gets a foot inside the server's
    event loop. Anything holding a connection bound to the loop that opened it
    -- the `/sessions` projection, in particular -- has to be started there
    rather than at construction time, and this is the only hook the server
    offers for that.
    """
    app = FastAPI(title="research-team", docs_url="/api/docs", lifespan=lifespan)

    async def _load(session_id: UUID):
        try:
            return await service.load(session_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no session {session_id}") from error

    @app.get("/api/sessions")
    async def list_sessions():
        return [summary_view(summary) for summary in await service.list_sessions()]

    def _workflow_of(state: ProjectState) -> dict[str, Any]:
        """Which preset a project runs and where it stands in it, both nullable.

        Two absences, kept distinct. No preset selected is the ordinary case
        and answers `None` for both. A preset id this build does not ship --
        a project started against a preset since renamed or removed -- still
        reports the workflow, because the id is the only honest thing to say,
        but reports no stage: resolving a position needs the stage list, and
        inventing one would be worse than admitting the gap. Neither is a
        server error, so neither raises; a listing that 500s because one row
        names an unknown preset is a listing nobody can use to fix it.
        """
        if state.preset_id is None:
            return {"workflow": None, "stage": None}
        preset = PRESETS.get(state.preset_id)
        if preset is None:
            return {
                "workflow": {
                    "id": state.preset_id,
                    "name": state.preset_id,
                    "version": state.preset_version,
                },
                "stage": None,
            }
        stage = current_stage_of(state, preset)
        return {
            "workflow": {"id": preset.id, "name": preset.name, "version": preset.version},
            "stage": stage_view(preset, stage) if stage is not None else None,
        }

    @app.get("/api/projects")
    async def list_projects():
        projects = await service.list_projects()
        rows = []
        for project_id, name in projects:
            state = await service.project_state(project_id)
            rows.append(
                project_view(
                    project_id,
                    name,
                    active_session_id=state.active_session_id,
                    tip_at_event=state.tip_at_event,
                    **_workflow_of(state),
                )
            )
        return rows

    @app.get("/api/workflows")
    async def list_workflows():
        """The presets on offer, in recommendation order.

        Order is the recommendation, and it is load-bearing: whichever pure
        methodology a user picks they inherit that tradition's structural
        defect, and knowing which defect to tolerate takes exactly the
        expertise they came here without. The hybrid is first because it is
        the one that does not require that judgement.

        Static: presets are code in `research_team/workflows/`, validated at
        import, so there is nothing to load and nothing that can fail here.
        """
        return [preset_view(preset) for preset in PRESETS.values()]

    @app.post("/api/projects")
    async def create_project(body: NewProject):
        """Create a project by name. A name collision is a 409, not a second project.

        Mirrors `/project new` in the REPL: check-then-create over
        `list_projects` rather than letting the aggregate itself reject a
        duplicate name, because `Project` has no notion of "the project
        called X" -- names are only unique by convention of this list, and
        that convention is enforced here, the one place both front ends
        share through `SessionService`.
        """
        existing = await service.list_projects()
        collision = next((pid for pid, name in existing if name == body.name), None)
        if collision is not None:
            raise HTTPException(
                status_code=409,
                detail=f"project {body.name!r} already exists ({collision})",
            )
        aggregate = service.projects.create_new(uuid4())
        aggregate.execute(CreateProject(project_id=aggregate.aggregate_id, name=body.name))
        await service.projects.save(aggregate)
        return project_view(aggregate.aggregate_id, body.name)

    @app.delete("/api/projects/{project_id}")
    async def delete_project(project_id: UUID, release_holder: bool = False):
        """Retire a project. `release_holder` ends the session still driving it.

        The holder is not released implicitly: releasing advances the tip,
        which writes to that session, and a delete that quietly did so would
        make a destructive-sounding verb do an unrelated write. Asking for it
        explicitly keeps both halves visible -- and gives the UI something to
        put in its confirmation prompt rather than a bare 409 to relay.
        """
        # An id nothing was ever written under raises from the repository
        # rather than folding to an empty state, so "no such project" arrives
        # two different ways and both have to become the same 404.
        try:
            state = await service.project_state(project_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no project {project_id}") from error
        if state.status == "new":
            raise HTTPException(status_code=404, detail=f"no project {project_id}")
        holder = state.active_session_id
        if holder is not None:
            if not release_holder:
                raise HTTPException(
                    status_code=409,
                    detail=f"project is held by session {holder}; end that session first",
                )
            if turns.is_running(holder):
                raise HTTPException(
                    status_code=409,
                    detail="the holding session has a turn running; cancel it first",
                )
            await service.release_project(holder)
        try:
            await service.delete_project(project_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        if service.attached_project_id == project_id:
            await service.detach_project()
        return {"deleted": True, "project_id": str(project_id)}

    async def _require_project(project_id: UUID) -> None:
        """404 unless `project_id` names a project that exists.

        Checked before touching the corpus so that "no such project" and "that
        project has no sources" stay different answers. Without it an unknown
        id would list empty and read 404, which reads as a project that exists
        and happens to be bare -- and the caller's next move (store something)
        would be the wrong one.
        """
        try:
            state = await service.project_state(project_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no project {project_id}") from error
        if state.status == "new":
            raise HTTPException(status_code=404, detail=f"no project {project_id}")

    @app.get("/api/projects/{project_id}/workflow")
    async def get_workflow(project_id: UUID):
        """Which workflow this project runs, and the stage it is at."""
        await _require_project(project_id)
        return _workflow_of(await service.project_state(project_id))

    @app.post("/api/projects/{project_id}/workflow")
    async def select_workflow(project_id: UUID, body: WorkflowChoice):
        """Bind a project to a preset. Once only -- a second is the domain's 409.

        Goes through the aggregate the way `create_project` does, rather than
        adding a use case to `SessionService`: there is no cross-front-end
        convention to enforce here (unlike project names, which are only
        unique because that route says so), so the one rule that exists is
        already in `decide` and reaching it directly keeps it that way.

        A re-selection is relayed with the domain's own message because that
        message names the preset already running. "Already selected" would
        leave the user knowing they cannot choose without knowing what they
        chose -- and re-selection is refused precisely because a run's audit
        trail is gated by one preset's stage list, so what that list is is the
        first thing they need.
        """
        await _require_project(project_id)
        preset = PRESETS.get(body.preset_id)
        if preset is None:
            raise HTTPException(
                status_code=404,
                detail=f"no workflow {body.preset_id!r}; try one of {', '.join(PRESETS)}",
            )
        project = await service.projects.load(project_id)
        try:
            project.execute(SelectWorkflow(preset=preset))
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await service.projects.save(project)
        return _workflow_of(project.state)

    @app.get("/api/projects/{project_id}/course")
    async def get_course(project_id: UUID):
        """The whole run: every stage of the preset, and every artifact it owes.

        409 rather than 404 when no workflow is selected. The project exists
        and the request was well formed; what is missing is a choice nobody has
        made yet, and the fix is to select a preset rather than to look
        somewhere else. A 404 would say the course is not here, which reads as
        "you have the wrong project".

        A preset the project names but this build does not ship is a 409 too,
        with the id in the message: there is no stage list to build a rail
        from, and the id is the only thing that lets anyone work out why.
        """
        await _require_project(project_id)
        state = await service.project_state(project_id)
        if state.preset_id is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    "this project runs no workflow, so there is no course to show; "
                    f"select one of {', '.join(PRESETS)} first"
                ),
            )
        preset = PRESETS.get(state.preset_id)
        if preset is None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"this project runs workflow {state.preset_id!r}, which this "
                    f"build does not ship; its stage list is unknown here"
                ),
            )
        files = await service.project_files(project_id)
        return course_view(
            course_progress(preset, state, files),
            project_name=state.name,
            holding_session_id=state.active_session_id,
        )

    def _reader(project_id: UUID) -> ProjectCorpusReader:
        """This project's corpus, through the same port the agent's tools use.

        Built per request rather than held, because it is two attributes over
        a shared runner and binding the project is the entire point -- a
        long-lived one would have to take the project as an argument again,
        which is what the port refuses so that no caller can read another
        project's sources.

        503 rather than 404 when nothing was wired: an application assembled
        without a corpus read model is a valid thing to serve (as with
        `approvals` and `activity`), and the caller needs to know the server
        cannot answer rather than that the project has nothing.

        `blob_store` is checked alongside `corpus` rather than defaulted to
        something that opens on first use: `ProjectCorpusReader` now needs one
        for `read_media`, and a build that wired a corpus read model but no
        blob store is exactly as unable to answer as one that wired neither --
        the 503 is honest about that rather than pretending media reads are
        wired when only text ones are.
        """
        if corpus is None or blob_store is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        return ProjectCorpusReader(corpus, project_id, blob_store)

    def _editor() -> CorpusEditor:
        """The corpus's write side, or the same 503 `_reader` answers.

        A project without a corpus read model is a valid thing to serve, so
        this is a refusal rather than a construction failure -- see `_reader`,
        which draws the same line for reading.
        """
        if editor is None:
            raise HTTPException(status_code=503, detail="no corpus is configured")
        return editor

    class NewSource(BaseModel):
        source_id: str
        text: str
        uri: str | None = None
        title: str | None = None
        note: str | None = None
        published_at: str | None = None

    class SourceEdit(BaseModel):
        """Every field optional, and `None` means "leave it alone".

        There is deliberately no way to clear a field back to null through
        this: distinguishing "unset" from "set to null" needs a sentinel, and
        the console has no control that asks for it. A caller that wants an
        empty title sends "".
        """

        text: str | None = None
        uri: str | None = None
        title: str | None = None
        note: str | None = None
        published_at: str | None = None

    class DropReason(BaseModel):
        reason: str

    @app.post("/api/projects/{project_id}/sources", status_code=201)
    async def upload_source(project_id: UUID, body: NewSource):
        """Store a document a person is holding, rather than one an agent found.

        Every other way into this corpus is an agent path -- `remember`,
        `remember_page`, the automatic keep on `fetch` -- and this is the
        first that is not.
        """
        await _require_project(project_id)
        try:
            await _editor().store(
                project_id,
                body.source_id,
                body.text,
                uri=body.uri,
                title=body.title,
                note=body.note,
                published_at=body.published_at,
            )
        except DocumentExists as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except KnowledgeError as error:
            # The blank-id refusal and the length cap, both `store_source`'s.
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await _source_row(project_id, body.source_id)

    @app.post("/api/projects/{project_id}/sources/media", status_code=201)
    async def upload_media(
        project_id: UUID,
        file: Annotated[UploadFile, File()],
        source_id: Annotated[str | None, Form()] = None,
        uri: Annotated[str | None, Form()] = None,
        title: Annotated[str | None, Form()] = None,
        note: Annotated[str | None, Form()] = None,
        published_at: Annotated[str | None, Form()] = None,
    ):
        """Store bytes a person is holding: a recording, a scan, a slide deck.

        The media twin of `upload_source`, and multipart rather than JSON for
        the reason the ceiling exists: a base64 field would put a gigabyte
        through a JSON parser and hold it in memory twice over. The bytes go
        to the blob store a megabyte at a time and never accumulate here.

        `source_id` defaults to the filename, because a person uploading
        `keynote.mp4` has already named it and asking twice is friction with
        no payoff. Unlike `upload_source` there is no 409 on a repeat: a
        second store under the same id is a *revision* of a media source, and
        `Corpus.decide` has the only opinion on that -- see
        `CorpusEditor.store_media`, which declines to re-pay the check.

        **Declared ahead of `/sources/{source_id}/drop` and its siblings for
        the reason `extract_all_sources` gives**: FastAPI matches in
        declaration order, and while `media` and `{source_id}/drop` do not
        currently collide, the neighbourhood is one where they have twice.
        """
        await _require_project(project_id)
        head = await file.read(UPLOAD_CHUNK_BYTES)
        media_type = file.content_type
        if not media_type or media_type == "application/octet-stream":
            # Browsers send `application/octet-stream` for plenty of things
            # that are not: it is what they fall back to when the operating
            # system has no association for the extension, which on a bare
            # machine includes `.mkv` and `.webm`. Storing that verbatim would
            # make the content route answer with a type no `<video>` will
            # play, and the record would carry the wrong answer forever --
            # nothing re-sniffs a stored blob.
            media_type = _sniff_media_type(head) or media_type or "application/octet-stream"

        async def chunks() -> AsyncIterator[bytes]:
            """The upload, bounded. See `MAX_UPLOAD_BYTES` on why it raises
            from inside the loop rather than reporting a total afterwards."""
            total = 0
            part = head
            while part:
                total += len(part)
                if total > MAX_UPLOAD_BYTES:
                    raise _UploadTooLarge(total)
                yield part
                part = await file.read(UPLOAD_CHUNK_BYTES)

        try:
            record = await _editor().store_media(
                project_id,
                source_id or file.filename or "upload",
                chunks(),
                media_type,
                uri=uri,
                title=title,
                note=note,
                published_at=published_at,
            )
        except _UploadTooLarge as error:
            raise HTTPException(
                status_code=413,
                detail=f"upload exceeds {MAX_UPLOAD_BYTES} bytes",
            ) from error
        except CommandRejectedError as error:
            # `decide`'s one refusal for this command: a `source_id` that
            # already holds *text*, which `_kind_of` will not let media take
            # over. There is no blank-id refusal on this path -- that check
            # lives in `RedstringKnowledge.store_source`, which media
            # deliberately does not go through (`corpus_editing.py`'s module
            # docstring) -- so a form field of `"   "` is stored verbatim as a
            # whitespace id. A literal `""` is unreachable: the fallback chain
            # above takes the filename and then `"upload"`.
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _source_row(project_id, record.source_id)

    @app.get("/api/projects/{project_id}/sources/{source_id}/content")
    async def read_source_content(project_id: UUID, source_id: str, request: Request):
        """A media source's actual bytes, whole or in ranges.

        Three refusals, and the distinction between the first two is the point:

        - **404** when `read_media` answers `None`. Either no such id, or an
          id that holds *text* -- a text source's bytes live in the event log,
          not the blob store, so this is the wrong route for it rather than a
          thing that has gone missing.
        - **410** when the record is here and its blob is not. A dangling
          reference is a real and different state, and an operator told 404
          goes looking for an ingest that never happened instead of for bytes
          that went away.
        - **416** for a range starting past the end, with `Content-Range:
          bytes */<length>` so the client can correct itself in one round trip.

        Range support lands here rather than with the citation slice that
        needs it, because without it a `<video>` will not seek: Chromium
        treats a response with no `Accept-Ranges` as unseekable and downloads
        the whole file before it will play at all. The alternative was
        shipping a player that stalls on a two-hour recording and calling it
        a later task.

        `include_dropped=True`, matching `read_source`: the console lists
        dropped rows and lets you open one, and refusing to play the recording
        somebody is deciding whether to restore is refusing at exactly the
        wrong moment.
        """
        await _require_project(project_id)
        handle = await _reader(project_id).read_media(source_id, include_dropped=True)
        if handle is None:
            raise HTTPException(
                status_code=404,
                detail=f"no media source {source_id!r} in project {project_id}",
            )
        if handle.stat is None:
            raise HTTPException(
                status_code=410,
                detail=f"the bytes for {source_id!r} are no longer stored",
            )
        total = handle.stat.byte_count
        headers = {"Accept-Ranges": "bytes"}
        requested = request.headers.get("range")
        span = None
        if requested:
            try:
                span = _parse_byte_range(requested, total)
            except _RangeNotSatisfiable as error:
                raise HTTPException(
                    status_code=416,
                    detail=str(error),
                    headers={"Content-Range": f"bytes */{total}", "Accept-Ranges": "bytes"},
                ) from error
        if span is None:
            headers["Content-Length"] = str(total)
            return StreamingResponse(
                handle.open(), media_type=handle.record.media_type, headers=headers
            )
        start, end = span
        headers["Content-Range"] = f"bytes {start}-{end}/{total}"
        headers["Content-Length"] = str(end - start + 1)
        return StreamingResponse(
            # `open(start)` seeks; `_first_bytes` trims the tail. Reading from
            # zero and discarding would answer identically and cost the whole
            # prefix -- see `BlobStorePort.open`.
            _first_bytes(handle.open(start), end - start + 1),
            status_code=206,
            media_type=handle.record.media_type,
            headers=headers,
        )

    @app.post("/api/projects/{project_id}/sources/{source_id}/drop")
    async def drop_source(project_id: UUID, source_id: str, body: DropReason):
        await _require_project(project_id)
        try:
            await _editor().drop(project_id, source_id, body.reason)
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except CommandRejectedError as error:
            # The blank reason and the double drop, both the aggregate's.
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    @app.post("/api/projects/{project_id}/sources/{source_id}/restore")
    async def restore_source(project_id: UUID, source_id: str):
        await _require_project(project_id)
        try:
            await _editor().restore(project_id, source_id)
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NotDropped as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    @app.patch("/api/projects/{project_id}/sources/{source_id}")
    async def revise_source(project_id: UUID, source_id: str, body: SourceEdit):
        await _require_project(project_id)
        try:
            await _editor().revise(
                project_id,
                source_id,
                text=body.text,
                uri=body.uri,
                title=body.title,
                note=body.note,
                published_at=body.published_at,
            )
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except KnowledgeError as error:
            # Two guards reach here, and `decide` is neither of them. `_store`'s
            # length cap: missing until review, when a PATCH over the cap was an
            # unhandled exception and a 500, where `upload_source` already
            # answered 400 for the same error. And `revise`'s refusal of a
            # `text` against a media id -- that one has no other handler, so
            # `test_patching_text_onto_a_media_source_is_refused` fails here
            # rather than at the editor if this branch narrows.
            raise HTTPException(status_code=400, detail=str(error)) from error
        return await _source_row(project_id, source_id)

    async def _source_row(project_id: UUID, source_id: str) -> dict[str, Any]:
        """The written document, read back through the listing.

        Read back rather than composed from the request, so the answer is what
        the corpus holds rather than what the caller sent -- `sha256` and
        `char_count` are computed in the fold and a client that trusted its own
        echo would render a digest nothing verified.
        """
        for listing in await _reader(project_id).list_sources(include_dropped=True):
            if listing.record.source_id == source_id:
                return source_view(listing)
        raise HTTPException(status_code=404, detail=f"no document {source_id!r}")

    @app.post("/api/projects/{project_id}/sources/extract")
    async def extract_all_sources(project_id: UUID):
        """Queue every stored document that has no graph. 202, none of it has run.

        **This whole block is registered ahead of the `/sources` reads, and has
        to stay there.** FastAPI matches in declaration order, so a literal
        segment that could also be a `{source_id}` must be declared first --
        the reason `dispatch_topic` gives. Two collisions are live here, and
        the second was found by a test rather than by reading: `extract` would
        be read as a `source_id` by `/sources/{source_id}/extract`, and
        `extraction-queue` would be read as one by `GET
        /sources/{source_id}`, which answered 404 "no such source" for the
        catch-up route until these moved above it.

        `queued` counts what this press actually took on, not what was asked
        for -- the queue refuses a document it already holds, so pressing this
        twice while the first pass drains answers 0 the second time rather
        than claiming to have started the same work again.

        The set is computed here rather than inside the queue because it is a
        corpus question, and the queue deliberately knows nothing about
        corpora. It is computed once, at press time: a document extracted by
        something else while this queue drains is still in the deque and will
        be extracted again. Harmless -- extraction is idempotent in effect --
        and cheaper than re-asking the projection before every item.
        """
        if extractor is None or extract_queue is None:
            raise HTTPException(
                status_code=503, detail="document extraction is not configured"
            )
        await _require_project(project_id)
        pending = await extractor.unextracted(project_id)
        queued = [
            source_id
            for source_id in pending
            if extract_queue.start(
                project_id, source_id, _extraction_of(project_id, source_id)
            )
        ]
        return JSONResponse(
            status_code=202,
            content={"queued": len(queued), "source_ids": queued},
        )

    @app.post("/api/projects/{project_id}/sources/reindex")
    async def reindex_sources(project_id: UUID):
        """Chunk every stored document again, and say how many. 200, it has run.

        Registered inside the literal-segment block above for that block's
        reason: `reindex` would otherwise be read as a `{source_id}`.

        200 and not 202, unlike its `extract` neighbours: chunking makes no
        model call, so there is nothing to queue and the work is finished when
        this answers. See `DocumentExtractor.reindex` for what that costs on a
        large corpus and why the queue was not worth building anyway.

        The repair this exists for is a corpus stored before chunk indexing
        shipped: it has no `DocumentChunked` events, so replay leaves its chunk
        store empty and every entity reads as unmentioned.
        `/api/corpus/rebuild` does not help -- it rebuilds the corpus documents
        table, which is derived from the log, where these chunks are not.

        Safe at any time: `index` is idempotent through the adapter's event
        store, so a second run on an unchanged corpus rewrites nothing.
        """
        if extractor is None:
            raise HTTPException(
                status_code=503, detail="document extraction is not configured"
            )
        await _require_project(project_id)
        return {"indexed": await extractor.reindex(project_id)}

    @app.post("/api/projects/{project_id}/sources/{source_id}/extract")
    async def extract_source(project_id: UUID, source_id: str):
        """Queue one stored document for extraction. 202, because it has not run.

        202 with `queued` rather than 409 when the project is busy, for
        `dispatch_topic`'s reason: this backs a control on every document row,
        and a control that usually refuses is a control people stop pressing.

        The document is read here -- not left for the queue -- so an unknown
        `source_id` is a 404 the caller can see. Deferred, it would fail
        asynchronously against a row that does not exist.

        `queued: false` is a 202 rather than a 409: the document *is* going to
        be extracted, because it is already in the queue or already running,
        which is what the caller wanted. Saying so plainly lets the client
        avoid claiming it started something it did not.
        """
        if extractor is None or extract_queue is None:
            raise HTTPException(
                status_code=503, detail="document extraction is not configured"
            )
        await _require_project(project_id)
        if await _reader(project_id).read_document(source_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        queued = extract_queue.start(
            project_id, source_id, _extraction_of(project_id, source_id)
        )
        return JSONResponse(
            status_code=202, content={"queued": queued, "source_id": source_id}
        )

    def _extraction_of(project_id: UUID, source_id: str):
        """A factory the queue can await later, closing over nothing mutable.

        Deliberately not the coroutine itself: an item that waits in the deque
        for a minute would otherwise be a live coroutine nobody has awaited,
        and one dropped by `cancel` would be one nobody ever will.
        """
        assert extractor is not None  # both call sites guard above

        async def run():
            return await extractor.extract(project_id, source_id)

        return run

    @app.get("/api/projects/{project_id}/sources/extraction-queue")
    async def get_extraction_queue(project_id: UUID):
        """What is extracting, what is waiting, and how each document's last one went.

        The catch-up read the queue cannot do without, and -- unlike
        `/dispatch` -- the *only* read: this queue publishes no frames, because
        `ExtractionActivity` already carries the running item's progress over
        the live feed. See `extraction_queue.py` on what that leaves stale.

        Three empty answers rather than a 503 when unwired, matching
        `get_dispatch`: a build with no queue has nothing extracting, which is
        a state and not an error. The POSTs above are where a client learns the
        feature is absent.
        """
        await _require_project(project_id)
        if extract_queue is None:
            return {"running": None, "queued": [], "finished": []}
        return {
            "running": extract_queue.current(project_id),
            "queued": list(extract_queue.queued(project_id)),
            "finished": extract_queue.finished(project_id),
        }

    @app.post("/api/projects/{project_id}/sources/extraction-queue/cancel")
    async def cancel_extraction_queue(project_id: UUID):
        """Stop the running extraction and drop everything waiting, for this project.

        Answers how many went, matching `cancel_dispatch`, so the caller can
        say "stopped 12" rather than guessing from a queue it re-reads a moment
        later.
        """
        await _require_project(project_id)
        if extract_queue is None:
            raise HTTPException(
                status_code=503, detail="document extraction is not configured"
            )
        return {"cancelled": extract_queue.cancel(project_id)}

    @app.get("/api/projects/{project_id}/sources")
    async def list_sources(project_id: UUID, include_dropped: bool = False):
        """Every source this project has stored. Metadata only, never text.

        `include_dropped` defaults to False, so the agent's own `list_sources`
        tool -- which calls the port behind this route directly, not this
        route -- is unaffected either way; the default here exists only so a
        browser doing the same request the agent's tool makes sees the same
        thing. A caller that opts in sees dropped documents too, each with
        the reason it was excluded: the corpus keeps them for that reason.
        """
        await _require_project(project_id)
        reader = _reader(project_id)
        summaries = await reader.list_sources(include_dropped=include_dropped)
        return [source_view(summary) for summary in summaries]

    @app.get("/api/projects/{project_id}/sources/{source_id}")
    async def read_source(
        project_id: UUID, source_id: str, start: int | None = None, end: int | None = None
    ):
        """One source's text, or a character range of it, with its real offsets.

        The range is clamped rather than validated: `quote` returns what the
        document actually has for the range asked, and the response reports
        those offsets. A caller guessing past the end of a document is the
        ordinary case -- it is how you page through one -- so answering with
        the last characters and honest offsets is more useful than a 422 that
        makes the caller compute the bound it was asking the server for.

        `include_dropped=True`, unlike `list_sources` above: the console lists
        dropped rows and lets you open one, and the reader is where someone
        decides whether to restore it -- refusing to show the text of the
        document being judged is refusing at exactly the wrong moment. The
        agent's own `read_source` tool goes through `ProjectCorpusReader` on a
        different path and keeps the default, so its view of the corpus is
        unchanged.
        """
        reader = _reader(project_id)
        await _require_project(project_id)
        document = await reader.read_document(source_id, include_dropped=True)
        if document is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        text = document.text
        span = quote(text, start or 0, len(text) if end is None else end)
        return source_text_view(document, span)

    def _topic_reader(project_id: UUID) -> TopicReadPort:
        """This project's topics, through the port composition assembled.

        503 rather than 404 when `topics` was not wired, for the reason
        `_reader` gives: a build with no topic read model is a valid thing to
        serve, and the caller needs to know the server cannot answer rather
        than that the project has none.
        """
        if topics is None:
            raise HTTPException(status_code=503, detail="no topic read model is configured")
        return topics(project_id)

    @app.get("/api/projects/{project_id}/topics")
    async def list_topics(project_id: UUID):
        """Every topic this project tracks, ranked on nothing -- the queue does that."""
        await _require_project(project_id)
        reader = _topic_reader(project_id)
        return [topic_view(view) for view in await reader.list_topics()]

    @app.post("/api/projects/{project_id}/topics/seed")
    async def seed_topics(project_id: UUID, body: NewSeed):
        """Start one seeding turn that names this project's first topics.

        Registered ahead of `/topics/{topic_id}` below -- FastAPI matches
        routes in declaration order, and `seed` would otherwise be parsed as
        a topic id and 422 on every call.

        202, matching `start_research_run`: the turn has not finished when
        this answers, and what it hands back is the id of a run that has
        *begun*. The topics it opens arrive over the log like any other
        `open_topic` call -- a client that wants them invalidates its topic
        list on those frames rather than reading this response for them.

        503 rather than 404 when unwired, matching `_topic_reader` above:
        this build is missing configuration, not the project this id names.
        409 when a seed is already running on this project -- see
        `seeding.py`'s `SeedingActivity.start` for why it is the same
        exception `start_research_run` maps the same way.
        """
        if topic_seeder is None or seeding is None:
            raise HTTPException(status_code=503, detail="topic seeding is not configured")
        await _require_project(project_id)
        try:
            frame = seeding.start(
                project_id,
                lambda run_id: topic_seeder.seed(
                    project_id, body.subject, body.max_topics, run_id=run_id
                ),
            )
        except RunAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=seeding_view(frame))

    @app.get("/api/projects/{project_id}/topics/seed")
    async def get_seed(project_id: UUID):
        """What the running seed has done so far, and the last one's account.

        A tab that arrived mid-run, or one whose connection dropped, has no
        other way back -- see `seeding.py`'s module docstring. 200 with both
        halves `None` when nothing has run, matching `get_extraction`'s own
        reasoning: an absent seed is a state, not a missing resource.
        """
        await _require_project(project_id)
        if seeding is None:
            return {"current": None, "last": None}
        return {
            "current": seeding_view(seeding.current(project_id)),
            "last": seeding_view(seeding.last(project_id)),
        }

    @app.get("/api/projects/{project_id}/topics/{topic_id}/documents")
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
        await _require_project(project_id)
        views = await _topic_reader(project_id).list_topics()
        position = next(
            (index for index, view in enumerate(views) if view.summary.topic_id == topic_id),
            None,
        )
        if position is None:
            raise HTTPException(
                status_code=404, detail=f"no such topic in project {project_id}"
            )
        return topic_documents_view(
            topic_directory(position, views[position].summary.question),
            await service.project_files(project_id),
            await service.project_state(project_id),
        )

    @app.post("/api/projects/{project_id}/topics/{topic_id}/dispatch")
    async def dispatch_topic(
        project_id: UUID, topic_id: UUID, body: NewDispatch | None = None
    ):
        """Send an agent at one topic. 202, because it has not run when this answers.

        Registered ahead of `/topics/{topic_id}` for the reason `seed_topics`
        gives: FastAPI matches in declaration order.

        **202 with `queued`, never 409.** This is the one place this API
        deliberately differs from `seed_topics` and `start_research_run`, and
        `dispatch.py`'s module docstring carries the argument: those two back a
        control that appears once on a page, where refusing a second press is
        correct. This one backs a control on every topic row, where refusing
        would be the answer to nearly every second press.

        The topic is resolved here rather than left to the queue so a bad id
        comes back as a 404 the caller can see. Enqueued and failed
        asynchronously, it would surface as a failure chip on a row that does
        not exist -- which is to say, nowhere.

        503 rather than 404 when unwired, matching every other optional
        dependency here: this build is missing configuration, not the project.
        """
        if dispatcher is None or dispatch is None:
            raise HTTPException(status_code=503, detail="topic dispatch is not configured")
        await _require_project(project_id)

        action = (body or NewDispatch()).action
        if action not in DISPATCH_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"no dispatch action {action!r}; this build offers "
                    f"{', '.join(sorted(DISPATCH_ACTIONS))}"
                ),
            )

        detail = await _topic_reader(project_id).read_topic(topic_id)
        if detail is None:
            raise HTTPException(
                status_code=404, detail=f"no such topic in project {project_id}"
            )

        frame = dispatch.start(
            project_id,
            topic_id,
            action,
            lambda dispatch_id: dispatcher.dispatch(
                project_id, topic_id, action, dispatch_id=dispatch_id
            ),
            question=detail.view.summary.question,
        )
        return JSONResponse(status_code=202, content=dispatch_view(frame))

    @app.get("/api/projects/{project_id}/dispatch")
    async def get_dispatch(project_id: UUID):
        """What is running, what is waiting, and how each topic's last one went.

        The catch-up read these frames cannot do without: they carry no feed
        position, so `Last-Event-ID` cannot replay them and a reconnecting tab
        would otherwise be unable to tell "still running" from "finished
        before I got here".

        Three empty answers rather than a 503 when unwired, matching
        `get_seed`: a build with no dispatch queue has nothing running, which
        is a state and not an error. The POST above is where a client learns
        the feature is absent.
        """
        await _require_project(project_id)
        if dispatch is None:
            return {"running": None, "queued": [], "finished": []}
        return {
            "running": dispatch_view(dispatch.current(project_id)),
            "queued": [dispatch_view(frame) for frame in dispatch.queued(project_id)],
            "finished": [dispatch_view(frame) for frame in dispatch.finished(project_id)],
        }

    @app.post("/api/projects/{project_id}/dispatch/cancel")
    async def cancel_dispatch(project_id: UUID):
        """Stop what is running and drop everything waiting, for this project.

        Per project rather than per dispatch, matching `ResearchSupervisor`'s
        own cancel. Answers how many went so the caller can say "stopped 3"
        rather than guessing from a queue it re-reads a moment later.
        """
        await _require_project(project_id)
        if dispatch is None:
            raise HTTPException(status_code=503, detail="topic dispatch is not configured")
        return {"cancelled": dispatch.cancel(project_id)}

    @app.get("/api/projects/{project_id}/topics/{topic_id}")
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
        await _require_project(project_id)
        detail = await reader.read_topic(topic_id)
        if detail is None:
            raise HTTPException(
                status_code=404, detail=f"no such topic in project {project_id}"
            )
        return topic_detail_view(detail)

    def _topic_repo() -> AggregateRepository[Topic]:
        """The `Topic` aggregate repository, for routes that change a topic.

        503 rather than 404 when `topic_repository` was not wired, matching
        `_topic_reader`: a build with no write model configured is a valid
        thing to serve read-only, and the caller needs to know the server
        cannot answer rather than that the topic is missing.
        """
        if topic_repository is None:
            raise HTTPException(status_code=503, detail="no topic write model is configured")
        return topic_repository

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
        await _require_project(project_id)
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

    @app.post("/api/projects/{project_id}/topics/{topic_id}/status")
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

    @app.post("/api/projects/{project_id}/topics/{topic_id}/sub-questions")
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

    @app.post("/api/projects/{project_id}/topics/{topic_id}/sub-questions/{key}/resolve")
    async def resolve_sub_question(
        project_id: UUID, topic_id: UUID, key: str, body: SubQuestionAnswer
    ):
        """Answer a tracked sub-question. Human-only, for the same reason above."""
        return await _change_topic(
            project_id, topic_id, ResolveSubQuestion(key=key, answer=body.answer)
        )

    async def _graph_reader(project_id: UUID) -> GraphReadPort:
        """This project's `GraphReadPort`, over the store `graphs` already owns.

        503 rather than 404 when `graphs` was not wired, for the reason
        `_reader` gives: a build with no graph read model is a valid thing to
        serve, and the caller needs to know the server cannot answer rather
        than that the project has no graph.

        `async`, unlike `_reader` and `_topic_reader`: those wrap an
        already-open corpus and topic repository, but the store behind a
        `ProjectGraphReader` is opened on demand by `graphs.open`, which is
        itself a coroutine -- there is no synchronous constructor to call
        here. Building it per request rather than caching it is safe because
        `graphs` is the single owner of the store underneath (see
        `ProjectGraphs`): a second call today gets back the same store a
        first call already opened, not a stale second one.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        return ProjectGraphReader(project_id=project_id, store=store)

    @app.get("/api/projects/{project_id}/graph")
    async def read_graph(project_id: UUID, limit: int = MAX_GRAPH_NODES):
        """This project's whole graph, so a browser has something to draw
        before the reader knows what to search for.

        `limit` is clamped by the port rather than refused here, which is the
        opposite of what `neighborhood` does with `depth` -- the two asks are
        different. A depth past the bound is a request for a *shape* of answer
        the server will not produce, and the caller needs to know its question
        was the wrong one. A limit past the bound is a request for as much as
        possible, and "as much as possible" is precisely what the clamp
        returns; `truncated` in the body already says the graph did not fit,
        so there is nothing a 422 would tell the caller that the answer does
        not.
        """
        await _require_project(project_id)
        reader = await _graph_reader(project_id)
        return graph_view(await reader.whole(limit=limit))

    @app.get("/api/projects/{project_id}/graph/entities")
    async def list_graph_entities(
        project_id: UUID,
        name: str | None = None,
        entity_type: str | None = None,
        limit: int = 100,
        after: UUID | None = None,
    ):
        """Entry points into this project's graph: entities matching every filter given.

        `after` is typed as `UUID | None` rather than `str | None` so FastAPI
        rejects a malformed cursor with a 422 before it ever reaches the
        reader -- `neighborhood`'s `entity_id` handles the identical problem
        with a try/except because it takes a path segment FastAPI cannot
        type-check for it; a query parameter does not need that fallback.
        """
        await _require_project(project_id)
        reader = await _graph_reader(project_id)
        page = await reader.find_entities(
            name=name,
            entity_type=entity_type,
            limit=limit,
            after=str(after) if after is not None else None,
        )
        return entity_page_view(page)

    @app.get("/api/projects/{project_id}/graph/entities/{entity_id}/neighborhood")
    async def read_graph_neighborhood(project_id: UUID, entity_id: str, depth: int = 1):
        """`entity_id` and what lies within `depth` hops of it, fully wired.

        A `depth` above `MAX_NEIGHBORHOOD_DEPTH` is refused with a 422 here,
        even though `GraphReadPort.neighborhood` clamps the same bound on its
        own -- see that port's docstring. The two are not redundant: the
        port's clamp protects every present and future in-process caller from
        an oversized traversal regardless of what sits above it, while this
        check exists for the one caller that can be told it made a mistake.
        Clamping silently here would spend the request answering a question
        nobody asked instead of saying which question was too big.
        """
        if depth > MAX_NEIGHBORHOOD_DEPTH:
            raise HTTPException(
                status_code=422,
                detail=f"depth {depth} exceeds the maximum of {MAX_NEIGHBORHOOD_DEPTH}",
            )
        await _require_project(project_id)
        reader = await _graph_reader(project_id)
        hood = await reader.neighborhood(entity_id, depth=depth)
        if hood is None:
            raise HTTPException(
                status_code=404, detail=f"no such entity in project {project_id}"
            )
        return neighborhood_view(hood)

    async def _usage_reader(project_id: UUID) -> UsageReader:
        """This project's `UsageReadPort`, over the graph and chunk stores
        `graphs` already owns.

        503 rather than 404 when either store is unwired, matching
        `_graph_reader`: a build with chunking off (`AGENT_CHUNK_STORE=none`)
        is a valid thing to serve, and the caller needs to know the server
        cannot answer rather than that the entity has no usages.

        `open` first, the same call `_graph_reader` makes: it is what builds
        this project's chunk store on first use (see `ProjectGraphs.open`),
        and it is idempotent, so a usages request that lands before any graph
        route has still opened the project gets a store rather than a 503
        that only means "nobody happened to ask for the graph yet".
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        chunk_store = graphs.chunks(project_id)
        if chunk_store is None:
            raise HTTPException(status_code=503, detail="no chunk store is configured")
        return UsageReader(store, chunk_store, project_id)

    @app.get("/api/projects/{project_id}/graph/entities/{entity_id}/usages")
    async def read_graph_usages(project_id: UUID, entity_id: UUID, limit: int = MAX_USAGES):
        """Passages naming `entity_id`, best matches first.

        A separate endpoint from the entity definition that follows in a
        later task, not a field folded into the same response: a definition
        may cost an LLM call, usages are a cheap deterministic BM25 lookup
        over an already-open chunk store, and a combined endpoint would make
        every caller wait for the slow half to get the fast one.

        `limit` above `MAX_USAGES` is refused with 422 rather than clamped,
        unlike `whole`'s `limit` -- see `MAX_USAGES`'s docstring for why the
        two asks are different.
        """
        if limit > MAX_USAGES:
            raise HTTPException(
                status_code=422,
                detail=f"limit {limit} exceeds the maximum of {MAX_USAGES}",
            )
        await _require_project(project_id)
        reader = await _usage_reader(project_id)
        return usages_view(await reader.usages(entity_id, limit=limit))

    @app.get("/api/projects/{project_id}/graph/entities/{entity_id}/definition")
    async def read_graph_definition(project_id: UUID, entity_id: UUID):
        """`entity_id`'s grounded definition, generated on first ask and
        cached from then on -- see `DefinitionService.define`.

        **503 only when nothing is wired.** `definitions` is now supplied by
        the composition root (`Application.definition_readers`), so the
        503 below means a caller built this app without it -- a test fixture,
        or a build with no chunk store, which is the second 503 further down.
        It is a factory rather than one service because the cache, the graph
        and the chunk store behind it are all bound to `project_id`; see
        `DefinitionReaders`.

        **200 with a null `text`, not 404, when `define` returns `None`.**
        `entity_id` is a real node in the graph; it is merely undefinable
        today because nothing was found to ground a definition in (no
        passages, no edges -- see `DefinitionService.define`'s docstring). A
        404 would tell the caller the entity itself does not exist, which is
        a different and wrong statement, and one the browser would act on by
        treating the node as gone rather than merely lacking a summary. Do
        not "fix" this to a 404 without re-reading that reasoning -- it is
        the deliberate case a later reader is likely to trip on, which is why
        it is spelled out here as well as in the service.

        No `force=True` here -- this route only reads. Regeneration is a
        separate concern (Task 12's retrigger), not something a GET should
        cause as a side effect the caller did not ask for.

        **Synchronous, deliberately, unlike extraction.** `ExtractionQueue`
        exists because extraction is long-running and a request that loses a
        queued extraction loses an intention the caller cannot easily
        re-express (BACKLOG B62). A definition is seconds of work, produces
        the same answer from the same inputs, and a failed or interrupted
        request costs the caller nothing but a second click -- so the entire
        retry story is "click again", and a durable queue here would be
        machinery bought for a payoff nobody would notice.
        """
        await _require_project(project_id)
        if definitions is None:
            raise HTTPException(status_code=503, detail="no definition service is configured")
        service = await definitions(project_id)
        if service is None:
            # A build with no chunk store cannot ground a definition in
            # passages, and a definition citing nothing is refused anyway --
            # see `definition_reader` in `composition.py`. The same 503 the
            # usages route above answers for the same absence.
            raise HTTPException(status_code=503, detail="no chunk store is configured")
        return definition_view(await service.define(entity_id))

    def _timeline_interval(from_: str | None, to: str | None) -> TimelineInterval | None:
        """`from`/`to` as an interval, or `None` when neither was given.

        `None` rather than `TimelineInterval(None, None)` for the empty case so
        the adapter passes `interval=None` to redstring and takes its
        no-window path, instead of an all-`None` `Bounds` whose behaviour is
        the library's to decide rather than ours.
        """
        if from_ is None and to is None:
            return None
        return TimelineInterval(start=_instant("from", from_), end=_instant("to", to))

    def _instant(name: str, raw: str | None) -> datetime | None:
        """One ISO query parameter as a datetime, 422 if it will not parse.

        `fromisoformat` and not `dateutil`: the client this serves is the
        browser, which produces `toISOString()` output, and accepting looser
        spellings would make the set of dates that work depend on which parser
        happened to be installed.
        """
        if raw is None:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            raise HTTPException(
                status_code=422, detail=f"{name}={raw!r} is not an ISO instant"
            ) from None

    async def _timeline_reader(project_id: UUID) -> TimelineReadPort:
        """This project's `TimelineReadPort`, over the store `graphs` owns.

        503 rather than 404 when `graphs` was not wired, matching
        `_graph_reader`: a build with no graph read model is a valid thing to
        serve, and the caller needs to know the server cannot answer rather
        than that the project has no timeline.

        Opens through `graphs` rather than holding its own store, so the
        timeline and the graph read the *same* store rather than two folds of
        one log that could drift apart between tabs.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        return ProjectTimelineReader(project_id=project_id, store=store)

    @app.get("/api/projects/{project_id}/timeline")
    async def read_timeline(
        project_id: UUID,
        entity_type: str | None = None,
        # `from` is a Python keyword, so the parameter is named `from_` and
        # aliased back. FastAPI's `Query` alias is the only way to spell a
        # reserved word in a signature; renaming the *wire* parameter to
        # something legal was rejected because the spec names `from`/`to` and a
        # query string is a contract with anyone holding a bookmark.
        from_: str | None = Query(default=None, alias="from"),
        to: str | None = None,
        limit: int = MAX_TIMELINE_BANDS,
    ):
        """This project's dated entities, ordered, for drawing on an axis.

        `from`/`to` are ISO instants bounding a half-open `[from, to)` window;
        either may be omitted for an open end, and omitting both is the whole
        timeline. Strings rather than a `datetime` annotation so an
        unparseable value is *this* route's 422 with a message naming which
        parameter was wrong -- FastAPI would otherwise answer its own 422
        naming a validation error the caller has to decode. It is a 422 and
        not a silent fall-back to "no window", because a client that mistyped
        a date and got the entire timeline back has been answered a different
        question than it asked and has no way to tell.

        Project-level rather than under `/graph/` because it is not a graph
        shape: nothing in the response has a source, a target or an edge type,
        and nesting it there would suggest a client could ask for one and be
        given the other.

        `limit` is clamped by the port rather than refused here, the same call
        `read_graph` makes and for the same reason -- "as much as possible" is
        precisely what the clamp returns, and `truncated` in the body already
        says it did not all fit.
        """
        await _require_project(project_id)
        interval = _timeline_interval(from_, to)
        reader = await _timeline_reader(project_id)
        return timeline_view(
            await reader.timeline(entity_type=entity_type, interval=interval, limit=limit)
        )

    @app.post("/api/sessions/{session_id}/release")
    async def release_session(session_id: UUID):
        """Finish with this session, handing its work back to its project.

        The counterpart the web app never had. Releasing is not tidying up
        after yourself: `release_project` is what advances the project's tip
        to this session's latest event, so it is also the *only* way work
        done here reaches the next session in the project. Without it a
        project stays held by a session nobody is driving, and its filesystem
        stays frozen at whatever the previous release left behind.

        Detaching is conditional on this being the attached project, because
        one process serves many browser sessions: releasing session A must
        not pull the graph out from under a turn running in session B.
        """
        session = await _load(session_id)
        project_id = session.state.project_id
        if project_id is None:
            return {"released": False, "project_id": None}
        if turns.is_running(session_id):
            raise HTTPException(
                status_code=409,
                detail="a turn is still running on this session; cancel it first",
            )
        await service.release_project(session_id)
        if service.attached_project_id == project_id:
            await service.detach_project()
        return {"released": True, "project_id": str(project_id)}

    @app.post("/api/projects/{project_id}/join")
    async def join_project(project_id: UUID, body: JoinOptions | None = None):
        """Start a session that inherits `project_id`'s filesystem, and attach its graph.

        Goes through `SessionService.start_in_project` -- the same use case
        the REPL's `/project use` calls -- so joining is decided in exactly
        one place: the `Project` aggregate. A project already held raises
        `CommandRejectedError` naming the holding session, which this maps to
        409 rather than letting it become an unhandled 500.

        Attachment design: unlike the REPL, this process serves many browser
        sessions at once through one `TurnSupervisor` and (if wired) one
        `KnowledgeAttachment`, so there is no single "current session" whose
        project should stay attached. A per-session attachment map would
        preserve REPL-like isolation between browser tabs, but this app is a
        local single-user tool -- the spec never asks it to serve concurrent
        untrusted users -- so the simpler answer is taken: attach here,
        accept that the most recent join wins process-wide, and say so
        plainly rather than build isolation nothing asked for. A second tab
        joining a different project will change the tools the first tab's
        turns run with; that is a known, accepted limitation of this design,
        not an oversight.

        Taking over: a project held by a session the user has finished with
        is the ordinary case, not an error -- "end this and start fresh" is
        the single most common thing to want from a project, and before
        `take_over` the web app could only report the 409 and offer no way
        out of it. It is spelled as an explicit flag rather than done
        silently because releasing the holder advances the tip, which is a
        write to somebody else's session; a plain join stays a plain join.
        """
        if body is not None and body.take_over:
            state = await service.project_state(project_id)
            if state.active_session_id is not None:
                if turns.is_running(state.active_session_id):
                    raise HTTPException(
                        status_code=409,
                        detail="the holding session has a turn running; cancel it first",
                    )
                await service.release_project(state.active_session_id)
        try:
            session_id = await service.start_in_project(project_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        try:
            await service.attach_project(project_id)
        except Exception as error:  # noqa: BLE001 -- report, do not fail the join
            return {
                "id": str(session_id),
                "project_id": str(project_id),
                "warning": str(error),
            }
        return {"id": str(session_id), "project_id": str(project_id), "warning": None}

    @app.post("/api/projects/{project_id}/auto-research")
    async def start_research_run(project_id: UUID, body: NewRun | None = None):
        """Start an autonomous run over this project's topic queue.

        202 rather than 200, and the reason is the whole shape of this route:
        the work has not been done when it answers. What it returns is the id
        of a run that has *begun*, which is enough to fold its stream, watch
        its rounds arrive on `/api/stream`, and stop it.

        Off unless `AGENT_RESEARCH_RUN` says otherwise, and absent rather
        than refusing when it is off -- 404, not 403, because a route that
        answers 403 has told an unauthenticated caller that there is an
        unattended research loop on the other side of this port. See
        `config.research_run_over_http`.

        A session is required and one is started by default, because a run's
        rounds are turns and a turn needs a session. Starting one goes through
        `start_in_project`, so a project already held answers 409 naming its
        holder -- the same answer joining gives, from the same aggregate.
        Attaching matters more here than anywhere else: without it the agent
        has no topic tools, and every round of the run would be a turn that
        could not record anything, which the driver would correctly read as a
        project with nothing left to find.
        """
        if research is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "autonomous runs are not enabled on this instance; "
                    "set AGENT_RESEARCH_RUN=1 to enable them"
                ),
            )
        await _require_project(project_id)
        options = body or NewRun()
        try:
            # Checked before anything is created: a half-grant is a mistake
            # in the request, not a state this instance should ever hold --
            # no session started, no project held, nothing to unwind.
            fetch_hosts, fetch_budget = options.fetch_grant()
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            session_id = await service.start_in_project(project_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        try:
            await service.attach_project(project_id)
        except Exception as error:
            raise HTTPException(
                status_code=503,
                detail=f"the project's knowledge graph would not open: {error}",
            ) from error
        try:
            run = research.start(
                project_id,
                session_id,
                budget=options.budget(),
                fetch_hosts=fetch_hosts,
                fetch_budget=fetch_budget,
                # This route made the session, so this route puts it away.
                # Two things go wrong without it, and the second is the worse
                # one: the project stays held, so the *next* run is refused by
                # a session nobody is driving -- and releasing is what advances
                # the project's tip, so it is also the only way the files this
                # run wrote reach the session that comes after it.
                after=lambda: service.release_project(session_id),
            )
        except RunAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=run_view(run))

    @app.get("/api/projects/{project_id}/auto-research")
    async def get_research_run(project_id: UUID):
        """This project's run in flight, folded. 404 when nothing is running.

        Deliberately only the live one. "Every run this project has ever done"
        is a projection nobody has built, and answering it here with a stream
        scan would be the read that quietly gets slower for a year.
        """
        if research is None:
            raise HTTPException(status_code=404, detail="autonomous runs are not enabled")
        await _require_project(project_id)
        run = research.active(project_id)
        if run is None:
            raise HTTPException(
                status_code=404, detail=f"no run is active on project {project_id}"
            )
        return run_view(run, await research.state(run.run_id))

    @app.get("/api/workers")
    async def get_all_workers():
        """Everything in flight anywhere, in one request.

        For a reader who is not looking at a project: the console's agent
        widget sits on every page and its collapsed state is a count across all
        of them, which the per-project route below cannot answer without one
        request per project on every page load.

        Only projects with something running are returned, and the empty list
        is the ordinary answer. That is not a shortcut for the client's benefit
        -- it is what makes this cheap, because `everywhere` folds only the
        projects its supervisors named rather than every project that exists.

        404 when no roster is wired, matching the per-project route exactly: a
        200 with an empty list would tell a browser that nothing is running,
        which is a different claim from "this build cannot tell you".
        """
        if workers is None:
            raise HTTPException(status_code=404, detail="the worker roster is not enabled")
        return [roster_view(roster) for roster in await workers.everywhere()]

    @app.get("/api/projects/{project_id}/workers")
    async def get_workers(project_id: UUID):
        """Everything in flight on this project, right now.

        Polled rather than pushed, and cheap enough to be: two process-local
        dicts and one fold. What it sets the latency of is "a new worker
        appeared" -- everything *inside* a worker arrives over the live feed,
        which is where a person's attention actually is.

        404 when no roster is wired, matching how `auto-research` answers for
        a feature this build does not have. A 200 with an empty list would
        tell a browser that nothing is running, which is a different claim.
        """
        if workers is None:
            raise HTTPException(status_code=404, detail="the worker roster is not enabled")
        await _require_project(project_id)
        return roster_view(await workers.on(project_id))

    @app.get("/api/projects/{project_id}/extraction")
    async def get_extraction(project_id: UUID):
        """What the running extraction has done so far, and the last one's account.

        A tab that arrived mid-ingest, or one whose connection dropped, has no
        other way back: these frames carry no feed position, so
        `Last-Event-ID` cannot replay them. 200 with two empty lists when
        nothing has run -- an absent extraction is a state, not a missing
        resource, and unlike `/workers` there is no claim being made about
        what is running elsewhere.
        """
        await _require_project(project_id)
        if extraction is None:
            return {"current": [], "last": []}
        return {
            "current": extraction.current(project_id),
            "last": extraction.last(project_id),
        }

    @app.post("/api/projects/{project_id}/auto-research/cancel")
    async def cancel_research_run(project_id: UUID):
        """Ask this project's run to stop after the round it is in.

        200 with `cancelled: false` when there was nothing running, rather
        than a 404: the caller wanted no run to be in flight, and that is the
        state they are in. The run is still finishing its round when this
        returns -- see `ResearchSupervisor.cancel` for why it is not killed.
        """
        if research is None:
            raise HTTPException(status_code=404, detail="autonomous runs are not enabled")
        await _require_project(project_id)
        run = research.cancel(project_id)
        if run is None:
            return {"cancelled": False, "run": None}
        return {"cancelled": True, "run": run_view(run)}

    def _ask_frame(note: object) -> str:
        """One SSE `data:` line per note.

        `message` mirrors ActivityMessage's fields so the browser reuses the
        parsing it already has for the session activity feed.
        """
        if isinstance(note, ActivityDelta):
            body: dict[str, Any] = {
                "type": "delta",
                "message_id": note.message_id,
                "text": note.text,
            }
        elif isinstance(note, ActivityMessage):
            body = {
                "type": "message",
                "message_id": note.message_id,
                "kind": note.kind,
                "payload": note.payload,
                "is_error": note.is_error,
            }
        elif isinstance(note, AskAnswer):
            body = {
                "type": "answer",
                "text": note.text,
                "citations": [
                    {"kind": citation.kind, "id": citation.id} for citation in note.citations
                ],
            }
        else:  # ActivityRemark and anything added later
            body = {"type": "message", "message_id": "", "kind": "assistant", "payload": {}}
        return f"data: {json.dumps(body)}\n\n"

    @app.post("/api/projects/{project_id}/ask")
    async def ask_project(project_id: UUID, body: AskRequest):
        if ask is None:
            raise HTTPException(status_code=503, detail="asking is not configured")
        # Guarded because `create_app` takes every dependency separately and the
        # ask route tests pass `service=None`; without the guard they would fail
        # on the check rather than on what they are about. The cost of skipping
        # it there is that "unknown project" is only enforced in a build that
        # has a session service -- which is every real one.
        if service is not None:
            await _require_project(project_id)

        notes = ask.ask(project_id=project_id, chat_id=body.chat_id, question=body.question)
        # `first` and `failed` are the two ways this can come back, and only
        # one of them can still become a status code.
        failed: Exception | None = None
        try:
            first = await anext(notes)
        except AskInFlight as busy:
            # Raised before any streaming begins, so it can still be a status code
            # rather than an error frame the browser has to special-case.
            raise HTTPException(status_code=409, detail=str(busy)) from busy
        except StopAsyncIteration:
            first = None
        except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
            # An executor that fails before its first note -- the ordinary
            # shape of a model that is simply unreachable. A 500 here would be
            # honest but useless to a page that has already opened an
            # EventSource, so it is reported as the same error frame a failure
            # halfway through would produce, and the page needs one path.
            first, failed = None, failure

        async def stream():
            try:
                if failed is not None:
                    raise failed
                if first is not None:
                    yield _ask_frame(first)
                async for note in notes:
                    yield _ask_frame(note)
            except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
                # A stream that simply stops looks identical to a slow model, so a
                # failure is reported in-band before the connection closes.
                yield f"data: {json.dumps({'type': 'error', 'detail': str(failure)})}\n\n"
            finally:
                # The only path that cancels the executor task when a reader
                # walks away: `AskService.ask`'s own `finally` runs when this
                # `aclose()` reaches it, and nothing else would ever cancel a
                # model call the reader has stopped waiting for. The cost of
                # forgetting this line is a live model call per abandoned
                # request.
                #
                # When it runs is the part worth knowing, because it is not
                # "on disconnect". Starlette never calls `aclose()` on
                # `body_iterator`: a disconnect either propagates an `OSError`
                # out of `stream_response` or fires the task group's cancel
                # scope, and in both cases *this* generator is left suspended
                # at a `yield` and never resumed. The `finally` therefore runs
                # when CPython finalises the generator -- the async-generator
                # finalization hook schedules `aclose()` once the last
                # reference drops, or `loop.shutdown_asyncgens` does it at
                # shutdown. It does run; it is not guaranteed to run promptly,
                # so an abandoned model call can outlive the request by as long
                # as the last reference does.
                await notes.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.delete("/api/projects/{project_id}/ask/{chat_id}")
    async def forget_ask(project_id: UUID, chat_id: str):
        if ask is None:
            raise HTTPException(status_code=503, detail="asking is not configured")
        # No `_require_project` here, unlike the POST. Forgetting is local to an
        # in-memory registry, costs nothing to run against an id that names no
        # project, and a page tidying up after a project was deleted underneath
        # it should not be answered 404 for doing so.
        ask.forget(chat_id)
        return {"ok": True}

    @app.get("/api/health")
    async def health():
        """Whether the derived views behind this API can be trusted.

        `/sessions` is answered from a projection, so unlike a fold it can be
        wrong -- and a wrong row looks exactly like a right one. This is where
        a UI finds out to say so.
        """
        summaries = await service.summaries_health()
        return {
            "summaries": {
                "healthy": summaries.healthy,
                "failed_events": summaries.failed_events,
                "following": summaries.following,
                "behind": summaries.behind,
            }
        }

    @app.post("/api/summaries/rebuild")
    async def rebuild_summaries():
        """Derive the session list from the log again, and report the result.

        Exposed over HTTP because the browser is the primary surface and a
        problem you can see but not fix is only half-reported. Safe to call at
        any time: it discards derived data and recomputes it, so the worst case
        is wasted work, and the log it derives from is never touched.
        """
        await service.rebuild_summaries()
        health = await service.summaries_health()
        return {"healthy": health.healthy, "failed_events": health.failed_events}

    @app.post("/api/corpus/rebuild")
    async def rebuild_corpus():
        """Derive the corpus table from the log again, and say what it holds.

        A sibling of `/api/summaries/rebuild` rather than part of it, for the
        reason `CorpusRunner` is a second runner: rebuilding is a manual repair
        that stops a manager, truncates a table and resets a checkpoint, and
        two tables that can fail independently have to be repairable
        independently. Repairing `/sessions` must not truncate the corpus.

        Goes through the runner rather than a `SessionService` method, unlike
        its sibling. `SessionSummaries` is a port the service already owns and
        answers for; the corpus runner reaches this layer directly, and adding
        a passthrough to the service would be a use case with nothing in it.

        Safe at any time, and the same argument as its sibling: every byte it
        discards is derivable from the event that put it there, so the worst
        case is wasted work. It is also the only way to correct `extracted` on
        a database written before that column existed -- see
        `CorpusDocumentRow.extracted_at`, where the measurement is recorded.
        """
        if corpus is None:
            raise HTTPException(status_code=503, detail="no corpus read model is configured")
        await corpus.rebuild()
        return {"rebuilt": True}

    @app.get("/api/tree")
    async def fork_tree():
        return tree_view(build_fork_tree(await service.list_sessions()))

    @app.get("/api/sessions/{session_id}")
    async def get_session(session_id: UUID):
        session = await _load(session_id)
        project_id = session.state.project_id
        holds = None
        if project_id is not None:
            state = await service.project_state(project_id)
            holds = state.active_session_id == session_id
        return session_view(
            session,
            await service.history(session_id),
            holds_project=holds,
            knowledge_attached=(
                None if project_id is None else service.attached_project_id == project_id
            ),
        )

    @app.get("/api/sessions/{session_id}/events")
    async def get_events(session_id: UUID):
        await _load(session_id)
        return event_rows(await service.history(session_id))

    @app.get("/api/sessions/{session_id}/at/{at}")
    async def get_session_at(session_id: UUID, at: int):
        """Time travel: the workspace as of event `at`. Folds, never writes."""
        try:
            session = await service.state_at(session_id, at)
        except (ValueError, CommandRejectedError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return session_view(session, await service.history(session_id), at=at)

    @app.get("/api/sessions/{session_id}/files")
    async def get_file(session_id: UUID, path: str, at: int | None = None):
        """A file's contents, at HEAD or as of event `at`.

        Scrubbing has to be able to read a file that no longer exists at HEAD --
        seeing a deleted file again is the point of time travel, not an error.
        """
        return {"path": path, "content": await _read_file(session_id, path, at), "at": at}

    @app.get("/api/sessions/{session_id}/files/history")
    async def get_file_history(session_id: UUID, path: str):
        await _load(session_id)
        return file_history(await service.history(session_id), path)

    async def _read_file(session_id: UUID, path: str, at: int | None) -> str:
        """One file's contents at HEAD or as of `at`, or a 404 saying which.

        Shared by the raw, parsed and attempt routes so the three cannot drift
        apart on what "not found at this point in the log" means. Time travel
        is not optional on any of them: a learner reading a lesson at a scrub
        point has to be graded against the lesson that was there, and an author
        diffing two revisions of a question needs both of them to parse.
        """
        if at is None:
            session = await _load(session_id)
        else:
            try:
                session = await service.state_at(session_id, at)
            except (ValueError, CommandRejectedError) as error:
                raise HTTPException(status_code=400, detail=str(error)) from error
        entry = session.state.files.get(path)
        if entry is None:
            moment = "at HEAD" if at is None else f"as of event {at}"
            raise HTTPException(status_code=404, detail=f"{path}: not found {moment}")
        return entry.get("content", "")

    @app.get("/api/sessions/{session_id}/files/parsed")
    async def get_file_parsed(
        session_id: UUID,
        path: str,
        at: int | None = None,
        view: View = "author",
    ):
        """A markdown file as blocks, with interactive components resolved.

        `view` is a `Literal`, so FastAPI rejects `learnr` with a 422 rather
        than falling back to a default. A typo that quietly returned the author
        view would hand back the answer key on exactly the request that meant
        to ask for it to be withheld -- the one failure mode of this route that
        is worth a hard edge.
        """
        content = await _read_file(session_id, path, at)
        return project(parse_document(content, path=path), view=view) | {"at": at}

    @app.post("/api/sessions/{session_id}/attempts")
    async def post_attempt(session_id: UUID, body: Attempt):
        """Mark one attempt. The server holds the key; the browser was not given it.

        A wrong answer is a 200 with `correct: false` -- it is a result, not an
        error. The 400s here are all malformed *requests*: a response shape the
        item cannot interpret, or an item that has no answer to mark.
        """
        content = await _read_file(session_id, body.path, body.at)
        component = parse_document(content, path=body.path).component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"{body.path} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        # Recorded after grading and before answering, so a verdict the learner
        # was shown is never one the log has no record of. The digest is of the
        # body as it stood, which is what lets a later reader see that an item
        # was rewritten under someone mid-course.
        progress = await service.record_attempt(
            session_id,
            path=body.path,
            component_id=body.component_id,
            component_type=component.type,
            digest=hashlib.sha256(component.raw.encode("utf-8")).hexdigest(),
            response=body.response,
            correct=verdict.correct,
            score=verdict.score,
            at=body.at,
        )
        item = item_view(progress, body.path, body.component_id)
        return verdict.as_json() | {"progress": item}

    @app.get("/api/sessions/{session_id}/progress")
    async def get_progress(session_id: UUID, path: str | None = None):
        """What this learner has done, for the whole session or one file.

        `path` narrows it, because the browser asks on opening a document and
        has no use for the other twelve. Answers an empty mapping for a session
        nobody has answered anything in -- that is the ordinary case for every
        course before its first learner, not a 404.
        """
        await _load(session_id)
        state = await service.learner_progress(session_id)
        return progress_view(state, path=path)

    @app.post("/api/sessions/{session_id}/progress/checklist")
    async def post_checklist(session_id: UUID, body: ChecklistState):
        """Remember which boxes are ticked on a `persist: true` checklist.

        A separate route from `/attempts` rather than a shape of it, because a
        checklist has no answer key: there is no verdict, nothing to be right
        about, and `grade` refuses it by design. Folding the two together would
        mean an endpoint that sometimes marks and sometimes just remembers.

        `persist` is honoured rather than assumed: a checklist that did not ask
        to be remembered is a 400, so a client cannot quietly accumulate state
        the author never opted into.
        """
        content = await _read_file(session_id, body.path, body.at)
        component = parse_document(content, path=body.path).component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"{body.path} has no component {body.component_id!r}",
            )
        if component.type != "checklist":
            raise HTTPException(
                status_code=400,
                detail=f"{body.component_id!r} is a {component.type}, not a checklist",
            )
        if component.data.get("persist") is not True:
            raise HTTPException(
                status_code=400,
                detail=f"checklist {body.component_id!r} does not set `persist: true`",
            )
        items = component.data.get("items", [])
        for index in body.checked:
            if not 0 <= index < len(items):
                raise HTTPException(
                    status_code=400,
                    detail=f"there is no item {index}; this checklist has {len(items)}",
                )
        progress = await service.record_checklist(
            session_id,
            path=body.path,
            component_id=body.component_id,
            checked=list(body.checked),
        )
        return item_view(progress, body.path, body.component_id)

    @app.post("/api/sessions/{session_id}/turns")
    async def run_turn(session_id: UUID, body: NewTurn):
        await _load(session_id)
        # Re-attach per turn rather than only at join. One process serves
        # every browser session, so by the time this session takes a turn the
        # attached graph may belong to a project joined in another tab -- or,
        # after a restart, to nothing at all. A session whose recorded prompt
        # promises knowledge tools has to get them on every turn, not just the
        # request that happened to join. A no-op for a session in no project,
        # and for a graph that will not open: knowledge is degraded then, and
        # the turn is still worth running.
        try:
            await service.ensure_project_attached(session_id)
        # No `noqa` needed: ruff accepts a bare `except Exception` whose handler
        # logs it with `exc_info=True`, which is what the warning below does.
        except Exception:
            logger.warning(
                "could not attach knowledge graph for %s", session_id, exc_info=True
            )
        try:
            outcome = await turns.run(session_id, body.input)
        except TurnAlreadyRunning as error:
            raise HTTPException(
                status_code=409,
                detail="a turn is already running on this session",
            ) from error
        except TurnCancelled as error:
            # Not a failure: someone asked for this. 499 is nginx's
            # "client closed request" -- the closest thing to a standard code
            # for work abandoned on purpose.
            raise HTTPException(status_code=499, detail=str(error)) from error
        except OptimisticLockError as error:
            # Another writer -- the REPL, or a second process -- got there
            # first. The log is append-only and the loser's events were
            # discarded whole, so nothing happened; this is a retry.
            raise HTTPException(
                status_code=409,
                detail="another turn was recorded on this session first; reload and retry",
            ) from error
        return {
            "reply": outcome.reply,
            "turn_index": outcome.turn_index,
            "from_index": outcome.from_index,
            "to_index": outcome.to_index,
        }

    @app.post("/api/sessions/{session_id}/turns/cancel")
    async def cancel_turn(session_id: UUID):
        """Stop the in-flight turn on this session, if there is one.

        Returns once the turn has actually unwound, so a caller that hears
        "cancelled" can trust the log already reflects it.
        """
        await _load(session_id)
        cancellation = await turns.cancel(session_id)
        return {
            "cancelled": cancellation.cancelled,
            "settled": cancellation.settled,
        }

    @app.get("/api/sessions/{session_id}/turns/current")
    async def current_turn(session_id: UUID):
        """What is in flight -- so a tab that arrived mid-turn can say so."""
        await _load(session_id)
        running = turns.running(session_id)
        if running is None:
            return {
                "running": False,
                "turn_index": None,
                "started_at": None,
                "elapsed_seconds": None,
            }
        return {
            "running": True,
            "turn_index": running.turn_index,
            "started_at": running.started_at.isoformat(),
            "elapsed_seconds": running.elapsed_seconds(datetime.now(UTC)),
        }

    @app.get("/api/sessions/{session_id}/turns/current/activity")
    async def current_activity(session_id: UUID):
        """What the running turn has produced so far, and what the last failed
        one threw away.

        The live feed announces each note as it arrives, but a tab that opened
        mid-turn never saw those frames -- and unlike log events they carry no
        position, so `Last-Event-ID` cannot replay them. This is how it
        catches up, exactly as `/approvals` is for a parked approval.
        """
        await _load(session_id)
        if activity is None:
            return {"running": [], "discarded": []}
        return {
            "running": activity.current(session_id),
            "discarded": activity.discarded(session_id),
        }

    @app.get("/api/sessions/{session_id}/approvals")
    async def pending_approvals(session_id: UUID):
        """Gated calls this session is waiting on.

        The live feed announces each one as it is parked, but a tab that opened
        mid-turn never saw that frame -- this is how it catches up.
        """
        await _load(session_id)
        return [] if approvals is None else approvals.pending(session_id)

    @app.post("/api/sessions/{session_id}/approvals/{approval_id}")
    async def decide_approval(session_id: UUID, approval_id: str, body: Decision):
        """Answer one parked approval, unblocking the turn waiting on it."""
        if approvals is None:
            raise HTTPException(status_code=404, detail="approvals are not wired up")
        await _load(session_id)
        try:
            approvals.resolve(
                session_id,
                approval_id,
                ApprovalDecision(
                    type=body.type,
                    edited_args=body.edited_args,
                    message=body.message,
                ),
            )
        except UnknownApproval as error:
            # Already answered, or the turn behind it was cancelled. Both are
            # races a second tab can lose honestly.
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"decided": True}

    def _policy() -> AutonomyPolicy:
        """The instance's policy, or a 404 saying this build has none.

        404 rather than a permissive default, matching `/workers`: "this build
        cannot tell you what the agent may do without asking" is a different
        claim from "everything is automatic", and a UI that read the second off
        the first would show a row of green switches for a policy it has no
        handle on.
        """
        if policy is None:
            raise HTTPException(status_code=404, detail="the autonomy policy is not wired up")
        return policy

    @app.get("/api/autonomy")
    async def get_autonomy():
        """What the agent may currently do without asking.

        No session in the path, because there is no per-session answer to give:
        one `AutonomyPolicy` serves the whole process, so this is a read of
        instance state. See the POST routes for why the *writes* name a session
        even though the state they change does not belong to one.
        """
        return autonomy_view(_policy())

    @app.post("/api/sessions/{session_id}/autonomy")
    async def set_autonomy(session_id: UUID, body: AutonomyChoice):
        """Set one tool's level, and record that it was set.

        Two steps, both required, exactly as `/autonomy` in the REPL does them.
        The policy is what the executor consults, so mutating it is what
        changes behaviour -- but a level that changed mid-session and left no
        trace makes every surrounding decision unreadable afterwards, in a
        system whose whole point is a complete audit trail. See
        `SessionService.record_autonomy_change`.

        The asymmetry is real and worth stating plainly rather than leaving to
        be discovered: **the policy is instance-wide and the record is
        per-session.** One object answers for every session in this process, so
        this call changes what the agent may do in all of them, while the
        `AutonomyChanged` event lands on this session's stream alone. That is
        what the REPL does, and it is the right trade for a local single-user
        tool -- the same trade `join_project` documents for graph attachment.
        The session in the path is therefore "who is answering for this
        change", not "where it applies". A per-session policy map would make the
        two agree, but nothing has asked for concurrent untrusted users, and
        splitting the policy would silently change what the executor consults
        for every other caller.

        A bad tool or level is a 400 carrying the policy's own message, and
        nothing is recorded: a rejected `set` changed nothing, so a log entry
        would describe a change that did not happen.
        """
        instance = _policy()
        await _load(session_id)
        try:
            instance.set(body.tool, body.level)  # type: ignore[arg-type]
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        await service.record_autonomy_change(session_id, body.tool, body.level)
        # The full map, so a client that just flipped one switch does not need a
        # second request to redraw the rest -- and cannot drift from the server
        # by assuming its own change was the only one.
        return autonomy_view(instance)

    @app.post("/api/sessions/{session_id}/autonomy/allow-all")
    async def allow_all_autonomy(session_id: UUID, body: AllowAll | None = None):
        """Stop asking about everything -- except the workflow review gates.

        The instance-wide/per-session asymmetry described on `set_autonomy`
        applies here too, and more loudly: this relaxes every hazard for every
        session in the process, and records it on one.

        `changed` is only what actually moved, and one `AutonomyChanged` is
        recorded per entry -- never one per gated tool. A log that claimed eight
        decisions where a person made one is as unreadable as a log that
        omitted them, and it is `changed` the UI should report back so it says
        what it did rather than claiming more.
        """
        instance = _policy()
        await _load(session_id)
        options = body or AllowAll()
        changed = instance.relax_all(include_stage_gates=options.include_stage_gates)
        # One append, not one per tool. Each append is a chance for a turn
        # running on this session to lose its version, and this route issues
        # its writes back to back -- see `record_autonomy_changes`.
        await service.record_autonomy_changes(session_id, changed)
        return {"changed": changed} | autonomy_view(instance)

    @app.post("/api/sessions/{session_id}/forks")
    async def fork_session(session_id: UUID, body: NewFork):
        await _load(session_id)
        try:
            return {"id": str(await service.fork(session_id, body.at))}
        except (ValueError, CommandRejectedError) as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

    @app.get("/api/stream")
    async def stream(request: Request) -> StreamingResponse:
        """Every event, as it is appended, to every listening browser.

        `Last-Event-ID` is the browser's own reconnect header -- EventSource
        sends it automatically with the id of the last frame it received, so
        resuming costs the client nothing and closes the window where events
        appended during a dropped connection would never be seen.
        """
        resume_from = request.headers.get("last-event-id")
        return StreamingResponse(
            _sse(
                request, feed, resume_from, approvals, activity, extraction, seeding, dispatch
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    if STATIC_DIR.is_dir():
        app.mount("/static", _RevalidatedStatics(directory=STATIC_DIR), name="static")

        @app.get("/")
        async def index() -> FileResponse:
            # The same `no-cache` as the assets, and for a sharper reason: this
            # is the file naming them. A cached index.html paired with rebuilt
            # assets is the mismatch that paints nothing.
            return FileResponse(
                STATIC_DIR / "index.html", headers={"Cache-Control": "no-cache"}
            )

    return app


async def _sse(
    request: Request,
    feed: LiveFeed,
    resume_from: str | None = None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
    extraction: ExtractionActivity | None = None,
    seeding: SeedingActivity | None = None,
    dispatch: DispatchQueue | None = None,
) -> AsyncIterator[str]:
    """Serialise the live feed as server-sent events.

    Keepalive comments keep intermediaries from closing an idle connection --
    a session can sit silent for a minute while the model thinks, which is
    exactly when the browser most needs the connection to still be there.

    Every logged frame carries the position that follows it as its id, so a
    browser that drops can say where it got to. An id we cannot place --
    stale, or from a database since replaced -- is treated as no id at all:
    starting at the live end shows less than the client wanted, while
    replaying the entire log at it would be worse than the gap.

    Approval requests, turn activity notes, extraction progress, seeding
    status and dispatch status ride this same connection rather than one each
    of their own, for the same reason as each other: none is a log entry -- an
    approval that is never answered, provisional turn content, where an ingest
    has got to, whether a seeding run is still going, and what a project has
    queued at its topics all leave no event behind -- so none carries an id,
    and a reconnecting browser refetches what it missed (`/approvals`, the
    activity catch-up route, `/projects/{id}/extraction`,
    `/projects/{id}/topics/seed`, or `/projects/{id}/dispatch`) instead of
    replaying them. But a second
    channel per concern would multiply the ways a tab can be half-connected,
    and a turn that halts for a person, or is still streaming its reply, is
    exactly the moment when being half-connected is worst.
    """
    queue: asyncio.Queue = asyncio.Queue()
    start_at = feed.decode_position(resume_from) if resume_from else None
    # Taken here rather than left to `follow`, so that by the time this
    # generator yields anything the cursor is already fixed. `follow` would
    # take the same position on the first turn of the pump task below, which is
    # scheduled and not awaited -- so "the response has started" would not mean
    # "the subscriber is placed", and an event appended in between would be
    # missed by a client that had every reason to think it was listening.
    #
    # `from_beginning` is not a nicety. An empty log has no position, so
    # `position_now()` answers `None` -- which is the same value as "I am not
    # telling you where to start", and `follow` responds to that by taking the
    # position itself, later, on the pump's first turn. The window this exists
    # to close would have reopened for exactly the case where it is widest.
    # Replaying from the start is not a different behaviour here: the log was
    # empty when we looked, so everything from the start *is* everything since.
    from_beginning = False
    if start_at is None:
        start_at = await feed.position_now()
        from_beginning = start_at is None

    async def pump() -> None:
        async for entry in feed.follow(from_position=start_at, from_start=from_beginning):
            await queue.put(("event", entry))

    # The feed is drained by its own task rather than awaited inline, so waiting
    # for the next event never means being unable to notice anything else. What
    # this coroutine waits on is a queue, which is safe to cancel; cancelling a
    # database poll mid-flight is not.
    pumps = [asyncio.create_task(pump())]
    listening = None
    if approvals is not None:
        listening = approvals.listen()

        async def pump_approvals() -> None:
            while True:
                await queue.put(("approval", await listening.get()))

        pumps.append(asyncio.create_task(pump_approvals()))

    watching = None
    if activity is not None:
        watching = activity.listen()

        async def pump_activity() -> None:
            while True:
                await queue.put(("activity", await watching.get()))

        pumps.append(asyncio.create_task(pump_activity()))

    extracting = None
    if extraction is not None:
        extracting = extraction.listen()

        async def pump_extraction() -> None:
            while True:
                await queue.put(("extraction", await extracting.get()))

        pumps.append(asyncio.create_task(pump_extraction()))

    seeded = None
    if seeding is not None:
        seeded = seeding.listen()

        async def pump_seeding() -> None:
            while True:
                await queue.put(("seeding", await seeded.get()))

        pumps.append(asyncio.create_task(pump_seeding()))

    dispatching = None
    if dispatch is not None:
        dispatching = dispatch.listen()

        async def pump_dispatch() -> None:
            while True:
                await queue.put(("dispatch", await dispatching.get()))

        pumps.append(asyncio.create_task(pump_dispatch()))

    idle = 0.0
    try:
        # "You are subscribed, from a position already taken."
        #
        # A comment rather than an event: `EventSource` ignores `:` lines
        # entirely, so no browser needs to know this exists and no client code
        # changes. What it buys is a point in time that means something --
        # headers arrive when the route returns, which is before any of the
        # above has run, so `onopen` alone never told a client its cursor was
        # placed.
        #
        # Inside the `try`, not above it, and that placement is the whole
        # reason this is not a one-line addition: a yield is a suspension
        # point, and a client that hangs up exactly here would otherwise throw
        # `GeneratorExit` past the `finally` that stops the pump tasks and
        # releases the listeners.
        #
        # It also makes the tests in `test_web.py` and `test_turn_visibility.py`
        # honest. They established "the subscriber is listening" with sleeps of
        # 0.05 to 0.4 seconds -- the `BACKLOG.md` B4 shape, and the reason a
        # write racing a subscription looked like a broken feed on a loaded
        # machine.
        yield ": ready\n\n"

        while not await request.is_disconnected():
            try:
                kind, item = await asyncio.wait_for(queue.get(), timeout=DISCONNECT_CHECK)
            except TimeoutError:
                idle += DISCONNECT_CHECK
                if idle >= KEEPALIVE_SECONDS:
                    # Long enough that an intermediary might give up on us --
                    # a turn can sit silent for a minute while the model thinks.
                    yield ": keepalive\n\n"
                    idle = 0.0
                continue
            idle = 0.0
            if kind in ("approval", "activity", "extraction", "seeding", "dispatch"):
                yield f"data: {json.dumps(item)}\n\n"
                continue
            if item.aggregate_type == Topic.aggregate_type:
                payload = topic_change(item.aggregate_id, item.event)
            elif item.aggregate_type in KNOWLEDGE_CATEGORIES:
                # `tenant_id`, not `aggregate_id`: see `graph_change`. Read
                # directly rather than through a `getattr` default -- every
                # event in these two categories is a `TenantDomainEvent`, and
                # one that was not would be a bug worth an `AttributeError`
                # naming it rather than a frame quietly addressed to nobody.
                payload = graph_change(item.event.tenant_id, item.event)
            elif item.aggregate_type == Project.aggregate_type:
                # Same free addressing as a corpus, and for the same reason:
                # a project's aggregate id *is* the project id, so the frame
                # names its project without a read model lookup.
                payload = project_change(item.aggregate_id, item.event)
            elif item.aggregate_type == Corpus.aggregate_type:
                # A corpus shares its project's UUID, so the aggregate id is
                # the project id with no lookup -- unlike a topic, which is why
                # a topic frame carries no project at all.
                payload = corpus_change(item.aggregate_id, item.event)
            else:
                payload = feed_event(
                    item.aggregate_id,
                    item.event,
                    getattr(item.event, "aggregate_version", None),
                )
            # One yield, not two: an id and its data are a single SSE frame,
            # and splitting them would let a cancellation land between the
            # cursor and the event it belongs to.
            cursor = feed.encode_position(item.position)
            yield f"id: {cursor}\ndata: {json.dumps(payload)}\n\n"
    finally:
        if approvals is not None and listening is not None:
            approvals.stop_listening(listening)
        if activity is not None and watching is not None:
            activity.stop_listening(watching)
        if extraction is not None and extracting is not None:
            extraction.stop_listening(extracting)
        if seeding is not None and seeded is not None:
            seeding.stop_listening(seeded)
        if dispatch is not None and dispatching is not None:
            dispatch.stop_listening(dispatching)
        for pumping in pumps:
            pumping.cancel()
            with suppress(asyncio.CancelledError):
                await pumping

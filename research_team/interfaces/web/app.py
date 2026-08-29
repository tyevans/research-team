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
from typing import Annotated, Any, Literal, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from eventsource import CommandRejectedError, OptimisticLockError
from eventsource.application.aggregates.repository import AggregateRepository
from eventsource.ports.dlq import DLQEntry
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
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError, field_validator
from starlette.datastructures import Headers

from research_team.application import (
    ApprovalDecision,
    AutonomyPolicy,
    LiveFeed,
    RunAlreadyActive,
    SessionService,
    TurnAlreadyRunning,
    TurnCancelled,
    TurnSupervisor,
    WorkerRoster,
    build_fork_tree,
)
from research_team.application.area_projection import GraphTooLarge
from research_team.application.ask import (
    AskAnswer,
    AskConversationOpened,
    AskInFlight,
    AskService,
)
from research_team.application.ask_components import answer_document
from research_team.application.blobs import BlobStorePort
from research_team.application.components import View, parse_document, project
from research_team.application.corpus_editing import CorpusEditor, DocumentExists, NotDropped
from research_team.application.corpus_spans import quote
from research_team.application.course_authoring import CourseAuthor
from research_team.application.course_catalog import (
    ArtGeneratorPort,
    BlurbTextPort,
    Catalog,
    CatalogService,
    OutlineTextPort,
)
from research_team.application.course_realization import CourseService
from research_team.application.curriculum import CurriculumService
from research_team.application.document_extraction import DocumentExtractor, UnknownDocument
from research_team.application.entity_definitions import DefinitionService, serve_citations
from research_team.application.frontmatter import parse_frontmatter
from research_team.application.grading import GradingError, grade
from research_team.application.graph_read import (
    MAX_GRAPH_NODES,
    MAX_NEIGHBORHOOD_DEPTH,
    MAX_USAGES,
    GraphReadPort,
)
from research_team.application.knowledge import ExtractionNote, KnowledgeError
from research_team.application.media_acquisition import MAX_UPLOAD_BYTES, MediaAcceptWorker
from research_team.application.media_curation import (
    CurationUnavailable,
    MediaCurationService,
    MediaCurationTextPort,
    MediaSearchPort,
)
from research_team.application.ontology_discovery import OntologyDiscoveryService
from research_team.application.perception import (
    MediaBytesMissing,
    MediaPerceiver,
    NotPerceivable,
    PerceptionPort,
    SourceDropped,
)
from research_team.application.ports import ActivityDelta, ActivityMessage, ActivityRemark
from research_team.application.project_graphs import ProjectGraphs
from research_team.application.project_summaries import ProjectSummaries
from research_team.application.socratic import (
    DialogueConcluded,
    DialogueInFlight,
    SocraticDialogueOpened,
    SocraticDialogueService,
    SocraticPrompt,
    UnknownDialogue,
)
from research_team.application.socratic_components import dialogue_document
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
from research_team.application.topics import MAX_OPEN_TOPICS
from research_team.domain import (
    Corpus,
    CreateProject,
    Project,
    SessionPurpose,
)
from research_team.domain.course import AbandonCourse, Course, RealizeCourse, course_stream_id
from research_team.domain.interaction import INTERACTION_EVENTS, InteractionEvent
from research_team.domain.media_proposals import (
    AcceptMediaProposal,
    IgnoreMediaAsset,
    IgnoreMediaHost,
    MediaProposals,
    RejectMediaProposal,
    UnignoreMediaAsset,
    UnignoreMediaHost,
)
from research_team.domain.topic import (
    AddSubQuestion,
    ResolveSubQuestion,
    SetTopicStatus,
    Topic,
    TopicStatus,
)
from research_team.infrastructure.interaction.recorder import EventStoreInteractionRecorder
from research_team.infrastructure.knowledge.co_mention_reader import RecordedCoMentions
from research_team.infrastructure.knowledge.graph_reader import ProjectGraphReader
from research_team.infrastructure.knowledge.library_art import LibraryArtProvider
from research_team.infrastructure.knowledge.semantic_neighbours import VectorNeighbours
from research_team.infrastructure.knowledge.svg_sanitiser import SvgSanitiser
from research_team.infrastructure.knowledge.timeline_reader import ProjectTimelineReader
from research_team.infrastructure.knowledge.usage_reader import UsageReader
from research_team.infrastructure.persistence import CorpusRunner
from research_team.infrastructure.persistence.corpus_reader import ProjectCorpusReader
from research_team.infrastructure.persistence.event_store import KNOWLEDGE_CATEGORIES
from research_team.infrastructure.persistence.interaction_log import (
    ENVELOPE_FIELDS,
    BrowserSessionPage,
    InteractionEventPage,
    InteractionEventRow,
    InteractionLogReader,
    InteractionSummary,
)
from research_team.infrastructure.persistence.read_models import (
    ArtStore,
    AskConversationRunner,
    CatalogFeatureStore,
    MediaProposalRow,
    MediaProposalRunner,
    OntologyRunner,
    SocraticDialogueRow,
    SocraticDialogueRunner,
)
from research_team.interfaces.web.activity import TurnActivity
from research_team.interfaces.web.approvals import UnknownApproval, WebApprovals
from research_team.interfaces.web.art_sweep import ArtReroll, ArtSweep, RerollAlreadyActive
from research_team.interfaces.web.art_sweep import SweepAlreadyActive as ArtSweepAlreadyActive
from research_team.interfaces.web.auth import (
    AuthConfig,
    AuthGate,
    SessionSigner,
    SessionStore,
    register_auth_routes,
)
from research_team.interfaces.web.authored_files import (
    is_path_file,
    path_file,
    split_area,
)
from research_team.interfaces.web.authoring import AuthoringActivity
from research_team.interfaces.web.blurb_sweep import BlurbSweep, SweepAlreadyActive
from research_team.interfaces.web.dispatch import DispatchQueue
from research_team.interfaces.web.export import ExportDeps, export_router
from research_team.interfaces.web.extraction import ExtractionActivity
from research_team.interfaces.web.extraction_queue import ExtractionQueue
from research_team.interfaces.web.presenters import (
    area_view,
    autonomy_view,
    catalog_category_view,
    catalog_view,
    corpus_change,
    course_detail_view,
    curriculum_view,
    definition_view,
    dialogue_progress_view,
    dispatch_view,
    entity_page_view,
    event_rows,
    feed_event,
    file_history,
    graph_change,
    graph_view,
    item_view,
    media_change,
    neighborhood_view,
    path_view,
    progress_view,
    project_change,
    project_detail_view,
    project_view,
    reading_head,
    roster_view,
    seeding_view,
    session_view,
    source_text_view,
    source_view,
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
from research_team.interfaces.web.settings import SettingsDeps, settings_router

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

# MAX_UPLOAD_BYTES used to be defined here. It moved to
# `application/media_acquisition.py` because `MediaAcceptWorker`'s download
# path needs the identical ceiling and the application layer may not import
# from this one (`tests/test_architecture.py`) -- see that module's docstring
# for the full reasoning. Imported, not redefined, so there is exactly one
# ceiling for both an interactive upload and an unattended accept to agree on.

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


OntologyDiscoverers = Callable[[UUID], OntologyDiscoveryService]
"""One project's `OntologyDiscoveryService`, built on demand.

A callable for `TopicReaders`' reason -- the project is bound at construction,
so no caller can run a pass against a project it was not handed.

Synchronous and never `None`, unlike `DefinitionReaders` below, and the
difference is what each needs. A definition is assembled from a project's graph
store and chunk store, so building one is asynchronous and can fail when
chunking is off. Discovery needs the document text and a model; neither can be
absent, so there is no `None` for a route to render as 503.
"""


class CatalogFeatureRecorder(Protocol):
    """What a route needs to record one person's featuring decision.

    A protocol rather than the concrete `EventStoreCatalogFeatureRecorder`
    directly, matching `OntologyDiscoveryService`'s own port-facing neighbours
    in this file: the route only ever calls `feature`/`unfeature`, and naming
    the concrete class here would make this interface layer name a class that
    belongs to `infrastructure`.
    """

    async def feature(self, slug: str, rank: int) -> None: ...

    async def unfeature(self, slug: str) -> None: ...


CatalogFeatures = Callable[[], CatalogFeatureStore | None]
"""The read side of course featuring, resolved when a request needs it.

A getter rather than the store itself, and the difference is the whole of a
503 that shipped. `CatalogFeatureStore.open` needs a running event loop, so
`Application.catalog_features` is `None` until `start()` -- which runs in the
server's lifespan, *after* `web.py` has called `create_app`. Passing the value
captured that `None` permanently and every catalog request answered "the
course catalog is not configured" in the running server while every test
passed, because every test starts the application before it builds the app.

A `CatalogFeatureStore | Callable[...]` union was considered and rejected: it
keeps "pass the value" legal, which is exactly the shape that shipped the bug,
and there is no gate that would notice an entrypoint choosing it again. Taking
only the callable means the early read is not expressible here.

The cost is three call sites that already had an open store having to wrap it
in a lambda, and one more indirection per request -- an attribute read.
"""


InteractionReaders = Callable[[], InteractionLogReader | None]
"""The interaction log's reader, resolved when a request needs it.

A getter for exactly `CatalogFeatures`'s reason, one layer along:
`InteractionLogRunner.reader` *raises* until `start()` has run, and `start()`
runs in the server's lifespan -- after `web.py` has called `create_app`. The
spec says `create_app` gains `interaction_reader: InteractionLogReader | None`,
and taking the value is not expressible from the entrypoint without either
starting the runner early or swallowing that `RuntimeError` at wiring time.
Taking only the callable also means the early read cannot be written.

Returning `None` is legal and means "no reader was wired", which is the 503.
"""


InteractionFailures = Callable[[], Awaitable[list[DLQEntry]]]
"""The interaction projection's dead letters, and nothing else.

`InteractionLogRunner.failures` bound, rather than the runner: the health
route needs the DLQ and none of the subscription, checkpoint repository or
lifecycle beside it, and a route holding the runner is a route that could
restart a projection. The narrower seam also lets a test supply a list without
building one.
"""


CatalogFeatureRecorders = Callable[[UUID], CatalogFeatureRecorder]
"""One project's `CatalogFeatureRecorder`, built on demand, matching
`OntologyDiscoverers`'s shape and its reason: the project is bound at
construction, so no caller can feature a candidate in a project it was not
handed."""

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


class AskAttempt(BaseModel):
    """One reader's answer to a component the model wrote into an answer.

    Addressed by `(position, component_id)` rather than by a file path: an ask
    answer has no file, and the turn is what the server re-parses to recover
    the key. `position` is in the body rather than the path for `Attempt`'s
    reason -- one addressing scheme for both attempt routes beats two.

    No `at`. A file can be revised under a learner, which is what `Attempt.at`
    defends against; an `AskTurnRecorded` is a fact about an answer that was
    given and is never rewritten, so there is no second version to grade
    against.
    """

    position: int
    component_id: str
    response: Any = None


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


INTERACTION_BATCH_LIMIT = 200
"""Most events one POST may carry.

The client flushes at 50, so this leaves room for a page-hide flush racing a
timer flush without rejecting a batch that is merely unlucky.
"""


INTERACTION_BODY_LIMIT_BYTES = 2_000_000
"""Most bytes one interaction POST may declare.

Comfortably above what a full legitimate batch can be -- 200 events, each
bounded by `QUERY_TEXT_MAX_LENGTH` plus an envelope of ids, is under a
megabyte -- so this never rejects a batch the client would actually build.
Deliberately loose for that reason: a cap tight enough to be interesting is a
cap that silently loses real batches, and the per-field bounds are what
actually make the data small. This one exists to stop a body that is large
before anything can be validated, which per-event checks cannot do.
"""


class _InteractionBodyCap:
    """Refuse an oversized interaction batch before its body is read.

    The design promised "200 events per batch, and a body-size cap" and only
    the first shipped. The per-field bounds now make a *well-formed* batch
    small, so this is not what stops the ordinary case -- it stops a body that
    is large before anything has looked at its contents, which is the one
    thing per-event validation structurally cannot do: FastAPI reads the whole
    body before the route function runs.

    **Raw ASGI rather than `@app.middleware("http")`, and that is a measured
    constraint rather than a style preference.** The decorator wraps every
    request in Starlette's `BaseHTTPMiddleware`, which runs the endpoint
    inside its own anyio task group; that broke four tests in
    `tests/interfaces/test_extraction_routes.py` -- queueing answered
    `queued: false` and cancelling reported `cancelled: 0`, because the
    extraction routes' fire-and-forget work no longer outlived the response.
    Those four passed with the decorator removed and nothing else changed. A
    plain ASGI callable adds no task group and leaves every other route's
    execution exactly as it was.

    `Content-Length` rather than counting the stream: both delivery paths send
    a `Blob` of known size, so the header is always present from our own
    client, and a chunked request without one falls through to the batch limit
    and the field bounds -- the same defence one layer in, which is enough on
    a local port and cheaper than buffering-while-counting here.

    Scoped to the one path: every other route has its own size story (document
    upload is the obvious one) and must not inherit a cap chosen for
    telemetry.
    """

    def __init__(self, app) -> None:
        self._app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] == "http" and scope.get("path") == "/api/interactions":
            declared = Headers(scope=scope).get("content-length")
            if (
                declared is not None
                and declared.isdigit()
                and int(declared) > INTERACTION_BODY_LIMIT_BYTES
            ):
                response = JSONResponse(
                    status_code=413,
                    content={"detail": "the interaction batch is too large"},
                )
                await response(scope, receive, send)
                return
        await self._app(scope, receive, send)


class InteractionEnvelope(BaseModel):
    """One reported interaction, as the browser sends it.

    Deliberately loose about `payload`: the kind decides its shape, and the
    domain event validates it. Validating twice would mean two vocabularies to
    keep in step, and the second one would drift.
    """

    kind: str
    browser_session_id: UUID
    install_id: UUID
    seq: int
    view: str
    occurred_at: datetime
    project_id: UUID | None = None
    session_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class InteractionBatch(BaseModel):
    """One flush.

    Capped rather than unbounded because this route takes unauthenticated
    input on a local port and the body becomes rows.

    `events` is `list[dict]`, not `list[InteractionEnvelope]`, on purpose:
    FastAPI validates a typed body before the route runs, so a batch typed as
    `list[InteractionEnvelope]` would 422 in full the moment any one envelope
    failed schema validation -- the same whole-batch loss partial acceptance
    exists to avoid, just moved one layer earlier where the route's own
    try/except never gets a chance to run. Each dict is validated into an
    `InteractionEnvelope` by hand, per-event, inside the route.
    """

    events: list[dict[str, Any]] = Field(
        default_factory=list, max_length=INTERACTION_BATCH_LIMIT
    )


class NewSeed(BaseModel):
    """What one seeding turn is asked to name topics for.

    `max_topics` defaults to 8 rather than being required, matching every
    other cap in this file (`NewRun.max_rounds` above): a caller that wants
    the ordinary amount says nothing about it, and the number this layer
    defaults to is the one `TopicSeeder`'s own tests exercise.
    """

    subject: str = Field(min_length=1)
    max_topics: int = 8


class NewAuthoring(BaseModel):
    """Which courses to write, and how long each should be.

    `area` absent means the whole path, which is the ordinary ask and so is
    the default rather than a flag. Naming one area is the narrower request,
    and it is the one that has to be spelled out -- the reverse arrangement
    would make "write everything" the thing a caller reaches by omission from
    a field they have to know exists.

    `lessons` is capped as well as floored. Four model turns per area is the
    fixed cost; a request for forty lessons is four turns asked to produce
    forty files, which no local model does well and which nobody reads. Twelve
    is where a unit stops being a unit.

    `take_over` releases whoever is holding the project first. Off by default
    and spelled the same as `join_project`'s flag, deliberately: a take-over
    ends somebody else's session, and the one thing
    `docs/design/the-holding-session-goes-backstage.md` §1 forbids is a
    console that resolves the lock silently on a person's behalf. The console
    asks first; this is what it sends when the answer is yes.
    """

    area: str | None = None
    lessons: int = Field(default=3, ge=1, le=12)
    take_over: bool = False


class NewDispatch(BaseModel):
    """What an agent dispatched at one topic is being asked to do.

    Plain `str` rather than a `Literal`, so a bad value comes back from the
    route naming the actions that exist -- the same reasoning `AutonomyChoice`
    gives for its two fields. FastAPI's 422 for a `Literal` mismatch is
    machine-readable and names none of them, and `lesson` is exactly the value
    a caller will reasonably try: it is designed, in
    `docs/design/topic-dispatch.md`, and not built.

    Defaults to `understanding` rather than being required, which is now a
    weaker justification than it was: with three actions the default is a
    choice among them rather than the only one on offer. Kept because changing
    it would break every existing caller that omits the field, and because
    `understanding` is the one action that neither fetches nor proposes an
    edit -- the safest thing to do by omission.
    """

    action: str = "understanding"


MAX_BULK_DISPATCH = MAX_OPEN_TOPICS
"""Most topics one bulk dispatch may name.

Tied to `MAX_OPEN_TOPICS` rather than chosen independently, and that is the
whole argument: fifty is the most live topics a project can hold, so "every
topic the filter is showing me" always fits. A smaller cap would refuse the
one request this route exists to serve -- the `All 50` case -- and a larger
one would be a number that could never be reached.

It is a cap on the *request*, not on the queue. Fifty one-turn dispatches is a
long afternoon of model time, and the thing that makes that acceptable is not
this number: it is that the queue renders all fifty, drains one at a time, and
`Stop` drops the lot. That surface is the budget control; this is only a
refusal of a request nobody meant to make.
"""


class BulkDispatch(BaseModel):
    """One action, across a list of topics the client chose.

    **`topic_ids` is required and there is no "all".** The server does not get
    to decide the scope, and the reason is not caution -- it is that "all" has
    no server-side definition that stays true. The queue the person is looking
    at is filtered in the browser (`All 12`, `Needs you 3`), so a route that
    took "all" would have to re-derive that filter from a client that owns it,
    and the two definitions would drift the first time a tab was added. Sending
    the ids makes the count on screen and the count enqueued the same number by
    construction.

    `action` is a plain `str` for `NewDispatch`'s reason and has no default:
    the per-topic route backs a single button whose meaning is obvious, and
    this one backs several.
    """

    action: str
    topic_ids: list[UUID] = Field(min_length=1, max_length=MAX_BULK_DISPATCH)


class AskRequest(BaseModel):
    """One question on one ephemeral chat.

    `chat_id` is the browser's, not the server's: nothing persists a chat, so
    there is no id for a server to have issued. `ConversationRegistry` checks
    the project it was opened under rather than trusting it.
    """

    chat_id: str
    question: str


class SocraticStart(BaseModel):
    """A topic to build a dialogue around.

    No id: unlike an ask's `chat_id`, the dialogue's id is minted by the server
    and returned, because it is an aggregate id, a row key and a URL segment --
    the identical hazard as letting a browser or a model pick one.
    """

    # Constrained because an empty topic is not merely useless: it reaches the
    # model as the whole framing instruction, and a framing that comes back
    # unusable surfaces as a 502 -- blaming the provider for a request that was
    # bad here. 422 from pydantic says the true thing at the true cost (one
    # round trip, no model call). `test_an_empty_topic_is_refused_before_the_model`
    # fails on the constraint being dropped.
    topic: str = Field(min_length=1)


class SocraticReply(BaseModel):
    """What the reader said in answer to the outstanding question.

    Named `reply` and not `question`, matching the domain: on this surface the
    system asks and the reader answers, which is the inverse of the ask.
    """

    reply: str


class SocraticAttempt(BaseModel):
    """One reader's answer to a component the dialogue asked.

    Addressed by `(position, component_id)`, matching `AskAttempt`: a dialogue
    turn has no file path, and the turn is what the server re-parses to recover
    the key. No `at` -- a `SocraticTurnRecorded` is never rewritten, so there is
    no second version to grade against.
    """

    position: int
    component_id: str
    response: Any = None


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


ReembedProject = Callable[[UUID], Awaitable[int]]
"""Re-embed one project's entities from its current graph. Returns how many.

A callable rather than the provider and the stores it needs, for the reason
every other port here is one: this module may not name redstring, and the
work reaches across the graph store, the embedding provider, the event log
and the per-project vector store. Composition owns all four.
"""


def create_app(
    service: SessionService,
    feed: LiveFeed,
    turns: TurnSupervisor,
    lifespan=None,
    approvals: WebApprovals | None = None,
    activity: TurnActivity | None = None,
    corpus: CorpusRunner | None = None,
    blob_store: BlobStorePort | None = None,
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
    asks: AskConversationRunner | None = None,
    dialogues: SocraticDialogueRunner | None = None,
    socratic: SocraticDialogueService | None = None,
    extractor: DocumentExtractor | None = None,
    extract_queue: ExtractionQueue | None = None,
    definitions: DefinitionReaders | None = None,
    ontology: OntologyRunner | None = None,
    ontology_discoverers: OntologyDiscoverers | None = None,
    editor: CorpusEditor | None = None,
    perception: PerceptionPort | None = None,
    perceiver: MediaPerceiver | None = None,
    media_proposals: MediaProposalRunner | None = None,
    media_proposal_repository: AggregateRepository[MediaProposals] | None = None,
    media_accept_worker: MediaAcceptWorker | None = None,
    curation_text: MediaCurationTextPort | None = None,
    curation_search: MediaSearchPort | None = None,
    interactions: EventStoreInteractionRecorder | None = None,
    interaction_reader: InteractionReaders | None = None,
    interaction_failures: InteractionFailures | None = None,
    curriculum: CurriculumService | None = None,
    course_author: CourseAuthor | None = None,
    authoring: AuthoringActivity | None = None,
    reembed: ReembedProject | None = None,
    catalog: CatalogService | None = None,
    catalog_features: CatalogFeatures | None = None,
    catalog_recorder: CatalogFeatureRecorders | None = None,
    course_service: CourseService | None = None,
    course_repository: AggregateRepository[Course] | None = None,
    blurb_sweep: BlurbSweep | None = None,
    blurb_writer: BlurbTextPort | None = None,
    outline_writer: OutlineTextPort | None = None,
    art_store: ArtStore | None = None,
    art_sweep: ArtSweep | None = None,
    art_reroll: ArtReroll | None = None,
    art_generator: ArtGeneratorPort | None = None,
    art_matcher: LibraryArtProvider | None = None,
    settings: SettingsDeps | None = None,
    project_summaries: ProjectSummaries | None = None,
    auth: AuthConfig | None = None,
) -> FastAPI:
    """Build the app around an already-wired service. Composition stays outside.

    `lifespan` is how the composition root gets a foot inside the server's
    event loop. Anything holding a connection bound to the loop that opened it
    -- the `/sessions` projection, in particular -- has to be started there
    rather than at construction time, and this is the only hook the server
    offers for that.
    """
    app = FastAPI(title="research-team", docs_url="/api/docs", lifespan=lifespan)

    app.add_middleware(_InteractionBodyCap)
    # Registered unconditionally, and inert unless `AGENT_AUTH` is on -- see
    # `AuthGate`, whose first branch forwards without reading a cookie when
    # auth is off. Registering it conditionally would mean the two states of
    # this app differ in their middleware stack as well as in their behaviour,
    # and the whole promise of the flag is that `off` is the build that
    # existed before identity did.
    app.add_middleware(AuthGate)
    # `AuthConfig` rather than a bare `enabled` flag, so that a test can point
    # the issuer at a fake ASGI app without setting an environment variable.
    # The default is an auth-off config rather than `None`: `app.state.auth`
    # being absent and being present-and-disabled would otherwise be two
    # distinguishable states with identical intent, and `principal_of` would
    # need to handle both.
    register_auth_routes(
        app,
        auth
        if auth is not None
        else AuthConfig(
            enabled=False,
            client=None,
            signer=SessionSigner.from_config(""),
            sessions=SessionStore(),
            public_url="",
        ),
    )

    # Strong references for `accept_media_proposal`'s fire-and-forget worker
    # runs (Task 11b). `asyncio.create_task` only *weakly* holds its task --
    # nothing else in this closure keeps one alive -- and the event loop is
    # free to garbage-collect a task nobody references, mid-download, with no
    # warning beyond a `Task was destroyed but it is pending` log line. Kept
    # here rather than on `app.state` because nothing outside this module
    # needs to see it; discarded from its own completion callback so the set
    # does not grow for the life of the process.
    media_accept_tasks: set[asyncio.Task] = set()

    async def _load(session_id: UUID):
        try:
            return await service.load(session_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no session {session_id}") from error

    @app.get("/api/sessions")
    async def list_sessions():
        return [summary_view(summary) for summary in await service.list_sessions()]

    @app.get("/api/projects")
    async def list_projects():
        """Every project, with the pipeline position the index draws it from.

        The summaries are read **once for the whole list**, outside the loop,
        which is the only thing worth knowing about this handler. The loop
        below already folds one aggregate per project to find the holder, and
        `domain/project/landing.ts` defers a feature by name on that cost —
        so a summary fetched inside the loop would have doubled the one thing
        this route was already too expensive at, in order to improve the page
        it serves.

        A build with no summaries wired answers zeros rather than 503, which
        is the opposite of what `_reader` and `_topic_reader` do and is
        deliberate: those guard routes that cannot mean anything without their
        collaborator, and this one is the index. A console that cannot count
        a project's sources should still list the project.
        """
        projects = await service.list_projects()
        summaries = await project_summaries.all() if project_summaries else {}
        rows = []
        for project_id, name in projects:
            state = await service.project_state(project_id)
            rows.append(
                project_view(
                    project_id,
                    name,
                    active_session_id=state.active_session_id,
                    tip_at_event=state.tip_at_event,
                    summary=summaries.get(project_id),
                )
            )
        return rows

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
        #
        # Deleted counts as absent here too, so deleting twice is a 404 rather
        # than the domain's 409 "project already deleted". The 409 was the more
        # informative answer and is deliberately given up: a caller who cannot
        # *see* the project through any other route has no way to act on being
        # told it is already gone, and one route treating a deleted project as
        # present -- to refuse it -- is the inconsistency this change exists to
        # remove.
        await _require_project(project_id)
        state = await service.project_state(project_id)
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
        if curriculum is not None:
            # The projection is cached per project and keyed on graph counts,
            # so a project deleted and a new one created under a recycled id
            # would otherwise be answered from the first one's areas. Ids are
            # not recycled today, which is why this is cheap insurance rather
            # than a fix -- the cache holding a dead project's clusters for the
            # life of the process is reason enough on its own.
            curriculum.forget(project_id)
        return {"deleted": True, "project_id": str(project_id)}

    async def _require_project(project_id: UUID) -> None:
        """404 unless `project_id` names a project that exists and is not deleted.

        Checked before touching the corpus so that "no such project" and "that
        project has no sources" stay different answers. Without it an unknown
        id would list empty and read 404, which reads as a project that exists
        and happens to be bare -- and the caller's next move (store something)
        would be the wrong one.

        **A deleted project is a 404, not a 200 with its name in it**, and this
        function is the only place that can say so once: it guards
        seventy-odd project-scoped routes, and until 2026-08-27 it refused
        only the `new` state, so every one of them answered a deleted
        project's reads in full. The write half was never affected --
        `Project.decide` refuses every command against a deleted project
        ("a deleted project answers nothing but 'deleted'") -- which is
        exactly what made the read half hard to notice: nothing could be
        *changed* through those routes, so nothing broke, and a retired
        project simply kept answering questions about itself.

        The same rule already held one layer down and disagreed with this one.
        `event_store.list_projects` filters deleted ids out and its docstring
        says that filter is "what makes deleted mean gone to every caller that
        lists" -- so a deleted project was absent from `/api/projects` and
        present at `/api/projects/{id}`, which is the shape of a bug rather
        than of a convention.

        What it costs: a client holding a URL to a project deleted in another
        tab now gets 404 rather than a page. That is the point. The
        alternative considered was 410 Gone, which is more precise and which
        no client here distinguishes -- `_require_project`'s callers and the
        console both branch on 404 alone, so 410 would buy accuracy nobody
        reads at the price of a second not-found code to handle.
        """
        try:
            state = await service.project_state(project_id)
        except Exception as error:
            raise HTTPException(status_code=404, detail=f"no project {project_id}") from error
        if state.status in ("new", "deleted"):
            raise HTTPException(status_code=404, detail=f"no project {project_id}")

    @app.get("/api/projects/{project_id}")
    async def read_project(project_id: UUID):
        """One project: who it is, and which session holds it.

        Separate from the listing rather than "the row you already fetched",
        because the console reaches a project page by URL as often as by a
        click -- a reload, a bookmark, a link somebody sent -- and on that path
        no listing has been fetched. The alternative was for a project page to
        read `/api/projects` and filter, which is O(projects) of server-side
        fold to answer a question about one.
        """
        await _require_project(project_id)
        state = await service.project_state(project_id)
        return project_detail_view(
            project_id,
            state.name,
            active_session_id=state.active_session_id,
            tip_at_event=state.tip_at_event,
            # The one field the listing beside this does not carry. See
            # `project_detail_view`: a page is reached one at a time, and the
            # listing folds an aggregate per row already.
            reading_head_session_id=reading_head(state),
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
        except CommandRejectedError as error:
            # `decide`'s separator refusal: a `source_id` holding a `/` would be
            # stored and then unreachable, because every route naming a source
            # spends it as one path segment. 400 beside the blank-id refusal
            # rather than 409 -- nothing conflicts, the id is simply not one
            # this API can address. The media route maps the same exception to
            # 409 because there it means a kind clash with a document that
            # exists, which genuinely is a conflict.
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
            # Two of `decide`'s refusals reach here, and only one is a conflict.
            # The first is a `source_id` that already holds *text*, which
            # `_kind_of` will not let media take over -- a real 409. The second
            # is the separator refusal, which is a bad id rather than a clash
            # and would be better as a 400; it is left at 409 because the id on
            # this path comes from the form field or the filename, and a
            # browser does not put a `/` in either, so the case is close to
            # unreachable and splitting the handler would cost more than it
            # buys. If a caller ever hits it, the detail names the `/`.
            # There is no blank-id refusal on this path -- that check
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
        except CommandRejectedError as error:
            # `Corpus.decide`'s refusal for a `StoreSourceDocument` or
            # `StoreDerivedText` this restore re-stores. No reachable case
            # exists today -- the derivedness guards that could have
            # triggered this were fixed before this arm was needed -- but
            # the next guard added to either command would otherwise land
            # here as an unhandled exception and a 500, matching
            # `upload_source`'s pattern.
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
        except CommandRejectedError as error:
            # `decide`'s refusal, which `KnowledgeError` below does not
            # catch. No reachable case exists today -- the derivedness
            # guards that could have triggered this were fixed before this
            # arm was needed -- but the next guard on
            # `StoreSourceDocument`/`StoreSourceMedia`/`StoreDerivedText`
            # would otherwise land here as an unhandled exception and a 500,
            # matching `upload_source`'s pattern.
            raise HTTPException(status_code=409, detail=str(error)) from error
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

    @app.get("/api/projects/{project_id}/sources/ungrouped")
    async def ungrouped_sources(project_id: UUID, include_examined: bool = False):
        """Every extracted document no ontology pass has read. 200, it is a read.

        **`include_examined=true` answers a different question on purpose: every
        extracted document, examined or not.** It is what a re-read is driven
        from, and it exists because "examined" is not "correctly examined". A
        pass records a document as read whether the model stated no classes,
        stated some the verifier refused, or stated some in a chunk whose reply
        was unreadable -- `OntologyDiscoveryService.discover` names all three
        and keeps none of them apart on the event. Measured 2026-08-24 on the
        owner's corpus: of two examined documents, one genuinely stated none and
        one stated `interactive components` {mcq, cloze, flashcard} and had it
        dropped because the quoted evidence spanned a hard line wrap and so was
        not found verbatim. Both render as "states no classes" and neither is
        reachable from the default list ever again.

        So the parameter is the cheap half of that fix: it does not make the
        verifier better, it makes a second attempt possible after someone has.
        The expensive half -- a locator that tolerates wrapping -- is a separate
        change, and this one is worth having without it because the model is
        not deterministic either.

        The name is `include_examined` rather than `all`, because it says which
        exclusion is being lifted. The other two -- unextracted, and media --
        still apply, and a re-read wants them to: neither is a document a pass
        could have got wrong.

        Re-reading is safe rather than merely permitted. `OntologyDiscovered`
        replaces a source's classes wholesale and the projection keys on
        `source_id`, so a second pass over a document that already has classes
        supersedes them rather than duplicating them. What it costs is one model
        call per document, which is why nothing does this on a schedule.

        Registered inside the literal-segment block above for that block's
        reason: `ungrouped` would otherwise be read as a `{source_id}` by
        `GET /sources/{source_id}`, which is the bug that block records
        happening twice already.

        **This route is the join `DocumentExtractor.ungrouped` was written
        for.** That method takes `examined` as a parameter rather than fetching
        it, deliberately -- it knows the corpus and the graph, and the ontology
        tables belong to a projection it has no reason to depend on. So the two
        halves have sat in the tree unconnected, with tests on each and nothing
        driving both: `ungrouped()` had no production caller at all, and the
        sweep it describes had never run. That is the `CoMentionPort` shape
        this repository has met before, caught here before it could ship.

        **503 when either half is unwired, not an empty 200**, for
        `read_ontology`'s reason and more sharply. An empty list is the correct
        answer for a corpus that has been fully grouped, so a misconfigured
        build answering the same thing tells a reader "there is nothing left to
        do" about a project nothing has ever examined -- and the control this
        backs would render as finished on exactly the project that needs it
        most.

        `sourceIds` in camelCase, unlike `source_ids` on the extract-all
        neighbour below. The two disagree and this one follows the ontology
        payloads it is read beside; the neighbour is not changed here because
        its shape is already in a client.
        """
        if extractor is None or ontology is None:
            raise HTTPException(status_code=503, detail="ontology discovery is not configured")
        await _require_project(project_id)
        examined: set[str] = set()
        if not include_examined:
            examined = await ontology.sources_with_classes(project_id)
        pending = await extractor.ungrouped(project_id, examined=examined)
        return {"sourceIds": list(pending)}

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

    @app.post("/api/projects/{project_id}/sources/{source_id}/perceive")
    async def perceive_source(project_id: UUID, source_id: str):
        """Queue one stored medium for perception. 202, because it has not run.

        **Queued rather than run inline, and through the extraction queue
        rather than one of its own.** Transcribing an hour of audio takes
        minutes, which is longer than any client should hold a connection, and
        it is the same kind of slow thing happening to the same source rows --
        so it reports through `ExtractionActivity` (stages `perceiving` and
        `perceived`) and waits behind whatever else that project has running.
        A second pane and a second queue would be a second thing to watch and
        a second thing to cancel, for one workflow. See `extraction_queue.py`.

        **Everything that can be refused is refused here, before the enqueue.**
        A 404 delivered later through a progress pane is a 404 nobody connects
        to the button they pressed. `perceiver.resolve` is what draws the four
        source-side distinctions -- it is the same call `perceive` makes when
        the job starts, so the route and the job cannot drift -- and the
        capability check is separate because it is not about this source at
        all. The mapping:

        - **404** no such media source. A typo, or an ingest that never ran.
        - **409** the id holds text. There is nothing in prose to perceive,
          and this is not the same mistake as a typo.
        - **409** the source was dropped, with the reason. It exists and
          somebody excluded it on purpose; restoring it is the operator's move
          and the detail says so, because "no such source" would send them
          looking for an ingest that did happen.
        - **410** the record is here and its blob is not, matching what
          `/content` already answers for the same dangling reference one click
          away.
        - **503** this install has no vision model and no transcriber, naming
          which, because a refusal that can only say "not configured" sends
          nobody anywhere. Not 501: the route exists and the install is short
          of something an operator can supply.

        The capability check is synchronous (`capabilities()` is, on purpose)
        and happens at the route rather than in the job, so an unconfigured
        install refuses the press instead of accepting work it cannot do and
        failing a minute later.

        `queued: false` is still a 202, for `extract_source`'s reason: the
        medium *is* going to be perceived, because it is already queued.
        """
        if perceiver is None or perception is None or extract_queue is None:
            raise HTTPException(status_code=503, detail="perception is not configured")
        await _require_project(project_id)
        try:
            await perceiver.resolve(project_id, source_id)
        except UnknownDocument as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except NotPerceivable as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except SourceDropped as error:
            raise HTTPException(
                status_code=409,
                detail=f"{error}; restore it first if it should inform this project",
            ) from error
        except MediaBytesMissing as error:
            raise HTTPException(status_code=410, detail=str(error)) from error

        capabilities = perception.capabilities()
        if not capabilities.any_model():
            raise HTTPException(
                status_code=503,
                detail=(
                    "this install cannot perceive media: " + "; ".join(capabilities.missing())
                ),
            )

        queued = extract_queue.start(
            project_id, source_id, _perception_of(project_id, source_id)
        )
        return JSONResponse(
            status_code=202, content={"queued": queued, "source_id": source_id}
        )

    def _perception_of(project_id: UUID, source_id: str):
        """A factory the queue can await later -- `_extraction_of`'s shape.

        Returns `None` rather than an `IngestReport`: perception extracts
        nothing, and reporting `entities: 0` for a finished transcription
        would read as "extraction found nothing" instead of "no extraction
        happened". `_drain` omits both counts for a `None`.

        The `failed` note is reported here rather than left to the queue,
        because the queue publishes nothing: without it a perception that
        raised would leave the pane on `perceiving` forever, with the only
        account of the failure sitting in a catch-up route nothing refetches.
        The exception is re-raised so the queue still records the outcome.

        **No route status for `PerceivedTextTooLong`, and that is not an
        omission.** This runs behind the 202 already answered above, so there
        is nothing left to map it to -- B93's ruling. `except Exception`
        below is broad enough to catch it along with everything else this
        path can raise; it lands on the pane as a `failed` note with the cap
        and the actual length in `detail`, the same as any other perception
        failure.
        """
        assert perceiver is not None  # the route guards above

        def _note(note: ExtractionNote) -> None:
            if extraction is not None:
                extraction.reporter(project_id)(note)

        async def run():
            _note(ExtractionNote(source_id=source_id, stage="perceiving"))
            try:
                report = await perceiver.perceive(project_id, source_id)
            except Exception as error:
                _note(ExtractionNote(source_id=source_id, stage="failed", detail=str(error)))
                raise
            _note(
                ExtractionNote(
                    source_id=source_id,
                    stage="perceived",
                    detail=(
                        f"{report.char_count} characters as {report.source_id}"
                        + (
                            f"; {'; '.join(report.degradations)}"
                            if report.degradations
                            else ""
                        )
                    ),
                )
            )
            return None

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

    _interaction_kinds = {event_type.__name__: event_type for event_type in INTERACTION_EVENTS}

    _INTERACTION_ENVELOPE_KEYS = ENVELOPE_FIELDS
    """Every field the event envelopes own, imported rather than listed.

    `envelope.payload` is splatted onto the constructor alongside the keyword
    arguments the route supplies, so a payload key that names an envelope
    field is either a `TypeError` ("got multiple values for keyword
    argument") for the eight the route passes explicitly, or -- far worse --
    a silent write for the nine it does not. `actor_id`, `tenant_id`,
    `causation_id` and `metadata` are free-form on `DomainEvent`, so a
    payload carrying one wrote arbitrary user text into the store, *outside*
    `TEXT_BEARING_FIELDS`, and `row_for` then stripped it back out of the
    row -- leaving it only in the `events` blob, the one place someone
    inspecting the log by hand would not look. `aggregate_type` could also be
    set to disagree with the `StreamId` the recorder appends under.

    Derived from the models rather than hand-picked because the hand-picked
    version is exactly the defect above: this branch shipped with eight of
    the seventeen named. `ENVELOPE_FIELDS` is the same expression the
    projection uses to strip these keys out of a stored payload, so the two
    directions cannot drift apart. Nothing legitimate collides -- payload
    fields are kind-specific (`params`, `dwell_ms`, `query_text`, ...).
    """

    @app.post("/api/interactions")
    async def post_interactions(body: InteractionBatch):
        """Record what the console's user did. Capture only; nothing reads
        this back.

        Answers 202 with counts rather than rejecting a batch that contains
        one bad event. The client cannot see this response -- it is delivered
        by `sendBeacon` on page-hide, which reports nothing -- so a
        whole-batch rejection would silently discard the good events beside
        the bad one. Partial acceptance loses one event instead of fifty.

        The counts are returned anyway, for a human with curl.
        """
        if interactions is None:
            raise HTTPException(
                status_code=503, detail="the interaction log is not collecting"
            )

        received = datetime.now(UTC)
        events: list[InteractionEvent] = []
        rejected = 0
        for raw in body.events:
            try:
                envelope = InteractionEnvelope.model_validate(raw)
            except ValidationError:
                # The envelope itself doesn't match the shape every kind
                # shares (a missing `view`, a bad UUID). Counted alongside a
                # bad `kind` and a bad `payload` below: see the docstring.
                rejected += 1
                continue
            event_type = _interaction_kinds.get(envelope.kind)
            if event_type is None:
                rejected += 1
                continue
            if not _INTERACTION_ENVELOPE_KEYS.isdisjoint(envelope.payload):
                # A payload carrying an envelope-owned key (e.g. `seq`)
                # would otherwise collide with the explicit keyword below
                # and raise `TypeError`, not `ValidationError` -- see
                # `_INTERACTION_ENVELOPE_KEYS`. The envelope is the
                # authority for these fields; payload content never
                # overrides them, so the event is rejected rather than
                # silently dropping either value.
                rejected += 1
                continue
            try:
                events.append(
                    event_type(
                        aggregate_id=envelope.browser_session_id,
                        install_id=envelope.install_id,
                        seq=envelope.seq,
                        view=envelope.view,
                        occurred_at=envelope.occurred_at,
                        project_id=envelope.project_id,
                        session_id=envelope.session_id,
                        received_at=received,
                        **envelope.payload,
                    )
                )
            except (ValidationError, TypeError):
                # One event's payload not matching its kind. Counted, not
                # raised: see the docstring. `TypeError` is belt-and-braces
                # here, not the primary defense -- the collision check above
                # is what actually stops an envelope-owned key from reaching
                # the constructor; this only catches whatever that check
                # didn't anticipate.
                rejected += 1

        accepted = await interactions.record(events)
        return JSONResponse(
            status_code=202,
            content={"accepted": accepted, "rejected": rejected},
        )

    def _interaction_log_reader() -> InteractionLogReader:
        """The reader, or 503 naming why there is none.

        Gated on the *reader*, never on `interactions`: `AGENT_INTERACTION_LOG=0`
        switches off the recorder while the runner still starts and the table
        still exists, and the honest answer there is an empty log with
        `collecting: false`. 503ing on the recorder's absence would make
        "switched off" and "broken" the same response, which is the one
        distinction this whole surface exists to draw.
        """
        reader = interaction_reader() if interaction_reader is not None else None
        if reader is None:
            raise HTTPException(
                status_code=503, detail="the interaction log reader is not configured"
            )
        return reader

    def _interaction_kind_filter(kinds: list[str] | None) -> list[str] | None:
        """The requested kinds, or 422 naming the one that is not a kind.

        422 rather than returning nothing, because on the server an
        unrecognised kind is a caller error and an empty page is what a
        *correct* filter over a quiet log looks like. Silence here would be
        indistinguishable from the instrument having stopped -- the exact
        confusion this surface is for.
        """
        if not kinds:
            return None
        unknown = [kind for kind in kinds if kind not in _interaction_kinds]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"unknown interaction kind(s): {', '.join(sorted(unknown))}",
            )
        return kinds

    def _interaction_window(
        since: str | None, until: str | None
    ) -> tuple[datetime | None, datetime | None]:
        """`since`/`until` as instants, naive spellings read as UTC.

        The reader calls `astimezone` on both bounds, which reads a naive
        datetime as *local* time -- so a bare `2026-08-25T00:00:00` would
        select a different window on a laptop in Berlin than on one in UTC,
        and neither would look wrong. Pinned here rather than in the reader
        because this is the seam where a string becomes a datetime.
        """
        bounds = []
        for name, raw in (("since", since), ("until", until)):
            moment = _instant(name, raw)
            if moment is not None and moment.tzinfo is None:
                moment = moment.replace(tzinfo=UTC)
            bounds.append(moment)
        return bounds[0], bounds[1]

    @app.get("/api/interactions/health")
    async def read_interaction_health():
        """Is the instrument working, and how much has it seen.

        Three sources, and the split is deliberate. `collecting` is whether the
        *recorder* was wired -- a fact about `AGENT_INTERACTION_LOG` that only
        this layer can see. `failures` is the projection's DLQ, which belongs
        to the runner. Everything else is a query over the table. A reader that
        reported all three would be guessing at two of them.

        `kinds` carries every name in `INTERACTION_EVENTS`, zeros included:
        that is the reader's doing, and the test derives the expected set from
        the tuple rather than listing it.
        """
        reader = _interaction_log_reader()
        health = await reader.health()
        failures = await interaction_failures() if interaction_failures is not None else []
        return {
            "collecting": interactions is not None,
            "total": health.total,
            "first_at": health.first_at,
            "last_at": health.last_at,
            "kinds": health.kinds,
            "failures": [
                {
                    "id": str(entry.id),
                    "event_type": entry.event_type,
                    "error": entry.error_message,
                    "failed_at": entry.last_failed_at or entry.first_failed_at,
                }
                for entry in failures
            ],
            "install_count": health.install_count,
            "session_count": health.session_count,
        }

    @app.get("/api/interactions/sessions")
    async def read_interaction_sessions(
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        install_id: UUID | None = None,
        project_id: UUID | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> BrowserSessionPage:
        """One row per browser session, newest first.

        `limit` over 500 is a 422 rather than a clamp, and the choice is not
        the one `read_timeline` made. There, `truncated` in the body tells the
        caller the clamp happened; here a clamped page and a complete one are
        the same JSON, so a caller asking for 800 and receiving 500 would read
        it as the whole answer.
        """
        reader = _interaction_log_reader()
        window_since, window_until = _interaction_window(since, until)
        return await reader.sessions(
            limit=limit,
            offset=offset,
            install_id=install_id,
            project_id=project_id,
            since=window_since,
            until=window_until,
        )

    @app.get("/api/interactions/sessions/{browser_session_id}")
    async def read_interaction_session(
        browser_session_id: UUID,
    ) -> dict[str, list[InteractionEventRow]]:
        """One browser session's whole stream, `seq` ascending.

        404 when no row carries that id -- the reader answers `None` rather
        than `[]` precisely so this route can tell an unknown session from a
        real one, and a bare empty list could not.

        Unpaged, per the spec: a browser session is bounded by a tab's life.
        There is still an `events` envelope rather than a bare JSON array,
        matching `/events` and `/sessions`: three collection routes under one
        prefix that disagree about their outermost shape is a decoder written
        twice, and the spec's own example bodies are objects throughout. It
        also leaves somewhere for a later `total` or a truncation flag to go
        without breaking a client, which a top-level array does not.
        """
        reader = _interaction_log_reader()
        events = await reader.session(browser_session_id)
        if events is None:
            raise HTTPException(
                status_code=404,
                detail=f"no interactions for browser session {browser_session_id}",
            )
        return {"events": events}

    @app.get("/api/interactions/events")
    async def read_interaction_events(
        kind: Annotated[list[str] | None, Query()] = None,
        view: Annotated[list[str] | None, Query()] = None,
        project_id: UUID | None = None,
        session_id: UUID | None = None,
        install_id: UUID | None = None,
        browser_session_id: UUID | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = Query(default=200, ge=1, le=1000),
        offset: int = Query(default=0, ge=0),
        order: Literal["newest", "oldest"] = "newest",
    ) -> InteractionEventPage:
        """A page of events under the filters, with the count under the same
        filters beside it.

        `total` is not the page length: a reader who cannot tell 200-of-200
        from 200-of-9000 cannot tell a filter that found everything from one
        that hit the cap.

        `kind` and `view` repeat. An unknown `kind` is 422; an unknown `view`
        is not, because the view vocabulary is the console's route names rather
        than a closed tuple, and a view that no longer exists is a legitimate
        thing to ask an old log about.
        """
        reader = _interaction_log_reader()
        window_since, window_until = _interaction_window(since, until)
        return await reader.events(
            kinds=_interaction_kind_filter(kind),
            views=view or None,
            project_id=project_id,
            session_id=session_id,
            install_id=install_id,
            browser_session_id=browser_session_id,
            since=window_since,
            until=window_until,
            limit=limit,
            offset=offset,
            order=order,
        )

    @app.get("/api/interactions/summary")
    async def read_interaction_summary(
        kind: Annotated[list[str] | None, Query()] = None,
        view: Annotated[list[str] | None, Query()] = None,
        project_id: UUID | None = None,
        session_id: UUID | None = None,
        install_id: UUID | None = None,
        browser_session_id: UUID | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> InteractionSummary:
        """Aggregates over the same window `/events` pages.

        No `limit`: the aggregate is over every matching row, and a paged
        aggregate would be a different number wearing the same name.
        """
        reader = _interaction_log_reader()
        window_since, window_until = _interaction_window(since, until)
        return await reader.summary(
            kinds=_interaction_kind_filter(kind),
            views=view or None,
            project_id=project_id,
            session_id=session_id,
            install_id=install_id,
            browser_session_id=browser_session_id,
            since=window_since,
            until=window_until,
        )

    @app.post("/api/projects/{project_id}/topics/seed")
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
        deliberately differs from `seed_topics`, and `dispatch.py`'s module
        docstring carries the argument: that one backs a control that appears
        once on a page, where refusing a second press is correct. This one
        backs a control on every topic row, where refusing would be the answer
        to nearly every second press.

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

    @app.post("/api/projects/{project_id}/dispatch/bulk")
    async def dispatch_topics(project_id: UUID, body: BulkDispatch):
        """Enqueue one action across the topics the client named. 202, like the one.

        Registered after `/dispatch/cancel` and before nothing that could
        shadow it -- `/dispatch/{...}` does not exist, so declaration order
        carries no risk here, unlike the `/topics/{topic_id}` family above.

        **The scope comes from the client and there is no "all".** A route that
        took "all" would have to define it against a queue the browser is
        filtering, and the two definitions would drift; see `BulkDispatch`.
        The safety property this buys is that the count on screen (`Needs you
        3`) and the number of turns started are the same number by
        construction, rather than by two pieces of code agreeing.

        **One `DispatchQueue.start` per topic, and deliberately not a second
        queue.** The existing queue is already FIFO, already one-in-flight per
        project, already cancellable in one press, and already renders
        `1 running, 11 queued`. A bulk queue beside it would be a second
        drain competing for the one thing `Project.decide` refuses to share.
        So this route is a loop, and the progress surface for it already
        exists.

        Unknown topic ids are reported rather than refused. The list a browser
        sends is what it was showing a moment ago, and a topic deleted in that
        moment would otherwise cost the other forty-nine their dispatch -- an
        outcome much worse than the mistake. They come back in `unknown` so a
        client can say so instead of silently starting fewer than it asked
        for.

        The list length is capped by `BulkDispatch` rather than here, so an
        over-long request is refused by FastAPI's own 422 before any topic is
        resolved -- no half-enqueued queue to unwind.
        """
        if dispatcher is None or dispatch is None:
            raise HTTPException(status_code=503, detail="topic dispatch is not configured")
        await _require_project(project_id)

        if body.action not in DISPATCH_ACTIONS:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"no dispatch action {body.action!r}; this build offers "
                    f"{', '.join(sorted(DISPATCH_ACTIONS))}"
                ),
            )

        reader = _topic_reader(project_id)
        queued: list[dict[str, Any]] = []
        unknown: list[str] = []
        # Sequential rather than gathered: `read_topic` hits the same read
        # model each time and the list is capped at fifty, so concurrency buys
        # nothing measurable and costs the deterministic enqueue order the
        # queue's positions are numbered from. A person who pressed this on a
        # sorted list expects the first row to run first.
        for topic_id in body.topic_ids:
            detail = await reader.read_topic(topic_id)
            if detail is None:
                unknown.append(str(topic_id))
                continue
            queued.append(
                dispatch.start(
                    project_id,
                    topic_id,
                    body.action,
                    # `topic_id=topic_id` binds the loop variable per
                    # iteration. Without it every closure would close over the
                    # last one and all fifty dispatches would run the same
                    # topic -- the classic late-binding defect, and one no
                    # type checker here would catch.
                    lambda dispatch_id, topic_id=topic_id: dispatcher.dispatch(
                        project_id, topic_id, body.action, dispatch_id=dispatch_id
                    ),
                    question=detail.view.summary.question,
                )
            )
        return JSONResponse(
            status_code=202,
            content={
                "queued": [dispatch_view(frame) for frame in queued],
                "unknown": unknown,
            },
        )

    def _media_proposal_view(row: MediaProposalRow) -> dict[str, Any]:
        return {
            "proposal_id": row.proposal_id,
            "need_id": row.need_id,
            "topic_id": row.topic_id,
            "page_url": row.page_url,
            "asset_url": row.asset_url,
            "thumbnail_url": row.thumbnail_url or None,
            "kind": row.kind,
            "title": row.title,
            "reason": row.reason,
            "query": row.query,
            "status": row.status,
            "note": row.note or None,
            "source_id": row.source_id,
            "error": row.error,
        }

    def _media_proposal_groups(rows: list[MediaProposalRow]) -> list[dict[str, Any]]:
        """Rows grouped by need, each group labelled with `need_description`.

        A `dict` keyed by `need_id` rather than a `groupby` over a sorted
        list: `for_project`'s rows already arrive in one project's insertion
        order, and a `dict`'s insertion-order iteration preserves that --
        "the order proposals were found in" -- without a sort that would
        reorder them by an id nobody chose for display.
        """
        groups: dict[str, dict[str, Any]] = {}
        for row in rows:
            group = groups.setdefault(
                row.need_id,
                {
                    "need_id": row.need_id,
                    "need_description": row.need_description,
                    "proposals": [],
                },
            )
            group["proposals"].append(_media_proposal_view(row))
        return list(groups.values())

    def _host_of(url: str) -> str:
        """Duplicated from `domain/media_proposals.py`'s own `_host_of`
        rather than imported: that function is private to the aggregate
        module, for the same reason `application/media_curation.py` gives its
        own copy -- this must agree with `decide`'s key derivation or an
        asset ignored here by host could still be proposed there.
        """
        return (urlsplit(url).hostname or "").lower()

    def _curation_service(project_id: UUID) -> MediaCurationService:
        """The three-stage chain, wired for one project's topics.

        Built per request rather than held on the app, mirroring `_reader`
        and `_editor`: `MediaCurationService.topics` is one project's
        `TopicReadPort` (`_topic_reader` below), and a single shared instance
        would either leak one project's topics into another's `curate` call
        or have to take the project as a second argument the port refuses to
        accept for exactly this reason.

        503 when any of the three optional dependencies it needs --
        `media_proposal_repository`, `curation_text`, `curation_search` --
        was not wired, matching every other optional feature in this module.
        """
        if (
            media_proposal_repository is None
            or curation_text is None
            or curation_search is None
        ):
            raise HTTPException(status_code=503, detail="media curation is not configured")
        return MediaCurationService(
            text=curation_text,
            search=curation_search,
            proposals=media_proposal_repository,
            topics=_topic_reader(project_id),
        )

    # The six routes below share one path prefix
    # (`/media-proposals`/`/ignored`) but no two share both a method and a
    # path shape, so declaration order cannot make one shadow another --
    # unlike `upload_media` and `/sources/{source_id}/drop`, nothing here is
    # a literal segment competing with a same-method `{param}` segment one
    # route down. Grouped together anyway, in the order a proposal moves
    # through its lifecycle (propose, list, accept/reject/ignore, then the
    # ignore lists), because that is the order a reader benefits from.

    @app.post("/api/projects/{project_id}/topics/{topic_id}/media-proposals")
    async def run_media_curation(project_id: UUID, topic_id: UUID):
        """Run the three-stage chain once for this topic. 202: what changed
        is a fact on the log by the time this answers, not a promise the
        caller waits on -- but the interesting state (the proposals
        themselves) is read back through `GET .../media-proposals`, not this
        response, the way `dispatch_topic` above treats its own 202.
        """
        await _require_project(project_id)
        service = _curation_service(project_id)
        try:
            outcome = await service.curate(project_id, topic_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CurationUnavailable as error:
            # An unreachable SearXNG instance or an unreachable model
            # endpoint -- the two most likely operational failures of this
            # feature -- previously propagated uncaught to an unhandled 500.
            # 502: this route is itself acting as a gateway to two other
            # services, and the failure is theirs, not a defect in this
            # route's own logic -- the honest report the review asked for,
            # rather than treating the run as though it produced zero
            # candidates.
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

    @app.get("/api/projects/{project_id}/media-proposals")
    async def list_media_proposals(project_id: UUID):
        """Every proposal in the project, grouped by the need that produced it.

        Empty rather than 503 when `media_proposals` was not wired: a build
        with no proposal read model has no proposals to show, which is a
        legitimate state for a project that has never run the chain, matching
        `get_dispatch`'s reasoning for its own optional dependency above.
        """
        await _require_project(project_id)
        if media_proposals is None:
            return []
        return _media_proposal_groups(await media_proposals.for_project(project_id))

    @app.post("/api/projects/{project_id}/media-proposals/{proposal_id}/accept")
    async def accept_media_proposal(project_id: UUID, proposal_id: str):
        """Record the decision, then hand the download off to `MediaAcceptWorker`.

        Still 202, and still answered before anything is fetched: the append
        below is the only part this request waits on. `MediaAcceptWorker.run`
        is scheduled with `asyncio.create_task` rather than awaited, because it
        downloads and perceives -- an hour of audio is minutes of transcription
        -- and a route that waited on that would be a route that times out.
        `media_accept_tasks` is what keeps the scheduled task alive; see its
        comment above `create_app`'s body for why a bare `create_task` is not
        enough on its own.

        No queue, unlike `ExtractionQueue`/`DispatchQueue`: those serialize
        because running two of a kind at once means racing writes to a shared
        resource (one extraction pass per project) or asking twice for the same
        research. An accept has neither problem -- each proposal downloads and
        stores into its own corpus row, `source_id=proposal_id`, so two accepts
        for two different proposals racing costs nothing a queue would have
        saved. `MediaAcceptWorker`'s own docstring is what makes even the
        crash-and-retry case safe without one.

        A logged exception, not a crashed task, is where a bug in the worker
        that is *not* one of its four named refusals ends up: nothing awaits
        this task, so nothing else would ever see it raise.
        """
        await _require_project(project_id)
        if media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await media_proposal_repository.load_or_create(project_id)
        try:
            aggregate.execute(
                AcceptMediaProposal(project_id=str(project_id), proposal_id=proposal_id)
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await media_proposal_repository.save(aggregate)

        if media_accept_worker is not None:

            async def _run_accept_worker() -> None:
                try:
                    await media_accept_worker.run(proposal_id)
                except Exception:
                    logger.exception(
                        "media accept worker failed for proposal %s in project %s",
                        proposal_id,
                        project_id,
                    )

            task = asyncio.create_task(_run_accept_worker())
            media_accept_tasks.add(task)
            task.add_done_callback(media_accept_tasks.discard)

        return JSONResponse(
            status_code=202, content={"proposal_id": proposal_id, "status": "accepted"}
        )

    class RejectMediaProposalBody(BaseModel):
        note: str = ""

    @app.post("/api/projects/{project_id}/media-proposals/{proposal_id}/reject")
    async def reject_media_proposal(
        project_id: UUID, proposal_id: str, body: RejectMediaProposalBody | None = None
    ):
        """Close the record without touching `ignored_assets`/`ignored_hosts`
        -- see the module docstring's "Rejecting is not blacklisting". The
        note is optional because most rejections are obvious, matching
        `MediaProposalRejected`'s own reasoning.
        """
        await _require_project(project_id)
        if media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await media_proposal_repository.load_or_create(project_id)
        try:
            aggregate.execute(
                RejectMediaProposal(
                    project_id=str(project_id),
                    proposal_id=proposal_id,
                    note=(body.note if body is not None else ""),
                )
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await media_proposal_repository.save(aggregate)
        return {"proposal_id": proposal_id, "status": "rejected"}

    class IgnoreMediaProposalBody(BaseModel):
        grain: Literal["asset", "host"]

    @app.post("/api/projects/{project_id}/media-proposals/{proposal_id}/ignore")
    async def ignore_media_proposal(
        project_id: UUID, proposal_id: str, body: IgnoreMediaProposalBody
    ):
        """Ignore the asset or host behind one proposal, keyed off the
        proposal's own recorded `asset_url` -- not a second identifier the
        caller has to already know, unlike `DELETE .../ignored/{grain}/{key}`
        below, which exists precisely for the case where they do (the ignore
        lists, with no proposal attached).

        404 for an unknown `proposal_id`: `decide`'s `IgnoreMediaAsset` and
        `IgnoreMediaHost` cases carry no unknown-id guard of their own (the
        module's transition table only guards commands that name a proposal
        directly), so this route checks existence itself before deriving a
        key from a record that is not there -- a `CommandRejectedError`
        never gets the chance to fire, so there is nothing to map to 409.
        """
        await _require_project(project_id)
        if media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await media_proposal_repository.load_or_create(project_id)
        record = aggregate.state.proposals.get(proposal_id)
        if record is None:
            raise HTTPException(
                status_code=404, detail=f"no proposal {proposal_id!r} in project {project_id}"
            )
        command = (
            IgnoreMediaAsset(project_id=str(project_id), asset_key=record.asset_url)
            if body.grain == "asset"
            else IgnoreMediaHost(project_id=str(project_id), host=_host_of(record.asset_url))
        )
        try:
            aggregate.execute(command)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await media_proposal_repository.save(aggregate)
        return {"proposal_id": proposal_id, "grain": body.grain}

    @app.delete("/api/projects/{project_id}/ignored/{grain}/{key:path}")
    async def unignore_media(project_id: UUID, grain: Literal["asset", "host"], key: str):
        """Reverse an ignore at either grain, by the same key `GET .../ignored`
        reports -- see the module docstring's "both are reversible".

        `{key:path}` rather than the default converter: an asset key is a
        whole URL (`normalize_url`'s output), which contains `/`, and the
        default converter stops at the first one -- `example.com/pic.jpg`
        would 404 as an unmatched route rather than reach this handler. A
        host key never contains `/`, but the same converter serves both
        grains rather than branching the route in two.
        """
        await _require_project(project_id)
        if media_proposal_repository is None:
            raise HTTPException(status_code=503, detail="media proposals are not configured")
        aggregate = await media_proposal_repository.load_or_create(project_id)
        command = (
            UnignoreMediaAsset(project_id=str(project_id), asset_key=key)
            if grain == "asset"
            else UnignoreMediaHost(project_id=str(project_id), host=key)
        )
        try:
            aggregate.execute(command)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await media_proposal_repository.save(aggregate)
        return {"grain": grain, "key": key}

    @app.get("/api/projects/{project_id}/ignored")
    async def get_ignored(project_id: UUID):
        """Both ignore lists at once -- the pane that shows one shows both.

        Empty rather than 503 when unwired, matching `list_media_proposals`.
        """
        await _require_project(project_id)
        if media_proposals is None:
            return {"assets": [], "hosts": []}
        return {
            "assets": sorted(await media_proposals.ignored_assets(project_id)),
            "hosts": sorted(await media_proposals.ignored_hosts(project_id)),
        }

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
        return ProjectGraphReader(project_id=project_id, store=store, ontology=ontology)

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
        definition = await service.define(entity_id)
        served = None
        if definition is not None and corpus is not None and blob_store is not None:
            # Resolved here rather than inside `DefinitionService`, so a
            # `Definition` fetched from cache is never the thing that goes
            # stale -- see `ServedCitation`'s docstring. `corpus`/`blob_store`
            # are checked rather than routed through `_reader` (which 503s):
            # a build with a definition service but no corpus read model
            # should still answer with a definition, just without moments,
            # not lose the whole route over a field it only decorates.
            served = await serve_citations(_reader(project_id), definition.citations)
        return definition_view(definition, served)

    @app.post("/api/projects/{project_id}/sources/{source_id}/ontology")
    async def discover_ontology(project_id: UUID, source_id: str, strict: bool = True):
        """Read one document for the classes it states. 200, because it has run.

        **Synchronous, unlike extraction, and for `read_graph_definition`'s
        reason.** `ExtractionQueue` exists because extraction is long-running
        and a request that loses a queued extraction loses an intention the
        caller cannot easily re-express. A discovery pass is one model call over
        one document, produces the same answer from the same inputs, and a
        failed request costs the caller a second click -- so the whole retry
        story is "click again".

        It also *could not* reuse that queue as it stands. `ExtractionQueue`
        deduplicates on `(project_id, source_id)` and reads
        `report.entity_count` off whatever it awaited, so queuing a pass for a
        document already queued for extraction would be silently dropped and
        answered `queued: false` -- which the client reads as "this is going to
        happen", when what is going to happen is the extraction, not the pass.
        Making it fit means changing a component another lane owns.

        **`strict=false` reads the document under the weaker rule** that
        `verify_classes` documents: a class whose quoted sentence is not in the
        text survives if all its members are, cited to the first member's
        occurrence and flagged `evidenceQuoted: false` on the way back out.
        Default true, because a reader who has not asked for it must not be
        handed classes the document may never have grouped.

        A query parameter and not a body field, on a POST, which is the odd
        choice here. The body is `{}` and stays that way: this route already
        carries its subject in the path, and a caller reading the URL sees the
        whole request -- which matters more than usual for a lever whose two
        settings answer different questions about the same document.

        **`found: null` rather than 404 when the pass declines.** The three
        declines -- an unreadable reply, a document over
        `MAX_DISCOVERY_CHARS`, and a source that is not there -- are told apart
        above by the 404 and below by nothing, deliberately: see
        `OntologyDiscoveryService.discover`. `found: 0` is a different answer
        again, and the important one to keep distinct: it means the document was
        read and states no classes.
        """
        await _require_project(project_id)
        if ontology_discoverers is None:
            raise HTTPException(status_code=503, detail="no ontology service is configured")
        if await _reader(project_id).read_document(source_id) is None:
            raise HTTPException(
                status_code=404, detail=f"no source {source_id!r} in project {project_id}"
            )
        found = await ontology_discoverers(project_id).discover(source_id, strict=strict)
        return {"sourceId": source_id, "found": found}

    @app.get("/api/projects/{project_id}/ontology")
    async def read_ontology(project_id: UUID):
        """Every class discovered in this project, with what it was derived from.

        **503 when the runner is unwired, not an empty 200.** An empty list is
        the correct answer for a project nobody has run a pass on, so a
        misconfigured build answering the same thing would be indistinguishable
        from a working one with nothing to show -- which is the whole failure
        this feature is arranged against, arriving at the last layer.

        Every field a reader needs to judge a class travels with it. `evidence`
        is offsets into the source document, not a quotation: the view opens the
        document there, and quoted text proves only that the model wrote a
        sentence, where opening the document proves the sentence is in it.
        `declaredCount` beside `memberCount` is the checksum, and
        `rejectedMembers` is what explains a gap between them -- a class short
        one member with no explanation cannot be judged, because an invented
        member and a document genuinely missing one look identical.
        """
        await _require_project(project_id)
        if ontology is None:
            raise HTTPException(status_code=503, detail="no ontology service is configured")
        classes = []
        for row in await ontology.classes_for(project_id):
            members = await ontology.members_for(row.id)
            classes.append(
                {
                    "id": str(row.id),
                    "name": row.name,
                    "kind": row.kind,
                    "declaredCount": row.declared_count,
                    "memberCount": row.member_count,
                    "parentClassId": str(row.parent_class_id) if row.parent_class_id else None,
                    "evidence": {
                        "sourceId": row.source_id,
                        "start": row.evidence_start,
                        "end": row.evidence_end,
                    },
                    "rejectedMembers": json.loads(row.rejected_members),
                    # Travels beside `evidence` rather than being inferred from
                    # it, because nothing about the offsets says which they are
                    # -- a member fallback and a located sentence are both a
                    # pair of integers into the same document.
                    "evidenceQuoted": row.evidence_quoted,
                    "stale": row.stale,
                    "members": [
                        {"name": member.member_name, "ordinal": member.ordinal}
                        for member in members
                    ],
                }
            )
        return {"classes": classes}

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

    async def _co_mentions(project_id: UUID) -> RecordedCoMentions:
        """This project's `CoMentionPort`, over the co-mention index `graphs` owns.

        **`graphs.co_mentions`, not `graphs.chunks`.** The retrieval corpus is
        filled by `index_documents`, which has no entity knowledge and writes
        every chunk with an empty `entity_ids` -- so this route answered 200
        with nothing in it for the whole life of the feature. The index holds
        the *extraction* chunking's links, folded from the same log.

        The graph store goes in as well, because recorded links are
        pre-consolidation ids; see `RecordedCoMentions`.

        `graphs.open` first and the store lookups second, in that order, which
        is not stylistic: `CLAUDE.md` records a defect where a call site
        fetched chunks before opening and every first request for a
        newly-touched project answered 503 while every later one succeeded --
        once per project, and indistinguishable from flakiness.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        store = await graphs.open(project_id)
        index = graphs.co_mentions(project_id)
        if index is None:
            raise HTTPException(status_code=503, detail="no co-mention index is configured")
        return RecordedCoMentions(index, project_id, store)

    async def _semantic(project_id: UUID) -> VectorNeighbours | None:
        """This project's `SemanticPort`, or None when there is nothing to read.

        `graphs.open` first, for `_co_mentions`' reason -- the card vector
        store is folded during `open`, so asking before it has run gets `None`
        from a project whose vectors are merely not loaded yet, which is the
        once-per-project failure that reads as flakiness.

        Unlike `_co_mentions` this returns `None` rather than raising a 503
        when the store is absent. The corpus is a hard requirement for area
        projection and its absence is a misconfiguration; embeddings are an
        optional signal, and a build with `AGENT_VECTOR_STORE=none` must serve
        a curriculum rather than an error.
        """
        if graphs is None:
            raise HTTPException(status_code=503, detail="no graph read model is configured")
        await graphs.open(project_id)
        vectors = graphs.card_vectors(project_id)
        if vectors is None:
            return None
        return VectorNeighbours(vectors, tenant_id=project_id)

    async def _curriculum(project_id: UUID):
        """This project's areas and the path through them.

        503 rather than 404 when unwired, matching `_graph_reader`: a build
        without a graph read model is a valid thing to serve, and the caller
        needs to know the *server* cannot answer rather than that the project
        has nothing to learn.
        """
        if curriculum is None:
            raise HTTPException(
                status_code=503, detail="curriculum projection is not configured"
            )
        reader = await _graph_reader(project_id)
        try:
            return await curriculum.build(
                project_id,
                reader,
                await _co_mentions(project_id),
                await _semantic(project_id),
            )
        except GraphTooLarge as error:
            # 422 rather than 500: the project is fine and the server is fine;
            # the question is one this projection will not answer at this size.
            # The detail names the cap so the answer is actionable.
            raise HTTPException(status_code=422, detail=str(error)) from error

    @app.get("/api/projects/{project_id}/curriculum")
    async def read_curriculum(project_id: UUID):
        """What this project turned out to be about, and in what order.

        A GET rather than a POST that stores something, because the projection
        is a pure function of a graph already folded from the log -- see
        `domain/learning_area.py` on why none of this is an aggregate. The
        cost of recomputation is paid by `CurriculumService`'s cache, not by
        making the reader ask for a projection and then poll for it.
        """
        await _require_project(project_id)
        return curriculum_view(await _curriculum(project_id))

    async def _catalog(project_id: UUID, *, include_unnamed: bool = False) -> Catalog:
        """This project's catalog, assembled over its curriculum and its
        featured overrides.

        503 rather than an empty catalog when `catalog` or `catalog_features`
        is unwired, matching `_curriculum`'s own reasoning: an empty catalog is
        the right answer for a project with no graph, and an unwired build
        answering the same thing would be indistinguishable from that --
        exactly the failure this feature is arranged against.

        `include_unnamed` defaults false, matching the front page's own
        default -- a caller that only needs one candidate by slug (course
        detail, realize) does not care which candidates the front page is
        currently hiding, since a hidden candidate's slug still resolves.
        The sweep route below passes `True` explicitly: it exists to *give*
        unnamed candidates a title, so it is the one caller that must see
        the set the toggle hides.
        """
        if catalog is None or catalog_features is None:
            raise HTTPException(status_code=503, detail="the course catalog is not configured")
        # Resolved here rather than closed over at wiring time: the store does
        # not exist until the server's lifespan has run `start()`. See
        # `CatalogFeatures`. A getter that still answers `None` at request time
        # is a build whose lifespan never ran, and 503 is the honest answer.
        features = catalog_features()
        if features is None:
            raise HTTPException(status_code=503, detail="the course catalog is not configured")
        built = await _curriculum(project_id)
        featured = await features.featured_for(project_id)
        return await catalog.build(
            project_id, built, featured, include_unnamed=include_unnamed
        )

    @app.get("/api/projects/{project_id}/catalog/categories/{key}")
    async def read_catalog_category(project_id: UUID, key: str, unnamed: bool = False):
        """One category's page.

        **Registered ahead of the feature/unfeature routes below**, matching
        the `/sources/extract` block's own comment: a literal segment that
        could also be read as a path parameter has to be declared first, or
        FastAPI's declaration-order matching reads it as one. `GET
        /catalog/blurbs` below is the same situation against `GET
        /catalog/{slug}` (Task 9): both are one segment past `/catalog`, one
        of them is literal, and the literal one has to come first or a
        project's course named `blurbs` would be unreachable and every other
        project's sweep progress would read as "no such course". `GET`/`POST
        /catalog/art` further below is the identical situation with the art
        sweep in place of the blurb sweep -- registered ahead of
        `/catalog/{slug}` for the same reason, no separate comment needed.

        404 for a key nothing in this catalog uses, not an empty category --
        an empty category and a misspelled key are different answers, and a
        reader needs to tell them apart.
        """
        await _require_project(project_id)
        page = catalog_category_view(await _catalog(project_id, include_unnamed=unnamed), key)
        if page is None:
            raise HTTPException(status_code=404, detail=f"no category {key!r}")
        return page

    @app.get("/api/projects/{project_id}/catalog/blurbs")
    async def read_blurb_sweep_progress(project_id: UUID):
        """Where the last (or current) blurb sweep on this project stands.

        **Registered ahead of `GET /catalog/{slug}` below** -- see
        `read_catalog_category`'s docstring. `_NOT_RUNNING`'s shape (see
        `blurb_sweep.py`) is what a project that has never swept and a
        project whose sweep just finished both answer, so this never needs
        its own 404 case.
        """
        await _require_project(project_id)
        if blurb_sweep is None:
            raise HTTPException(status_code=503, detail="blurb sweeping is not configured")
        return blurb_sweep.progress(project_id)

    @app.post("/api/projects/{project_id}/catalog/blurbs", status_code=202)
    async def start_blurb_sweep(project_id: UUID):
        """Write catalog copy and outlines for every candidate whose cached
        copy or outline is missing or stale, in the background.

        Outline generation used to happen inside `GET /catalog/{slug}` on a
        cache miss -- a model call awaited behind a click. It now happens
        only here; `CourseService._outline_for` is cache-read-only. See
        `blurb_sweep.py`'s module docstring for why this is folded into the
        existing copy sweep rather than a second one running beside it.

        409 when a sweep is already running on this project -- one at a time,
        `BlurbSweep.start`'s own reason: two sweeps racing would both read and
        write the same cache entries.
        """
        await _require_project(project_id)
        if blurb_sweep is None or blurb_writer is None or outline_writer is None:
            raise HTTPException(status_code=503, detail="blurb sweeping is not configured")
        # `include_unnamed=True`: the whole point of a sweep is to give an
        # unnamed candidate a title, so the one caller that must see them is
        # this one -- the default-hidden set on the front page is exactly the
        # backlog this route exists to work through.
        built = await _catalog(project_id, include_unnamed=True)
        try:
            frame = await blurb_sweep.start(
                project_id, built.all_candidates, blurb_writer, outline_writer
            )
        except SweepAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=frame)

    @app.get("/api/projects/{project_id}/catalog/art")
    async def read_art_sweep_progress(project_id: UUID):
        """Where the last (or current) art sweep on this project stands.
        Mirrors `read_blurb_sweep_progress` exactly -- see its docstring and
        `read_catalog_category`'s for why this is registered ahead of `GET
        /catalog/{slug}` below."""
        await _require_project(project_id)
        if art_sweep is None:
            raise HTTPException(status_code=503, detail="art sweeping is not configured")
        return art_sweep.progress(project_id)

    @app.post("/api/projects/{project_id}/catalog/art", status_code=202)
    async def start_art_sweep(project_id: UUID, force: bool = False):
        """Generate art for every candidate the library has neither assigned
        nor matched, in the background.

        `force=true` re-illustrates *every* candidate, ignoring an existing
        assignment (fresh or drifted) and skipping the library-match check
        too -- see `art_sweep.py`'s module docstring for why a forced sweep
        has to actually call the model for every card rather than quietly
        re-matching most of them back to what they already had. The default
        (`force=False`) is unchanged from before this feature: someone
        pressing the ordinary "Illustrate the catalog" button must not
        suddenly pay for a model call per card that already has art.

        409 when a sweep is already running on this project, matching
        `start_blurb_sweep`'s reason.
        """
        await _require_project(project_id)
        if art_sweep is None or art_generator is None or art_matcher is None:
            raise HTTPException(status_code=503, detail="art sweeping is not configured")
        built = await _catalog(project_id, include_unnamed=True)
        try:
            frame = await art_sweep.start(
                project_id, built.all_candidates, art_generator, art_matcher, force=force
            )
        except ArtSweepAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=frame)

    @app.get("/api/projects/{project_id}/catalog/{slug}/art/reroll")
    async def read_art_reroll_progress(project_id: UUID, slug: str):
        """Where the last (or current) reroll of this candidate's art
        stands. Mirrors `read_art_sweep_progress`, keyed one level narrower
        -- see `ArtReroll`'s docstring."""
        await _require_project(project_id)
        if art_reroll is None:
            raise HTTPException(status_code=503, detail="art rerolling is not configured")
        return art_reroll.progress(project_id, slug)

    @app.post("/api/projects/{project_id}/catalog/{slug}/art/reroll", status_code=202)
    async def start_art_reroll(project_id: UUID, slug: str):
        """Drop this candidate's art assignment and generate a fresh piece,
        skipping the library search entirely -- see `ArtReroll`'s docstring
        for why re-matching would usually hand back the very picture the
        person is trying to get away from.

        404 for a slug naming no current candidate, matching
        `read_course_detail`'s reasoning. 409 when this candidate is already
        mid-reroll.
        """
        await _require_project(project_id)
        if art_reroll is None or art_generator is None:
            raise HTTPException(status_code=503, detail="art rerolling is not configured")
        built = await _catalog(project_id, include_unnamed=True)
        candidate = next((c for c in built.all_candidates if c.slug == slug), None)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"no course {slug!r}")
        try:
            frame = await art_reroll.start(project_id, slug, candidate, art_generator)
        except RerollAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=frame)

    @app.get("/api/projects/{project_id}/catalog/{slug}")
    async def read_course_detail(project_id: UUID, slug: str):
        """One cluster's detail page: its candidate card, its outline, its
        full membership, and -- if realized -- how far it has drifted.

        404 for a slug naming no candidate in the current catalog, matching
        `CourseService.detail`'s own reasoning: a stranded realized course
        (one whose slug names no *current* cluster) is deliberately not
        reachable through this route -- see `orphans()`.
        """
        await _require_project(project_id)
        if course_service is None:
            raise HTTPException(status_code=503, detail="course realization is not configured")
        built = await _curriculum(project_id)
        # `include_unnamed=True`: a slug is looked up directly here, and a
        # candidate the front page currently hides by default must not 404
        # just for being unnamed -- the toggle governs what the front page
        # shows, not which slugs exist.
        catalog_built = await _catalog(project_id, include_unnamed=True)
        detail = await course_service.detail(project_id, built, catalog_built, slug)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no course {slug!r}")
        return course_detail_view(detail)

    @app.get("/api/projects/{project_id}/catalog/{slug}/unit")
    async def read_course_unit(project_id: UUID, slug: str):
        """The markdown the authoring turns wrote for this course, as text a
        browser renders -- not as an attachment.

        **The gap this closes.** Everything downstream of `realize` already
        worked: the three UbD turns write `/course/areas/<slug>/unit.md` and
        its lessons into their session's workspace, `authoring_runs` records
        which session that was, and `export.py` resolves both. But every route
        that read those files set `Content-Disposition` -- that module's own
        docstring says none of them "returns a body a browser would render in
        place" -- so a realized course's page could offer a download or a link
        into the agent transcript and nothing else. A product whose stated end
        is "where learners go to learn" terminated in a zip file.

        **Three states, and they are the point of the shape below.**
        `CourseDetail.outline` deliberately conflates "the model refused" with
        "nothing has generated one yet", and its docstring argues that is fine
        because both render as "no outline yet". That argument does not
        survive being applied to a whole course: a reader who lands on
        "nothing here" must be able to tell *nobody has written this* from
        *it is being written right now*, because the first is a button to
        press and the second is a reason to wait. So `state` is explicit --
        `authored`, `authoring`, `unauthored` -- rather than inferred by a
        client from a null field.

        **The order the states are decided in, and what it costs.** Files
        first: if a session recorded against this slug holds course markdown,
        that is `authored`, *even while a later run is rewriting it*. The
        alternative was to let an in-flight run win and show a spinner over a
        course that exists and is readable, which trades a reader's whole
        course for a progress indicator they can already see in the authoring
        panel. The cost is that a re-author in progress is invisible from this
        payload alone; that is deliberate, and the run panel is where it
        shows.

        A recorded session that holds *no* files under the prefix falls
        through to the run check rather than answering `authored` with
        nothing in it. An empty `authored` would be the same silence this
        route exists to end, wearing the word that means the opposite.

        **`authoring` requires the slug to be among a live run's targets**,
        not merely that some run is live. A path run over eight other areas
        tells this reader nothing about theirs, and "being written right now"
        about a course nobody queued is a promise the system will not keep.

        **`unitPath` is here so the console can render widgets.** The lessons
        already carried their workspace paths; the unit carried only its text,
        because the first reader of this payload put both through a plain
        markdown renderer. That reader was wrong -- a lesson's
        ```component:mcq``` fence is not markdown, and rendering it as one
        prints the widget's yaml source as a code block. The console now asks
        `GET /api/sessions/{id}/files/parsed` for each file, which needs a
        session id and a *path*, and the unit had no path to give. Measured on
        2026-08-24 against the `resolution` course: 19 component blocks, 10 of
        them in the unit, so a fix that reached only the lessons would have
        left more than half of them raw.

        503 when authoring is unwired, matching `read_course_detail` beside
        it: a build with no authoring cannot answer any of the three states
        truthfully, and `unauthored` would read as a fact about the course.
        `service.load` raising for a session id the table names is left to
        propagate -- a recorded session that cannot be opened is a broken
        record, and answering `unauthored` would file it as ordinary absence.
        """
        await _require_project(project_id)
        if authoring is None:
            raise HTTPException(status_code=503, detail="course authoring is not configured")

        session_id = await authoring.authored_session_for(project_id, slug)
        if session_id is not None:
            session = await service.load(session_id)
            if is_path_file(session, slug):
                # A target that wrote the path overview rather than an area:
                # one file, no lessons. Asked of the workspace rather than
                # inferred from the slug, for `is_path_file`'s reason.
                entry = session.state.files.get(path_file(slug)) or {}
                # `learning_plan_prompt` asks for a YAML frontmatter block on
                # every file it writes, and markdown reads a `key: value` line
                # immediately followed by `---` as a setext heading -- so a
                # reader handed the raw file sees a fabricated `<h2>` made of
                # the frontmatter's own fields sitting above the real `# `
                # heading the file opens with. `parse_frontmatter` already
                # exists for `application/components.py`'s parser; using it
                # here rather than a second notion of "what frontmatter is" in
                # the console.
                _, body = parse_frontmatter(entry.get("content", ""))
                return {
                    "slug": slug,
                    "state": "authored",
                    "sessionId": str(session_id),
                    "unitPath": path_file(slug),
                    "unit": body,
                    "lessons": [],
                }
            unit, lessons = split_area(session, slug)
            if unit is not None or lessons:
                return {
                    "slug": slug,
                    "state": "authored",
                    "sessionId": str(session_id),
                    "unitPath": None if unit is None else unit[0],
                    "unit": None if unit is None else parse_frontmatter(unit[1])[1],
                    "lessons": [
                        {"path": path, "markdown": parse_frontmatter(content)[1]}
                        for path, content in lessons
                    ],
                }

        live = authoring.active(project_id)
        if live is not None and slug in (live.get("targets") or []):
            return {
                "slug": slug,
                "state": "authoring",
                "sessionId": None,
                "unitPath": None,
                "unit": None,
                "lessons": [],
            }

        return {
            "slug": slug,
            "state": "unauthored",
            "sessionId": None,
            "unitPath": None,
            "unit": None,
            "lessons": [],
        }

    def _author_one_target(
        project_id: UUID,
        built,
        by_slug: dict,
        subject: str,
        lesson_count: int = 3,
    ):
        """One target's authoring call, shared by `author_courses`'s run and
        `realize_course`'s single-area run below (Task 9's brief) -- one call
        into `CourseAuthor`, not two copies that could drift on what "the
        path's own slug" means.
        """

        async def _one(run_id: UUID, target: str):
            if target == built.path.slug:
                return await course_author.author_path(
                    project_id, built.path, by_slug, run_id=run_id
                )
            return await course_author.author_area(
                project_id, by_slug[target], subject, lesson_count=lesson_count, run_id=run_id
            )

        return _one

    async def _authoring_holder(project_id: UUID) -> UUID | None:
        """Who holds this project, asked because authoring is about to need it.

        `CourseAuthor.author_area` opens with `start_in_project`, and
        `JoinProject`'s precondition is `active_session_id is None` -- so a
        project somebody has open in chat refuses every authoring run. That
        refusal used to happen inside the background task, ~30ms after a 202
        the caller read as "it started": measured on the owner's database on
        2026-08-29, three `CourseAuthoringFailed` events in half an hour, all
        `project is held by session 049ac30c`, a `purpose: chat` session that
        had done nothing since it joined 20 minutes earlier. Nothing on any
        surface said so; the course page simply stayed unauthored forever.

        Asked *before* starting, so the answer can be handed to the caller as
        a name rather than left as a silence. Advisory rather than a lock --
        a holder can arrive between this read and `start_in_project` -- and
        that is fine: the background refusal is still there underneath, this
        only makes the ordinary case sayable.
        """
        state = await service.project_state(project_id)
        return state.active_session_id

    async def _take_over_for_authoring(project_id: UUID) -> None:
        """Release whoever holds this project so an authoring run can join.

        The same two steps `join_project`'s `take_over` takes, and refused on
        the same condition: a holder mid-turn is not released, because
        `release_project` advances the tip to `session.version` and a turn
        still running would write past it -- the detachment `_catch_up_tip`
        exists to repair. `docs/design/the-holding-session-goes-backstage.md`
        §1 is what this is careful about: holding is untouched, nothing joins
        implicitly, and a take-over stays an explicit act a person asked for.
        """
        holder = await _authoring_holder(project_id)
        if holder is None:
            return
        if turns.is_running(holder):
            raise HTTPException(
                status_code=409,
                detail="the holding session has a turn running; cancel it first",
            )
        await service.release_project(holder)

    @app.post("/api/projects/{project_id}/catalog/{slug}/realize", status_code=202)
    async def realize_course(project_id: UUID, slug: str):
        """Record that a person has decided this cluster is a course, then
        try to start writing it.

        **The decision is appended first, unconditionally on the slug naming
        a current candidate and not already being realized.** Authoring is
        then attempted, and `RunAlreadyActive` is caught rather than left to
        become this route's own 409 -- see the module's Task 9 brief: whether
        a person can *choose* a course must not depend on whether someone
        else's authoring run happens to be in flight. `authoring` is `None`
        and `reason` is set on that path; a caller invalidates the run panel
        on the next `curriculum/author` attempt rather than reading a frame
        from this response.

        **The frozen membership is the area's full membership, not its
        anchors** -- `CourseCandidate.anchors` is capped at 12 (Task 9's
        brief), and freezing that would make every course's fit report drift
        that is an artifact of the cap rather than a fact about the cluster.
        404 for a slug naming no current candidate; 409 when `decide` refuses
        a second `RealizeCourse` on an already-realized stream.
        """
        await _require_project(project_id)
        if course_repository is None:
            raise HTTPException(status_code=503, detail="course realization is not configured")
        built = await _curriculum(project_id)
        # `include_unnamed=True` for `read_course_detail`'s reason above: a
        # slug looked up directly must not 404 for being unnamed.
        catalog_built = await _catalog(project_id, include_unnamed=True)
        candidate = next((c for c in catalog_built.all_candidates if c.slug == slug), None)
        if candidate is None:
            raise HTTPException(status_code=404, detail=f"no course {slug!r}")

        area = built.area(slug)
        member_ids = tuple(m.entity_id for m in area.members) if area is not None else ()

        aggregate = await course_repository.load_or_create(
            course_stream_id(project_id, slug).aggregate_id
        )
        try:
            aggregate.execute(
                RealizeCourse(
                    project_id=project_id,
                    slug=slug,
                    title=candidate.title,
                    member_entity_ids=member_ids,
                    membership_hash=candidate.membership_hash,
                    realized_at=datetime.now(UTC),
                )
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await course_repository.save(aggregate)

        authoring_frame: dict[str, Any] | None = None
        reason: str | None = None
        held_by: UUID | None = None
        if authoring is None or course_author is None:
            reason = "course authoring is not configured"
        else:
            # Asked before starting rather than after failing -- see
            # `_authoring_holder`. No `take_over` flag on *this* route: the
            # realization is already appended by the time we get here and a
            # second click answers 409, so the retry has to be a different
            # call anyway. `POST /curriculum/author` with `take_over` is that
            # call, and putting the take-over on one route rather than two
            # keeps the release of somebody else's session in one place.
            held_by = await _authoring_holder(project_id)
            if held_by is not None:
                reason = f"this project is held by session {held_by}"
            else:
                subject = (await service.project_state(project_id)).name or str(project_id)
                _one = _author_one_target(project_id, built, built.by_slug, subject)
                try:
                    authoring_frame = await authoring.start(
                        project_id, [slug], _one, kind="area"
                    )
                except RunAlreadyActive as error:
                    reason = str(error)

        return JSONResponse(
            status_code=202,
            content={
                "realized": True,
                "authoring": authoring_frame,
                "reason": reason,
                # Named, not merely counted: the console's whole offer is
                # "held by <this session> -- take it?", and a reason string
                # the client has to parse a UUID out of is the version of
                # that offer which breaks the first time the wording changes.
                "heldBy": None if held_by is None else str(held_by),
            },
        )

    @app.post("/api/projects/{project_id}/catalog/{slug}/abandon")
    async def abandon_course(project_id: UUID, slug: str):
        """Withdraw the decision that this cluster is a course.

        Does not cancel a running authoring run and does not delete anything
        that run wrote -- the decision is withdrawn, not the work it caused
        (Task 9's brief). 409 when `decide` refuses -- the course was never
        realized, or was already abandoned.
        """
        await _require_project(project_id)
        if course_repository is None:
            raise HTTPException(status_code=503, detail="course realization is not configured")
        aggregate = await course_repository.load_or_create(
            course_stream_id(project_id, slug).aggregate_id
        )
        try:
            aggregate.execute(AbandonCourse(project_id=project_id, slug=slug))
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        await course_repository.save(aggregate)
        return {"slug": slug, "realized": False}

    class FeatureCourse(BaseModel):
        rank: int = 0

    @app.post("/api/projects/{project_id}/catalog/{slug}/feature")
    async def feature_course(project_id: UUID, slug: str, body: FeatureCourse):
        """Put one candidate on the front page, at the given rank.

        No check that `slug` names a current area: a slug is derived from an
        area's top anchor, so re-clustering can move it, and a feature aimed
        ahead of the graph that will eventually hold it is exactly the case
        `Catalog.unplaceable_featured` reports rather than refuses.
        """
        await _require_project(project_id)
        if catalog_recorder is None:
            raise HTTPException(status_code=503, detail="catalog curation is not configured")
        await catalog_recorder(project_id).feature(slug, body.rank)
        return {"slug": slug, "rank": body.rank}

    @app.post("/api/projects/{project_id}/catalog/{slug}/unfeature")
    async def unfeature_course(project_id: UUID, slug: str):
        """Take one candidate off the front page.

        Unfeaturing a slug that was never featured is accepted rather than
        refused, matching `CatalogFeatureStore.unfeature`'s own reasoning:
        there is no aggregate here to enforce a precondition against, and a
        second click doing nothing is not an error.
        """
        await _require_project(project_id)
        if catalog_recorder is None:
            raise HTTPException(status_code=503, detail="catalog curation is not configured")
        await catalog_recorder(project_id).unfeature(slug)
        return {"slug": slug}

    @app.get("/api/projects/{project_id}/catalog")
    async def read_catalog(project_id: UUID, unnamed: bool = False):
        """The front page: hero, highlights, and everything else by category.

        `unnamed=true` shows candidates with no cached title -- default false
        because a title-less card falls back to `LearningArea.display_name()`,
        the single most central *entity* in the cluster, and reads as an
        entity name rather than a course.
        """
        await _require_project(project_id)
        return catalog_view(await _catalog(project_id, include_unnamed=unnamed))

    @app.get("/api/art/{art_id}.svg")
    async def read_art(art_id: UUID):
        """Serve one piece of art from the global library.

        Deliberately **not** under `/api/projects/{id}/` -- the increment-3
        spec's "Reuse across projects" section is the point of the library
        existing at all: a picture drawn for one project's course is
        findable and servable from any other, and nesting this under a
        project id would make that reuse a lie the URL itself contradicts.

        Re-sanitises on the way out rather than trusting `ArtStore.put`'s
        write-time check alone. `ArtStore.put`'s own docstring gives the
        cost side of that trade -- every read pays a parse it does not
        strictly need if nothing has gone wrong -- but the alternative is a
        route whose safety depends entirely on every past and future writer
        of this table having called the sanitiser correctly, including any
        row written by a version of this codebase that predates it, or by a
        bug in the sibling generator task this route cannot see. A refusal
        here degrades to 404 rather than serving anything, and an SVG cheap
        enough to regenerate is a better failure than trusting a write path
        this route does not control.
        """
        if art_store is None:
            raise HTTPException(status_code=404, detail=f"no art {art_id}")
        row = await art_store.get(art_id)
        if row is None:
            raise HTTPException(status_code=404, detail=f"no art {art_id}")
        safe = SvgSanitiser().sanitise(row.svg)
        if safe is None:
            # A row that fails re-sanitisation is treated the same as a
            # missing one -- 404, not 500 -- because the failure is "this
            # is not safe to serve", which is exactly what a missing row
            # also means to a caller of this route. Logged as a real
            # anomaly, since it means a stored row disagrees with the
            # sanitiser that is supposed to have already passed it once.
            logging.getLogger(__name__).warning(
                "stored art %s failed re-sanitisation on read", art_id
            )
            raise HTTPException(status_code=404, detail=f"no art {art_id}")
        return Response(
            content=safe,
            media_type="image/svg+xml",
            headers={
                # Immutable: `art_id` is `uuid4`, minted once, and the bytes
                # under it never change (see `ArtRow`'s docstring) -- so a
                # browser that has fetched one id never needs to ask again.
                "Cache-Control": "public, max-age=31536000, immutable",
                # Belt over the sanitiser's suspenders, per the increment-3
                # spec: an `<img src>` will not execute script in any
                # current browser, but this route is general enough that a
                # future caller may inline the response, and this header is
                # what still holds the line if one does.
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            },
        )

    @app.post("/api/projects/{project_id}/embeddings", status_code=202)
    async def refresh_embeddings(project_id: UUID):
        """Re-embed every entity in this project, from the graph as it stands.

        **Why this exists rather than embeddings simply being current.** A
        vector is written when its entity is extracted, and it encodes the card
        the entity had *then*. Nothing re-embeds at project open, deliberately:
        `rebuild_graph` must not depend on a live endpoint, or a session
        refolded years from now would not open. So an entity that gained six
        relationships after it was first seen carries a vector that knows about
        none of them, and this is the button that fixes it.

        It is also the repair for the whole class of projects ingested before
        embeddings were durable at all, which is every project written before
        2026-08-22: their logs carry no `EntitiesEmbedded`, so they fold to an
        empty vector store and cluster on the graph alone until this runs.

        **202 and synchronous, which is a contradiction worth admitting.** The
        work is one embedding call per 64 entities and returns before the
        response does; the status is 202 because the *effect* a caller cares
        about -- a curriculum clustered with the new vectors -- lands on the
        next projection rather than in this response body. What it costs is a
        request held open proportional to the graph: about eight calls for a
        five-hundred-entity project, and a route that is no longer reasonable
        somewhere north of a few thousand. `BACKLOG.md` B131 has the
        background-run version; this is deliberately the small one.

        The cached curriculum is forgotten here rather than left to expire,
        because the cache is keyed on entity and relationship counts and
        re-embedding moves neither -- so without this, the run would succeed
        and change nothing anybody could see until the next extraction.
        """
        await _require_project(project_id)
        if reembed is None:
            raise HTTPException(status_code=503, detail="embeddings are not configured")
        try:
            embedded = await reembed(project_id)
        except KnowledgeError as error:
            # 502 rather than 500: the fault is upstream and the operator can
            # act on it. Distinct from the 503 above, which says this build was
            # never wired for embeddings, and from a 202 carrying `embedded: 0`,
            # which says the feature is off on purpose. Three different things
            # a browser would otherwise have to guess at from one status.
            raise HTTPException(status_code=502, detail=str(error)) from error
        if curriculum is not None:
            curriculum.forget(project_id)
        return {"embedded": embedded}

    @app.get("/api/projects/{project_id}/curriculum/areas/{slug}")
    async def read_learning_area(project_id: UUID, slug: str):
        """One area with its full membership, not just its anchors.

        404 when the slug names no area, and that is the ordinary case rather
        than a fault: a browser holding a slug from a projection taken before
        the graph grew is exactly what a bookmark is.
        """
        await _require_project(project_id)
        area = (await _curriculum(project_id)).area(slug)
        if area is None:
            raise HTTPException(status_code=404, detail=f"no learning area {slug!r}")
        return area_view(area)

    @app.get("/api/projects/{project_id}/curriculum/paths/{slug}")
    async def read_learning_path(project_id: UUID, slug: str):
        """The complete path, or the prerequisite closure of one area.

        `complete` is the whole projection in order; any other slug is read as
        an area id and answered with everything needed to reach it. One route
        rather than two because they are the same object -- a cut of one
        digraph -- and two routes would invite two implementations that could
        disagree about whether A precedes B.
        """
        await _require_project(project_id)
        built = await _curriculum(project_id)
        if slug == built.path.slug:
            return path_view(built.path)
        if curriculum is None:  # pragma: no cover -- `_curriculum` already raised
            raise HTTPException(
                status_code=503, detail="curriculum projection is not configured"
            )
        cut = await curriculum.path_toward(
            project_id,
            slug,
            await _graph_reader(project_id),
            await _co_mentions(project_id),
            await _semantic(project_id),
        )
        if cut is None:
            raise HTTPException(status_code=404, detail=f"no learning area {slug!r}")
        return path_view(cut)

    @app.post("/api/projects/{project_id}/curriculum/author")
    async def author_courses(project_id: UUID, body: NewAuthoring):
        """Write the course for one area, or for every area on the path.

        202, matching `seed_topics`: the turns have not finished when this
        answers. What it hands back is a run that has *begun*, and the files
        it writes arrive over the log like any other `write_file` -- a client
        wanting them invalidates its file list on those frames rather than
        reading this response for them.

        409 when this project already has an authoring run in flight. One at a
        time, refused up front, for `AuthoringActivity`'s reason: a path is up
        to four model turns per area and a second run would interleave with
        the first on the same project.
        """
        if course_author is None or authoring is None:
            raise HTTPException(status_code=503, detail="course authoring is not configured")
        await _require_project(project_id)

        # Before the curriculum is folded, because a run that cannot join the
        # project is refused whatever the curriculum says, and folding it
        # first would spend that work on the way to a 409.
        if body.take_over:
            await _take_over_for_authoring(project_id)
        else:
            holder = await _authoring_holder(project_id)
            if holder is not None:
                # 409 naming the holder, not a 202 that dies in the
                # background 30ms later -- see `_authoring_holder` for what
                # that silence measured. The client's next call is this same
                # route with `take_over`, so the refusal names the flag
                # rather than only the problem.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"this project is held by session {holder}; "
                        "retry with take_over to release it"
                    ),
                )

        built = await _curriculum(project_id)

        if body.area:
            if built.area(body.area) is None:
                raise HTTPException(status_code=404, detail=f"no learning area {body.area!r}")
            targets = [body.area]
        else:
            targets = list(built.path.area_slugs)
        if not targets:
            # 409 rather than 202-with-nothing-to-do. A run reported as started
            # over an empty target list settles instantly as "done" and reads,
            # on every surface, exactly like a run that authored everything.
            raise HTTPException(
                status_code=409,
                detail="this project has no learning areas yet; extract some sources first",
            )

        # The path's own overview file, authored last and only when the whole
        # path was asked for. Last because it links every area's `unit.md` and
        # is the one file that is wrong if an area's course does not exist yet;
        # only for a path because a single-area run has no order to write up.
        #
        # Appended to `targets` rather than run after them, so the one place
        # that reports progress reports this too -- a final step that ran
        # outside the target list would leave the panel saying "done" while a
        # model turn was still going.
        if not body.area:
            targets.append(built.path.slug)

        by_slug = built.by_slug
        # The project's own name is the subject every Stage 1 prompt is framed
        # against. Read here rather than passed in by the caller: a client that
        # could name the subject could aim a project's courses at a topic its
        # corpus knows nothing about, and the resulting unit would assess
        # material that is not there.
        subject = (await service.project_state(project_id)).name or str(project_id)

        _one = _author_one_target(project_id, built, by_slug, subject, body.lessons)

        try:
            frame = await authoring.start(
                project_id, targets, _one, kind="area" if body.area else "path"
            )
        except RunAlreadyActive as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return JSONResponse(status_code=202, content=frame)

    @app.post("/api/projects/{project_id}/curriculum/author/cancel")
    async def cancel_authoring(project_id: UUID):
        """Stop this project's authoring run, keeping what it already wrote.

        Answers how many targets it abandoned, matching
        `cancel_extraction_queue` and `cancel_dispatch`, so the caller can say
        "stopped 6" rather than re-reading a status a moment later and
        inferring it. Zero when nothing was running, which is not an error: a
        stop control pressed twice is a person pressing a button, not a bad
        request.

        200 rather than 202, unlike the POST above: cancelling is synchronous
        here. What is *not* synchronous is the run reaching `cancelled` on the
        log -- the driving task appends that on its way out, after the model
        turn it just cancelled unwinds. A caller that re-reads immediately can
        still see `running`, which is why this answers the count rather than
        the frame.
        """
        if authoring is None:
            raise HTTPException(status_code=503, detail="course authoring is not configured")
        await _require_project(project_id)
        return {"cancelled": authoring.cancel(project_id)}

    @app.get("/api/projects/{project_id}/curriculum/author")
    async def get_authoring(project_id: UUID):
        """What the running authoring run has done, and the last one's account.

        200 with both halves `None` when nothing has run, matching `get_seed`:
        an absent run is a state, not a missing resource.

        `last` is read from the log rather than from memory, so a run that a
        restart interrupted still answers with the targets it authored and the
        sessions holding them -- reported with status `interrupted`, which is
        neither `done` nor `failed`. See `AuthoringActivity.last`.
        """
        await _require_project(project_id)
        if authoring is None:
            return {"current": None, "last": None}
        return {
            "current": authoring.current(project_id),
            "last": await authoring.last(project_id),
        }

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
        # Ahead of `take_over`, so that a deleted project is 404 rather than
        # reaching `release_project` and advancing a retired project's tip on
        # the way to the domain's refusal. Joining one used to answer the
        # domain's 409 "project has been deleted", which both refused the join
        # and confirmed the project existed; 404 is the same refusal without
        # the confirmation, and matches every other project-scoped route.
        await _require_project(project_id)
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
            session_id = await service.start_in_project(project_id, SessionPurpose.CHAT)
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

    @app.get("/api/workers")
    async def get_all_workers():
        """Everything in flight anywhere, in one request.

        For a reader who is not looking at a project: the console's agent
        widget sits on every page and its collapsed state is a count across all
        of them, which a per-project route cannot answer without one request
        per project on every page load. There used to be such a route
        (`GET /api/projects/{project_id}/workers`); it was deleted unused.

        Only projects with something running are returned, and the empty list
        is the ordinary answer. That is not a shortcut for the client's benefit
        -- it is what makes this cheap, because `everywhere` folds only the
        projects its supervisors named rather than every project that exists.

        404 when no roster is wired: a 200 with an empty list would tell a
        browser that nothing is running, which is a different claim from
        "this build cannot tell you".
        """
        if workers is None:
            raise HTTPException(status_code=404, detail="the worker roster is not enabled")
        return [roster_view(roster) for roster in await workers.everywhere()]

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

    def _ask_frame(note: object) -> str:
        """One SSE `data:` line per note.

        `message` mirrors ActivityMessage's fields so the browser reuses the
        parsing it already has for the session activity feed.
        """
        if isinstance(note, AskConversationOpened):
            # The first frame of every ask. Without it the browser holds only
            # its own `chat_id`, which is not what the conversation is stored
            # under and never reaches storage at all -- so the history routes
            # below would list conversations the page that produced them could
            # not identify.
            body: dict[str, Any] = {
                "type": "conversation",
                "conversation_id": str(note.conversation_id),
            }
        elif isinstance(note, ActivityDelta):
            body = {
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
                "position": note.position,
                # Parsed here rather than in the browser for the four reasons
                # `application/components.py` opens with, of which the second
                # binds hardest: withholding is only real if the projection
                # happens before the bytes leave. `text` travels beside it
                # anyway (see the design's section 5) -- that is honesty about
                # the strength of the property, not a reason to skip it.
                "blocks": answer_document(note.text)["blocks"],
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

    def _socratic_frame(note: object) -> str | None:
        """One SSE `data:` line per note, or `None` for a note with nothing to draw.

        Deliberately its own function rather than a branch inside `_ask_frame`:
        the last frame of a dialogue turn is typed `prompt` and not `answer`,
        because it is a question. A page that reused the ask's handler would
        draw the dialogue's question in the reader's own column -- and it would
        render, which is why this is a separate function with its own test
        (`test_the_last_frame_is_typed_prompt_and_not_answer`, red against a
        copy-paste of `_ask_frame`).
        """
        if isinstance(note, SocraticDialogueOpened):
            body: dict[str, Any] = {
                "type": "dialogue",
                "dialogue_id": str(note.dialogue_id),
                "goal": note.goal,
                "stopping_condition": note.stopping_condition,
                # The question being answered, not the one about to be asked.
                # On a resumed dialogue this is not the opening one, which is
                # why the field is not called `opening_prompt`.
                #
                # Projected rather than raw, and this one is the leak that
                # nearly survived: `pending_prompt` is the NEWEST turn's prompt
                # (see `read_models.py`, where it is written from exactly
                # that), so on a resumed dialogue it is the component-bearing
                # question the reader is looking at -- key and all. Fixing the
                # `prompt` frame alone would have left this shipping the answer
                # to every question a reader had already been asked, the moment
                # they came back to it.
                "pending_blocks": dialogue_document(note.pending_prompt)["blocks"],
            }
        elif isinstance(note, ActivityDelta):
            # **The dialogue's own prose never goes over this stream, and that
            # is the whole of this branch.** `to_activity_delta` carries the
            # main agent's text exactly as the model produced it, so when the
            # model writes an `mcq` the fence streams with `correct: true` in
            # it -- ahead of the `prompt` frame two branches down, which is at
            # pains to withhold precisely that. Measured on 2026-08-17 by
            # `test_no_frame_of_a_streamed_turn_carries_the_answer_key`, which
            # is red with this `return None` removed.
            #
            # Suppressed rather than filtered or buffered. Filtering the fenced
            # region out of a delta means recognising a fence that has not
            # finished arriving -- a half-written ```` ```component: ```` is
            # indistinguishable from prose until its closing line, so the
            # filter's failure mode is shipping the key it exists to hold back.
            # Buffering until a fence closes has the same recogniser inside it
            # and defers every delta behind an unclosed one. Suppression has no
            # recogniser at all, and on this surface a projection is only real
            # if there is nothing beside it.
            #
            # The frame itself survives with an EMPTY `text`, and that is not
            # tidiness. The console plan for this surface
            # (`docs/superpowers/plans/2026-08-17-socratic-dialogue-console.md`,
            # read rather than assumed) already rules that the transcript's
            # question text comes only from `blocks` and that "deltas drive
            # nothing but a composing indicator" -- so the page folds over
            # delta frames for liveness and ignores their text. Dropping the
            # frame outright would take that liveness signal away with the
            # leak; emptying it takes only the leak.
            #
            # The cost, stated plainly: a reader watching a dialogue compose
            # gets a "composing" indicator and then the finished question, with
            # no token-by-token prose. That is what the plan already assumed.
            # It becomes a real cost the day a console wants the prose itself,
            # and the answer then is a projected delta channel, not the raw
            # one.
            body = {"type": "delta", "message_id": note.message_id, "text": ""}
        elif isinstance(note, ActivityMessage):
            if note.kind == "assistant":
                # The same leak by the other route: `to_activity_message`
                # builds `payload` from `message_to_dict` (`messages.py:54`),
                # so an assistant message carries the model's whole answer --
                # fence and key -- in one frame. The same test measures this
                # one; it caught both halves on the first red run.
                #
                # Tool and error messages still stream: they are what a reader
                # watching a slow turn actually sees, and they carry retrieved
                # source rather than the dialogue's own authored components.
                return None
            body = {
                "type": "message",
                "message_id": note.message_id,
                "kind": note.kind,
                "payload": note.payload,
                "is_error": note.is_error,
            }
        elif isinstance(note, SocraticPrompt):
            body = {
                "type": "prompt",
                # **No raw `text` beside `blocks`, and its absence is the
                # point.** This frame carried `"text": note.prompt` until
                # `test_the_answer_key_never_reaches_the_reader` measured what
                # went over the wire: the projection below withholds
                # `options[].correct`, and the raw copy one key to its left
                # shipped the whole fenced block with `correct: true` in it. A
                # page rendering `blocks` looked correct the entire time; the
                # defect was only ever visible in the bytes.
                #
                # The cost is that a client wanting the prose has to walk
                # `blocks` for its `kind: "markdown"` entries rather than
                # reading one string. That is the right cost: on this surface a
                # projection is only real if there is nothing beside it, and a
                # convenience field that re-adds the source is a hole no
                # projection can close.
                #
                # Parsed here rather than in the browser, for the reasons
                # `components.py` opens with -- the second binds hardest:
                # withholding is only real if the projection happens before the
                # bytes leave, and this surface is the one where being told the
                # answer defeats the method rather than merely leaking.
                "blocks": dialogue_document(note.prompt)["blocks"],
                "position": note.position,
                "citations": [{"kind": kind, "id": cited} for kind, cited in note.citations],
                "concluded": note.concluded,
            }
        elif isinstance(note, ActivityRemark):
            # Carried, not flattened. The brief's version emitted an empty
            # `payload` here, which draws an empty assistant bubble on the page
            # and loses the one thing the remark is: its text. A remark has no
            # `message_id` by design (see `ActivityRemark`), so it travels as a
            # message with an empty one and `kind: "remark"` -- Plan 3 can
            # style it apart from a model utterance without a sixth frame type
            # its DTOs would have to learn.
            body = {
                "type": "message",
                "message_id": "",
                "kind": "remark",
                "payload": {"text": note.text},
                "is_error": False,
            }
        else:
            # Anything added later, and deliberately nothing rather than an
            # empty bubble: a frame the page cannot render is worse than no
            # frame, because it occupies a row in the transcript. The caller
            # skips a `None`. Whoever adds a note type adds a branch here, and
            # the cost of forgetting is a note that is silently invisible --
            # which is the trade taken over a visible blank.
            return None
        return f"data: {json.dumps(body)}\n\n"

    @app.post("/api/projects/{project_id}/dialogues")
    async def start_dialogue(project_id: UUID, body: SocraticStart):
        """Frame a dialogue and return it -- goal, stopping condition and all.

        Not a stream, unlike the reply route: framing produces three strings and
        no activity worth watching, and a page that opened an EventSource for it
        would show a spinner over an empty transcript. The reader's first sight
        of the dialogue is its goal, and that arrives here.

        **It did not, until this route returned more than an id.** For three
        commits this docstring's last sentence was false: the body was
        `{"dialogueId"}` alone, so a freshly framed dialogue drew an empty
        framing block and an empty thread until the reader answered a question
        they could not see. `read_dialogue` below already served all three
        fields; nothing called it after framing.

        Returned here rather than left to a second `GET` by the client, and the
        trade is worth naming. A second call is one more round trip on the one
        path where the browser has nothing at all to draw in between, and it
        gives the store two independent failure modes (a 404 or a 503 on the
        read) for one reader action -- a dialogue that exists but whose framing
        did not arrive is a state nothing on the page can explain. The cost is
        that this route now needs `dialogues` and answers 503 without it, where
        it previously needed only `socratic`. That is honest rather than a
        narrowing: `composition.py` builds the two together (`socratic_service`
        takes `read_model=dialogues`), and a build with no projection cannot
        resume, list, or re-read any dialogue it mints.

        Reading the projection immediately after the write happens to be safe
        today -- `InMemoryEventBus.publish` dispatches synchronously by default
        (`background=False`), so `SocraticDialogueOpened` is projected before
        `begin` returns -- and that is **not** relied on. A miss falls through to
        `caught_up()` and one retry, which is scoped by aggregate type and so
        returns immediately in the common case rather than running its timeout
        against another stream's append (`SocraticDialogueRunner.caught_up` says
        why the scoping matters). The cost of the retry is one wasted `get` on a
        genuinely absent row; the cost of trusting the bus is a route that
        starts 502ing the day anything passes `background=True`.

        A framing the model botched raises `ValueError` out of `parse_framing`
        and becomes a 502: the request was fine and the upstream was not, which
        is a different thing to tell a reader than a 400.
        """
        if socratic is None or dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        if service is not None:
            await _require_project(project_id)
        try:
            dialogue_id = await socratic.begin(project_id=project_id, topic=body.topic)
        except ValueError as bad_framing:
            raise HTTPException(
                status_code=502, detail=f"the dialogue could not be framed: {bad_framing}"
            ) from bad_framing
        row = await dialogues.get(dialogue_id)
        if row is None:
            await dialogues.caught_up()
            row = await dialogues.get(dialogue_id)
        if row is None:
            # Unreachable through a working projection, and a 502 rather than
            # an assertion because the failure it reports is real and specific:
            # the dialogue was minted and its framing is not readable, which is
            # a half-made thing the client must not be handed as if it were
            # whole. A dropped `@handles` reaches here as a `TimeoutError` out
            # of `caught_up` instead -- see that method for why.
            raise HTTPException(
                status_code=502,
                detail=f"dialogue {dialogue_id} was framed but its projection is not readable",
            )
        return _dialogue_view(row)

    @app.post("/api/projects/{project_id}/dialogues/{dialogue_id}/reply")
    async def reply_to_dialogue(project_id: UUID, dialogue_id: UUID, body: SocraticReply):
        """Answer the outstanding question, and stream the next one.

        The same two-stage shape as `ask_project`, and for the same reason: the
        first note is pulled before the response begins so that the failures
        which can still be a status code -- 404 for an unknown dialogue, 409 for
        one already running or already concluded -- are status codes rather
        than error frames the page has to special-case.

        A concluded dialogue is a 409 rather than a 404, which is a distinction
        this route used to argue was not worth drawing. It was not, while
        nothing could conclude. It is now: a concluded dialogue is the reader's
        *own*, and their whole history is still stored under that id, so
        answering "no dialogue in project" says the opposite of what happened.
        """
        if socratic is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        if service is not None:
            await _require_project(project_id)

        notes = socratic.respond(
            project_id=project_id, dialogue_id=dialogue_id, reply=body.reply
        )
        failed: Exception | None = None
        try:
            first = await anext(notes)
        except DialogueConcluded as finished:
            # 409 and not 404: the dialogue exists and belongs to this reader,
            # and it is in a state that refuses this request. The same status
            # `post_dialogue_attempt` answers for an attempt against a
            # concluded dialogue, so a page has one rule for both.
            #
            # Ordered above `UnknownDialogue` because it is a subclass -- the
            # broader arm would otherwise swallow it and this reads as working.
            # Measured, not reasoned: swapping the two arms turns
            # `test_replying_to_a_concluded_dialogue_says_it_finished_not_that_it_is_missing`
            # back into a 404.
            raise HTTPException(status_code=409, detail=str(finished)) from finished
        except UnknownDialogue as missing:
            # A guessed id and another project's id are both 404 and stay
            # indistinguishable: confirming that an id a caller cannot use does
            # exist tells a prober which ids exist, and that is a distinction
            # not worth drawing.
            raise HTTPException(status_code=404, detail=str(missing)) from missing
        except DialogueInFlight as busy:
            raise HTTPException(status_code=409, detail=str(busy)) from busy
        except StopAsyncIteration:
            first = None
        except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
            first, failed = None, failure

        async def stream():
            try:
                if failed is not None:
                    raise failed
                if first is not None:
                    frame = _socratic_frame(first)
                    if frame is not None:
                        yield frame
                async for note in notes:
                    frame = _socratic_frame(note)
                    if frame is not None:
                        yield frame
            except Exception as failure:  # noqa: BLE001 -- the browser needs the reason
                yield f"data: {json.dumps({'type': 'error', 'detail': str(failure)})}\n\n"
            finally:
                # The only path that cancels the executor task when a reader
                # walks away. See `ask_project`'s `finally` for when this
                # actually runs -- it is generator finalisation, not disconnect.
                await notes.aclose()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/projects/{project_id}/dialogues/{dialogue_id}/attempts")
    async def post_dialogue_attempt(
        project_id: UUID, dialogue_id: UUID, body: SocraticAttempt
    ):
        """Mark one attempt at a component the dialogue asked, and remember it.

        **Unlike `post_ask_attempt`, this records.** An ask has no identity to
        record against; a dialogue is one -- a durable id meaning exactly "one
        reader working toward one goal" -- which is the design's §3 and the
        reason this surface can answer a question the ask path was allowed to
        skip.

        What that buys: the attempt is *recorded* against the dialogue id and
        survives a refresh both in storage and on the page.
        `GET .../dialogues/{dialogue_id}/progress` below is what reads it back
        (B114). For three commits it did not exist -- the only progress read
        route was `GET /api/sessions/{session_id}/progress`, which resolves its
        id through `_load(session_id)` and so cannot serve a dialogue id, and
        `progress_for` on the service is in-process only -- so the property this
        route was built for was real in the event log and invisible in the
        browser.

        The key is recovered by re-parsing the stored turn's `prompt`, which is
        the dialogue's utterance -- not `reply`, which is the reader's. Parsed
        raw and never through `project()`: that call is what strips the key for
        a browser, and this is the one caller that needs it.
        """
        if socratic is None or dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        turn = next(
            (t for t in await dialogues.turns_for(dialogue_id) if t.position == body.position),
            None,
        )
        if turn is None:
            raise HTTPException(
                status_code=404,
                detail=f"dialogue {dialogue_id} has no turn {body.position}",
            )
        component = parse_document(turn.prompt, path="").component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"turn {body.position} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        try:
            # `record_attempt` writes `ObserveSocraticProgress` to the
            # transcript, and `socratic_dialogue.decide` refuses EVERY command
            # against a concluded dialogue -- so an attempt posted at one is a
            # `CommandRejectedError`, which is a 500 without this. Unreachable
            # today, because nothing yet writes `SocraticDialogueConcluded`;
            # that is precisely why it is guarded now rather than when
            # concluding lands, since the plan that adds concluding has no
            # reason to look at this route. 409 matches every neighbouring
            # route (`delete_project` at :941 is the shape).
            #
            # `test_an_attempt_at_a_concluded_dialogue_is_a_409` concludes a
            # dialogue directly and posts to it; it is 500 with this `except`
            # removed, which is how it was proved.
            progress = await socratic.record_attempt(
                project_id=project_id,
                dialogue_id=dialogue_id,
                position=body.position,
                component_id=body.component_id,
                component_type=component.type,
                digest=hashlib.sha256(component.raw.encode("utf-8")).hexdigest(),
                response=body.response,
                correct=verdict.correct,
                score=verdict.score,
            )
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return verdict.as_json() | {
            "progress": item_view(progress, f"turn/{body.position}", body.component_id)
        }

    @app.post("/api/projects/{project_id}/dialogues/{dialogue_id}/end")
    async def end_dialogue(project_id: UUID, dialogue_id: UUID):
        """End a dialogue at the reader's request.

        POST and not DELETE: nothing is removed. The dialogue, its turns and
        every marked answer stay where they were and stay readable, which is the
        opposite of what the wrong verb would tell a reader.

        409 for one already concluded, matching `post_dialogue_attempt` and the
        reply route, so the page has one rule for every "this dialogue has
        finished" it can meet. The row read is against the projection, so two
        ends inside one projection lag both reach `socratic.end` -- which is why
        the `CommandRejectedError` arm is what makes a double-click safe, and not
        the row check. `test_ending_a_dialogue_twice_is_refused_rather_than_written_twice`
        is a 500 with that arm removed.

        The project check is the route's because `ConcludeSocraticDialogue`
        carries no project id and `decide` has nothing to compare: without it a
        guessed id ends someone else's dialogue and answers 200 -- measured, by
        deleting the check: `test_ending_a_dialogue_in_another_project_is_a_404`
        goes green-path and the other project's dialogue is concluded.
        """
        if socratic is None or dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await dialogues.get(dialogue_id)
        if row is None:
            # The same `caught_up()` retry `create_dialogue` takes, and for the
            # same reason: `InMemoryEventBus` dispatches synchronously today, so
            # a miss here is impossible today -- but this is the one route a
            # reader can reach a single frame after `start` resolves, and under
            # `background=True` a reader who ends immediately would be told the
            # dialogue does not exist. That is the exact "it exists, it
            # finished, your history is intact" confusion this surface spent a
            # task correcting in the other direction. Costs one projection wait
            # on a genuinely unknown id, which is the 404 path and not hot.
            # `test_ending_a_dialogue_the_projection_has_not_caught_up_to_yet_still_ends_it`
            # fails with this retry removed; the rest of the end tests pass
            # either way, because a synchronous bus never misses.
            await dialogues.caught_up()
            row = await dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        try:
            await socratic.end(project_id=project_id, dialogue_id=dialogue_id)
        except CommandRejectedError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"status": "concluded"}

    @app.get("/api/projects/{project_id}/dialogues/{dialogue_id}/progress")
    async def read_dialogue_progress(project_id: UUID, dialogue_id: UUID):
        """Every answer this reader has had marked in this dialogue (B114).

        **The read side of the route above, and the whole argument for this
        surface being its own principal.** An ask discards an attempt; a
        dialogue records one against a durable id. That claim -- "your answers
        survive a refresh" -- was true in storage and false on screen until this
        existed, because nothing could read the recording back.

        `scope: "dialogue"` is a third shape beside `progress_view`'s `"file"`
        and `"session"`, built rather than folded into the shared presenter.
        `dialogue_progress_view` carries the reasoning and the cost; the short
        form is that a dialogue's records are keyed by an *utterance*
        (`turn/{position}`) and a component id is only unique within one, so
        neither existing key fits, and widening a presenter two other surfaces
        depend on so a third can reuse it is how surfaces couple by accident.

        An untouched dialogue answers `{"items": {}}` and not a 404: nobody has
        answered anything yet is a fact about the reader, not about the id. So
        a test that asserts only the status passes against a route reading an
        id it was never given -- `test_a_recorded_attempt_is_readable_back`
        asserts a stored verdict through the body for that reason.

        Ownership is checked the way both neighbours check it, and a dialogue in
        another project is a 404 rather than a 403 for `read_dialogue`'s reason:
        telling a caller that an id they cannot read does exist is the
        distinction not worth drawing.
        """
        if socratic is None or dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        state = await socratic.progress_for(dialogue_id)
        return dialogue_progress_view(state, str(dialogue_id))

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

    def _conversation_view(row) -> dict[str, Any]:
        """One conversation, without its turns -- what a history list needs.

        `conversationId` is the id the ask stream announced in its first frame
        (`AskConversationOpened`), deliberately the same string: a list whose
        ids did not match what the page was told would let a reader open every
        past conversation except the one they are in.
        """
        return {
            "conversationId": str(row.id),
            "projectId": str(row.project_id),
            "openedAt": row.opened_at.isoformat(),
            "firstQuestion": row.first_question,
            "turnCount": row.turn_count,
        }

    @app.get("/api/projects/{project_id}/asks")
    async def list_asks(project_id: UUID):
        """Every conversation asked of this project, most recent first.

        **503 when the projection is unwired, not an empty 200** -- the same
        ruling as `read_ontology`, and it matters more here: an empty list is
        the right answer for a project nobody has asked anything, and an ask
        appends whether or not anything follows the log, so a build with no
        runner started is indistinguishable from a quiet project unless the
        route says so.
        """
        if asks is None:
            raise HTTPException(status_code=503, detail="ask history is not configured")
        return [_conversation_view(row) for row in await asks.for_project(project_id)]

    @app.get("/api/projects/{project_id}/asks/{conversation_id}")
    async def read_ask(project_id: UUID, conversation_id: UUID):
        """One conversation, with its turns in the order they were asked.

        404 covers both "no such conversation" and "that conversation belongs
        to another project", and they are deliberately the same answer: the
        second is a guessed id, and telling a caller that an id they cannot
        read does exist is the distinction not worth drawing.
        """
        if asks is None:
            raise HTTPException(status_code=503, detail="ask history is not configured")
        row = await asks.get(conversation_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no conversation {conversation_id} in {project_id}"
            )
        turns = await asks.turns_for(conversation_id)
        return {
            **_conversation_view(row),
            "turns": [
                {
                    "position": turn.position,
                    "question": turn.question,
                    # **No raw `answer` beside `blocks`, and its absence is the
                    # point.** This shipped `"answer": turn.answer` -- the
                    # stored markdown, fences and all -- next to blocks that
                    # correctly withheld `options[].correct`, so every reopened
                    # conversation handed back the answer key to every question
                    # in it. Measured 2026-08-18 by dumping the response body:
                    # `correct: true` was in the bytes while the projection one
                    # key to its right reported it withheld. `question` stays
                    # raw; it is the reader's own words and there is no key in
                    # it. Same shape as `read_dialogue`'s turns, fixed next
                    # door in 95076c9 for the same reason.
                    #
                    # The cost is that a client wanting the prose walks
                    # `blocks` for its markdown entries instead of reading one
                    # string. That is the right cost: a convenience field
                    # re-adding the source is a hole no projection can close.
                    # Nothing consumed it -- grepped `frontend/src` and the
                    # committed console, which reach only this route's
                    # `/attempts` sibling.
                    "blocks": answer_document(turn.answer)["blocks"],
                    "citations": turn.citations,
                    "recordedAt": turn.recorded_at.isoformat(),
                }
                for turn in turns
            ],
        }

    @app.post("/api/projects/{project_id}/asks/{conversation_id}/attempts")
    async def post_ask_attempt(project_id: UUID, conversation_id: UUID, body: AskAttempt):
        """Mark one attempt at a component the model wrote into an answer.

        The key is recovered by re-parsing the stored answer, which is the same
        move the file surface makes with `session.state.files` -- the browser
        holds the learner projection and could not mark this if it tried.

        **Nothing is recorded.** `LearnerProgress` keys on a session and an ask
        is deliberately not one; the design's section 4 gives the three
        reasons and B33 records the identity question this declines to answer
        by accident. The visible cost is that a refresh blanks the widgets.
        """
        if asks is None:
            raise HTTPException(status_code=503, detail="ask history is not configured")
        row = await asks.get(conversation_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no conversation {conversation_id} in {project_id}"
            )
        turns = await asks.turns_for(conversation_id)
        turn = next((t for t in turns if t.position == body.position), None)
        if turn is None:
            raise HTTPException(
                status_code=404,
                detail=f"conversation {conversation_id} has no turn {body.position}",
            )
        # Re-parsed raw, never through `project()`: that call is what strips
        # the key for a browser, and this is the one caller that needs it,
        # server-side, with nothing it returns carrying the block itself.
        document = parse_document(turn.answer, path="")
        component = document.component(body.component_id)
        if component is None:
            raise HTTPException(
                status_code=404,
                detail=f"turn {body.position} has no component {body.component_id!r}",
            )
        try:
            verdict = grade(component, body.response)
        except GradingError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return verdict.as_json()

    def _dialogue_view(row: SocraticDialogueRow) -> dict[str, Any]:
        """One dialogue, without its turns -- what a history list needs.

        `row` is annotated, unlike `_conversation_view`'s beside it: a renamed
        column then fails the type checker rather than the request. Nothing
        else here reads a row, so the looser sibling is left alone.

        Carries `goal` and `stoppingCondition` in the *list* view and not only
        in the detail one, deliberately. A reader picking a dialogue back up
        needs to know what it was aiming at, and the topic alone does not say:
        two dialogues about the Nicene settlement can be trying to do entirely
        different things. It is two strings per row on a page that is a cheap
        index, which is the same trade `firstQuestion` makes on the ask list.
        """
        return {
            "dialogueId": str(row.id),
            "projectId": str(row.project_id),
            "topic": row.topic,
            "goal": row.goal,
            "stoppingCondition": row.stopping_condition,
            # Both projected, never raw. `pendingPrompt` used to be
            # `row.pending_prompt`, which `read_models.py` writes from the
            # newest turn's prompt -- so an index page listing a reader's
            # dialogues handed back the answer key to every live question, on a
            # route nobody thought of as a rendering surface.
            # `test_the_answer_key_never_reaches_the_reader` measures the bytes
            # of all three surfaces rather than trusting any of them.
            "openingBlocks": dialogue_document(row.opening_prompt)["blocks"],
            # The question the reader is looking at now, which belongs to no
            # turn -- see `SocraticTurnRecorded`. A view that omitted it would
            # render a transcript ending on the reader's own words with
            # nothing asking them anything.
            "pendingBlocks": dialogue_document(row.pending_prompt)["blocks"],
            "openedAt": row.opened_at.isoformat(),
            "status": row.status,
            "concludedReason": row.concluded_reason,
            "turnCount": row.turn_count,
            "observations": row.observations,
        }

    @app.get("/api/projects/{project_id}/dialogues")
    async def list_dialogues(project_id: UUID):
        """Every dialogue held with this project, most recent first.

        **503 when the projection is unwired, not an empty 200** -- the same
        ruling `list_asks` makes and for the same reason: a dialogue appends
        whether or not anything follows the log, so a build with no runner
        started is indistinguishable from a project nobody has talked to unless
        the route says so.
        """
        if dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        return [_dialogue_view(row) for row in await dialogues.for_project(project_id)]

    @app.get("/api/projects/{project_id}/dialogues/{dialogue_id}")
    async def read_dialogue(project_id: UUID, dialogue_id: UUID):
        """One dialogue, with its exchanges in the order they happened.

        404 covers both "no such dialogue" and "that dialogue belongs to
        another project", and they are deliberately the same answer, matching
        `read_ask`: the second is a guessed id, and telling a caller that an id
        they cannot read does exist is the distinction not worth drawing.

        A turn's `blocks` are the dialogue's question and `reply` is the
        reader's answer -- the inverse of `read_ask`'s question/answer, because
        this surface runs in the opposite direction. A client that reused the
        ask's turn renderer here would draw every dialogue with the speakers
        swapped, and it would still read as a conversation.

        A turn pairs the reader's answer with the question it *produced*, so
        the transcript's first utterance is `openingBlocks` on the dialogue
        (not `openingPrompt` -- there is no raw prompt key on any of these
        surfaces any more, see `_dialogue_view`) and is on no turn: a client
        rendering only `turns` draws a reader answering something nobody asked.
        """
        if dialogues is None:
            raise HTTPException(status_code=503, detail="dialogues are not configured")
        row = await dialogues.get(dialogue_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(
                status_code=404, detail=f"no dialogue {dialogue_id} in {project_id}"
            )
        return {
            **_dialogue_view(row),
            "turns": [
                {
                    "position": turn.position,
                    # Projected, and no raw `prompt` beside it -- the same
                    # measurement as `_socratic_frame`'s. A stored turn is
                    # re-read on every resume, so a raw copy here would hand
                    # back the answer key to any reader who refreshed, for
                    # every question they had already been asked. `reply` is
                    # raw and stays raw: it is the reader's own words and there
                    # is no key in it.
                    "blocks": dialogue_document(turn.prompt)["blocks"],
                    "reply": turn.reply,
                    "citations": turn.citations,
                    "recordedAt": turn.recorded_at.isoformat(),
                }
                for turn in await dialogues.turns_for(dialogue_id)
            ],
        }

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
    async def allow_all_autonomy(session_id: UUID):
        """Stop asking about every hazard. No body, because there is nothing
        left to ask for.

        It used to take `include_stage_gates`, which crossed the workflow
        review gate as well. The console stopped sending it a slice before
        this and the gate itself is deleted a slice after, so the flag would
        be a switch over a tool that is on its way out. `relax_all`'s own
        parameter goes with that tool; this call takes its default until then,
        which is the behaviour a client omitting the flag already got.

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
        changed = instance.relax_all()
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

    # The download routes, which live in their own module rather than inline
    # here. They need three of the closures above rather than the collaborators
    # underneath them -- `_require_project`, `_graph_reader` and `_curriculum`
    # already encode what a 404 and a 503 mean on this surface, and a second
    # derivation of that would be free to disagree with this one about whether
    # an unwired graph store is a missing project. See `export.py`.
    app.include_router(
        export_router(
            ExportDeps(
                service=service,
                require_project=_require_project,
                graph_reader=_graph_reader,
                curriculum_of=_curriculum,
                authoring=authoring,
                # Three more closures, for `format=html` only. Same reasoning
                # as the three above: each already encodes what a 503 means
                # here, and re-deriving them in `export.py` would be a second
                # opinion about whether an unwired corpus is a missing project.
                corpus_reader=_reader,
                definitions=definitions,
                timeline_reader=_timeline_reader,
            )
        )
    )

    # The settings and provider routes. Registered unconditionally, with an
    # empty `SettingsDeps` when composition supplied none: the schema and the
    # provider catalogue are static data and answer either way, and a 404 for
    # the whole surface because one collaborator is unwired is the shape of
    # failure CLAUDE.md's "silent defaults" note is about -- it makes "never
    # wired" and "no such feature" identical to a caller.
    app.include_router(settings_router(settings or SettingsDeps()))

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
    else:
        # The console is a build artefact and is no longer committed, so a
        # fresh clone has no `static/` at all. Answering that with the router's
        # bare 404 makes a missing build look like a missing route -- the same
        # blank page a broken one gives, with nothing naming the cause. What a
        # test would fail on: `test_web_missing_console.py` asserts the 503 and
        # the command in its body.
        @app.get("/")
        async def console_not_built() -> PlainTextResponse:
            return PlainTextResponse(
                "The web console has not been built.\n"
                "Run `npm run build` in `frontend/`, then restart.\n",
                status_code=503,
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
            elif item.aggregate_type == MediaProposals.aggregate_type:
                # A `MediaProposals` aggregate is keyed on `project_id` alone
                # (see the aggregate's module docstring), so the aggregate id
                # is the project id with no lookup -- the same free addressing
                # `corpus_change` gets from a corpus sharing its project's
                # UUID. Without this branch these events fell to the generic
                # `feed_event` below, which sent `index: 0` and was silently
                # dropped by the frontend's log-frame branch.
                payload = media_change(item.aggregate_id, item.event)
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

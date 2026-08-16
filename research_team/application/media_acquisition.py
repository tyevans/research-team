"""Bytes from a URL into the corpus -- one implementation, two callers.

`download_media` is the primitive shared by the accept worker (a human
approves a judged candidate) and a gated agent tool (the model asks for one
directly). Both need the same answer to "is this actually media, and is it
small enough" -- writing it twice would let the two paths drift on exactly
the check that matters most.

That check is why `UnsupportedMedia` is not a nicety. A judged candidate
whose URL turns out to serve an HTML interstitial -- a login wall, a consent
page, a "your download will begin shortly" shim -- is a *failure*, not a
source. Nothing downstream can tell "this row is empty because the page was
gated" from "this row is empty because the transcriber found nothing to
transcribe" unless the HTML is refused before it is ever stored. A corpus row
with HTML bytes and an empty transcript is worse than no row at all: it reads
as a successful acquisition.

`max_bytes` is a parameter, not a constant baked into `download_media` itself,
because two different callers care about two different questions with the
same shape: an interactive upload and an unattended accept both want *a*
ceiling, but only one of them is this repository's own upload limit.
`MAX_UPLOAD_BYTES` below is that shared ceiling. It used to live in
`interfaces/web/app.py`, which worked while only the upload route needed it;
`MediaAcceptWorker` needs the identical number and the application layer may
not import from an outer layer (`tests/test_architecture.py`), so the
constant moved down to where both callers can reach it. `app.py` now imports
it from here rather than defining a second one -- two ceilings that happen to
agree today is a bug waiting for the day someone changes one of them.
"""

import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

import httpx
from eventsource import CommandRejectedError
from eventsource.application.aggregates.repository import AggregateRepository

from research_team.application.corpus_editing import CorpusEditor
from research_team.application.perception import (
    MediaBytesMissing,
    NotPerceivable,
    PerceptionUnavailable,
    SourceDropped,
)
from research_team.domain.media_proposals import (
    FailMediaProposal,
    MediaProposals,
    StoreMediaProposal,
)

MAX_UPLOAD_BYTES = 2 * 1024**3
"""The largest media this build will accept, from an upload or a download.

Streaming bounds *memory*; only this bounds *disk*. A two-hour recording is
comfortably under it and a runaway response is not, which is the line it is
drawn at -- there is no measurement behind the exact number, and raising it
is a one-line change with no other consequence. See `upload_media` in
`app.py` for the enforcement on that path and `download_media` above for
this one; both raise from inside their chunk loop rather than after reading
the whole body, for the same reason.
"""

logger = logging.getLogger(__name__)

_HEADERS = {
    # Identical string to `infrastructure/agent/fetch.py`'s `_HEADERS`.
    # Named honestly, with a contact URL, because that is what buys access
    # from Wikimedia and sites with a similar User-Agent policy -- see that
    # module's comment. A download tool that disguised itself as a browser
    # would be a worse trade even where it worked: it borrows trust the
    # operator did not extend to this software.
    "User-Agent": (
        "research-team/0.1 (https://github.com/tyevans/research-team; agent fetch)"
    ),
}

_ACCEPTED_PREFIXES = ("image/", "video/", "audio/")


class UnsupportedMedia(Exception):
    """The URL answered with a content-type outside `image/*`, `video/*` or
    `audio/*`.

    Not raised for a redirect any more -- see `MediaMoved` below, added in
    review: a `media_type` of `""` was indistinguishable from a genuinely
    missing content-type, so a caller could only tell "this asset is the
    wrong kind" from "this URL moved" by parsing a message string.
    """

    def __init__(self, media_type: str):
        self.media_type = media_type
        super().__init__(f"unsupported media type: {media_type or '(none)'}")


class MediaMoved(Exception):
    """The URL answered with a redirect, which this module does not follow.

    `fetch.py` makes the same choice when a grant is in play, for a reason
    that applies here without a grant in the picture at all: an unattended
    acquisition following a redirect would be leaving the process to a
    second address nobody judged, on the same authority that only covered
    the first one.

    Its own type rather than folding into `UnsupportedMedia` (as it used to)
    because the two answer different questions a caller needs told apart:
    "this asset is the wrong kind" is a dead end, "this URL moved" is
    something a person can act on -- re-propose `location`. A caller with the
    authority to follow it can also just re-issue the call against
    `location` directly, which is a decision rather than something this
    primitive makes silently.
    """

    def __init__(self, location: str):
        self.location = location
        super().__init__(f"that URL redirected to {location}, which was not followed")


class MediaTooLarge(Exception):
    """The body exceeded `max_bytes` partway through streaming.

    Raised from inside the chunk loop, once `total` crosses the ceiling --
    the same shape `app.py`'s `upload_media` chunk generator uses for the
    same reason: reporting a total only after reading the whole body would
    mean reading a body sized specifically to make that expensive.
    """

    def __init__(self, total: int):
        self.total = total
        super().__init__(f"media exceeds the {total} byte ceiling")


async def download_media(
    url: str, *, client: httpx.AsyncClient, max_bytes: int
) -> tuple[AsyncIterator[bytes], str]:
    """Fetch `url`'s bytes, refusing anything that is not image/video/audio.

    Redirects are not followed -- see `MediaMoved`'s docstring for why.

    The content-type check happens on the response headers, before any of
    the body is read. Streaming a gigabyte to discover it was an HTML
    interstitial would make the refusal this module exists for cost exactly
    what it was meant to avoid; `httpx.AsyncClient.send(..., stream=True)`
    returns headers without pulling the body, so the check and the refusal
    both happen before a single byte of it is asked for.

    **The returned iterator owns the underlying httpx response and closes it
    in a `finally`, on the generator's own exhaustion or an explicit
    `aclose()` -- never on anything else.** A caller must fully drain it or
    close it explicitly. Abandoning it partway -- for instance because a
    caller downstream (a corpus store, `CorpusEditor.store_media`'s `put`)
    raised mid-write -- leaves the generator suspended and the connection
    open until garbage collection gets to it, which asyncio does not promise
    will happen promptly, or at all, for a suspended coroutine. See
    `MediaAcceptWorker.run` for the caller that has to handle this
    deliberately.
    """
    request = client.build_request("GET", url, headers=_HEADERS)
    response = await client.send(request, stream=True)

    if response.is_redirect:
        location = response.headers.get("location", "(no Location header)")
        await response.aclose()
        raise MediaMoved(location)

    content_type = response.headers.get("content-type", "")
    media_type = content_type.split(";")[0].strip().lower()
    if not media_type.startswith(_ACCEPTED_PREFIXES):
        await response.aclose()
        raise UnsupportedMedia(media_type)

    async def chunks() -> AsyncIterator[bytes]:
        # Same shape as `app.py`'s upload `chunks()`: raise from inside the
        # loop, mid-stream, rather than buffering the whole body to measure
        # it first. `aiter_bytes()` is what `stream=True` buys -- the
        # headers above were already read without touching this.
        total = 0
        try:
            async for part in response.aiter_bytes():
                total += len(part)
                if total > max_bytes:
                    raise MediaTooLarge(total)
                yield part
        finally:
            await response.aclose()

    return chunks(), media_type


@dataclass(frozen=True)
class AcceptedProposal:
    """What `MediaAcceptWorker` needs to know about one accepted proposal.

    A narrow projection of `MediaProposalRow`, not that type itself: this
    module may not import `infrastructure/persistence/read_models.py`
    (`tests/test_architecture.py`), and the worker has no use for the fields
    that exist for the review pane -- `reason`, `thumbnail_url`, `query`.
    `project_id` is `str` rather than `UUID` because it is threaded straight
    into `StoreMediaProposal`/`FailMediaProposal`, which are dataclasses
    typed that way to match every other command in `media_proposals.py`.
    """

    project_id: str
    page_url: str
    asset_url: str
    title: str


class MediaProposalReadPort(Protocol):
    """Looks up one accepted proposal's details, by id.

    `None` for an id the read model has never seen -- a dispatch racing
    ahead of its own projection, or a caller holding a stale id -- rather
    than raising, because there is nothing this worker could report the
    failure *against*: `FailMediaProposal` needs a `project_id` this read is
    the only source of, and `decide` refuses the command for an unknown
    proposal anyway. `run` treats it as nothing to do.
    """

    async def get(self, proposal_id: str) -> AcceptedProposal | None: ...


class MediaPerceiverPort(Protocol):
    """The one method `MediaAcceptWorker` uses off `MediaPerceiver`.

    A structural protocol rather than importing `MediaPerceiver` itself: nothing
    here needs its `PerceptionReport`, and a narrower dependency is a smaller
    fake in this module's tests.
    """

    async def perceive(self, project_id: UUID, source_id: str) -> object: ...


class MediaAcceptWorker:
    """Runs after a person accepts a proposal: download, store, perceive, record.

    The four steps run in this order and for this reason each:

    1. **Download**, under `max_bytes`. `UnsupportedMedia`, `MediaMoved` and
       `MediaTooLarge` are the three ways it can fail, and all three are
       refusals this worker can explain -- see `_fail`.
    2. **`CorpusEditor.store_media`**, with `uri=detail.page_url`. The *page*
       URL, not `detail.asset_url` the download just fetched: provenance is
       where a thing was found, not the CDN path it happened to be served
       from -- a reader citing this source wants the gallery page, not a
       signed S3 URL that may not resolve tomorrow.
    3. **Perception, eagerly**, so the source is never visible in a
       half-perceived state a moment after it exists. Best-effort, not a
       gate: `NotPerceivable`, `SourceDropped`, `MediaBytesMissing` and
       `PerceptionUnavailable` are all outcomes `perceive_source`'s own route
       already treats as ordinary (404/410/503, not 500), and failing the
       whole accept over "this install has no vision model configured" would
       discard a source that downloaded and stored correctly, over a
       capability question a person can revisit later through that same
       route. An exception *not* in that set is a bug in the perceiving path
       and is left to propagate -- the difference between "the source is
       fine, perception can wait" and "something is broken" is exactly the
       set of named types.
    4. **Record the outcome** -- `StoreMediaProposal` on success,
       `FailMediaProposal` on a download refusal.

    **A worker retrying after a crash must treat an "already stored" refusal
    as its own success signal.** `StoreMediaProposal` against a proposal
    already `stored` is refused by `decide`, not made idempotent -- `decide`
    cannot arbitrate between two different `source_id`s both claiming to be
    one proposal's result (see the controller ruling in the task-11 brief).
    So a crash between a successful `store_media`/perceive and the append
    that would have recorded it leaves the proposal `accepted`; a re-run
    downloads and stores again (harmless -- `source_id` is `proposal_id`,
    content-addressed, so a re-fetch of unchanged bytes lands on the same
    blob) and then reaches `StoreMediaProposal` a second time, which
    `decide` now refuses because the first append this time *did* land. That
    refusal is read back and, if the state it refused against is already
    `stored`, treated as success rather than surfaced as an error --
    anything else refusing is a genuine problem and is not swallowed the
    same way.
    """

    def __init__(
        self,
        *,
        reads: MediaProposalReadPort,
        proposals: AggregateRepository[MediaProposals],
        editor: CorpusEditor,
        perceiver: MediaPerceiverPort,
        client: httpx.AsyncClient,
        max_bytes: int = MAX_UPLOAD_BYTES,
    ) -> None:
        self._reads = reads
        self._proposals = proposals
        self._editor = editor
        self._perceiver = perceiver
        self._client = client
        self._max_bytes = max_bytes

    async def run(self, proposal_id: str) -> None:
        detail = await self._reads.get(proposal_id)
        if detail is None:
            return

        project_id = UUID(detail.project_id)
        # The proposal's own id, not a freshly minted one: it is already
        # unique (`decide`'s "unknown proposal" guard makes `proposal_id`
        # unique domain-wide, per `MediaProposalRow.row_id`'s docstring), and
        # reusing it is what makes a re-run's `store_media` land on the same
        # `source_id` rather than creating a second corpus row for a retried
        # accept.
        source_id = proposal_id

        try:
            stream, media_type = await download_media(
                detail.asset_url, client=self._client, max_bytes=self._max_bytes
            )
        except (UnsupportedMedia, MediaMoved, MediaTooLarge) as error:
            # `str(error)` already distinguishes the shapes a person needs
            # told apart: `UnsupportedMedia` names the refused media type
            # ("this asset is the wrong kind"); `MediaMoved` names the
            # Location that was not followed ("this URL moved" -- something
            # a person can act on by re-proposing it, unlike a generic
            # refusal); `MediaTooLarge` names the ceiling crossed. Collapsing
            # any of them into a generic "download failed" would lose
            # exactly the distinction the pane needs to show.
            await self._fail(project_id, proposal_id, str(error))
            return

        try:
            await self._editor.store_media(
                project_id,
                source_id,
                stream,
                media_type,
                uri=detail.page_url,
                title=detail.title or None,
            )
        except BaseException:
            # `store_media` failing after it started reading `stream` -- a
            # blob-store I/O error, most plausibly -- leaves
            # `download_media`'s generator suspended mid-iteration. Its own
            # `finally` closes the underlying response only on exhaustion or
            # an explicit `aclose()`; an abandoned suspended generator is not
            # promised to be collected promptly, so the connection would sit
            # open until it happens to be. Close it explicitly rather than
            # trust that.
            await stream.aclose()
            raise

        await self._perceive_eagerly(project_id, proposal_id, source_id)
        await self._record_stored(project_id, proposal_id, source_id)

    async def _perceive_eagerly(
        self, project_id: UUID, proposal_id: str, source_id: str
    ) -> None:
        # Ordinary, named outcomes -- see the class docstring's step 3. The
        # source is stored correctly either way, so this logs rather than
        # fails the accept -- but a silent suppression would make a stored
        # medium with no derived text (inert in the graph: it answers no
        # questions) indistinguishable, in the review pane, from a fully
        # successful acquisition. `MediaPerceiver.unperceived` is how this
        # is meant to be found and cleared later -- it already answers
        # "which media has no derived text", and a field on the proposal
        # duplicating that fact is a second source of truth for it.
        try:
            await self._perceiver.perceive(project_id, source_id)
        except (NotPerceivable, SourceDropped, MediaBytesMissing, PerceptionUnavailable):
            logger.warning(
                "eager perception failed for proposal %s, source %s in project %s",
                proposal_id,
                source_id,
                project_id,
                exc_info=True,
            )

    async def _record_stored(self, project_id: UUID, proposal_id: str, source_id: str) -> None:
        aggregate = await self._proposals.load_or_create(project_id)
        try:
            aggregate.execute(
                StoreMediaProposal(
                    project_id=str(project_id), proposal_id=proposal_id, source_id=source_id
                )
            )
        except CommandRejectedError:
            # See the class docstring's crash-retry paragraph: refused
            # because a previous run already recorded this is this worker's
            # own success, not an error. Any other refused state (rejected,
            # failed by a previous run) is a real problem and is re-raised.
            reloaded = await self._proposals.load_or_create(project_id)
            if reloaded.state.proposals[proposal_id].status == "stored":
                return
            raise
        await self._proposals.save(aggregate)

    async def _fail(self, project_id: UUID, proposal_id: str, error: str) -> None:
        aggregate = await self._proposals.load_or_create(project_id)
        try:
            aggregate.execute(
                FailMediaProposal(
                    project_id=str(project_id), proposal_id=proposal_id, error=error
                )
            )
        except CommandRejectedError:
            # Mirrors `_record_stored`'s crash-retry handling: a re-run that
            # fails identically after a previous run already recorded the
            # failure should not raise over its own prior work.
            reloaded = await self._proposals.load_or_create(project_id)
            if reloaded.state.proposals[proposal_id].status == "failed":
                return
            raise
        await self._proposals.save(aggregate)

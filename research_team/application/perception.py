"""Making a stored medium legible.

The port takes a digest and no mimetype. Detection is the perceiving library's
job and it does it from content -- measured on 2026-08-15 and re-taken against
`readeverything` 0.2.0 on 2026-08-16, an extensionless file named for its own
sha256 was identified as `video/mp4` -- so handing it this repository's stored
`media_type` would be giving a sniffed guess to something with a better
sniffer.

Nothing in this module names a library. `LocatorSpan.locator` is a plain dict
for exactly that reason: the adapter under `infrastructure/perception/` is the
only place that should know which library perceives, and the five `kind`
spellings below are this repository's own vocabulary rather than a re-export of
someone's union type.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.application.corpus_read import MediaHandle
from research_team.application.document_extraction import CorpusReaders, UnknownDocument
from research_team.domain.corpus import Corpus, MediaRecord, StoreDerivedText, TextRecord

LOCATOR_KINDS = ("time", "page", "bbox", "char", "byte")
"""Every `kind` a `LocatorSpan.locator` may carry.

Written down here rather than left implicit in the adapter. **Nothing
dispatches on these tags today**, and this docstring claimed three readers did
-- a resolver, a citation renderer and the timeline -- until a reviewer counted
them. What actually reads a locator is `locators.resolve`, which checks only
that `kind` is a `str` and passes unfamiliar spellings straight through
(deliberately -- see its docstring), and nothing renders them at all. The three
named readers are sub-project 4's, not this slice's.

So the value here is that the adapter's five `match` arms have one written-down
vocabulary to agree with, rather than that anything currently switches on it.
That is still worth the constant: the tags are being *written into stored
events* now, so a spelling invented later at a reader would silently match
nothing in every transcript already on disk.

The tag is always explicit: inferring the kind from which keys are present
makes an unrecognised locator look like whichever known one it shares a key
with, where an explicit tag makes it visibly unknown.

The shapes, per kind:

- `{"kind": "time", "start_s": float, "end_s": float}`
- `{"kind": "page", "page": int}`
- `{"kind": "bbox", "page": int | None, "x": float, "y": float, "w": float, "h": float}`
- `{"kind": "char", "start": int, "end": int}`
- `{"kind": "byte", "start": int, "end": int}`
"""


@dataclass(frozen=True)
class LocatorSpan:
    """A stretch of the rendered text, and where in the medium it came from."""

    char_start: int
    char_end: int
    locator: dict[str, object]
    """The locator as JSON-ready data, tagged with one of `LOCATOR_KINDS`. A
    dict rather than a library's union type so nothing above this line imports
    the perceiving library: the adapter is the only place that should know
    which one it is."""


@dataclass(frozen=True)
class Perceived:
    """What one reading of one medium produced."""

    text: str
    locators: tuple[LocatorSpan, ...]
    fingerprint: str
    """What invalidates a derived transcript. A function of the *configured*
    model revisions, so swapping the vision model changes it and a stored
    reading taken with the old one stops being reused."""
    degradations: tuple[str, ...]
    """What could not be done, in words, rather than what failed. A missing
    capability degrades rather than raising -- measured 2026-08-16: with no
    vision model a video still renders, carrying `vision unavailable: frames
    were not described`."""


@dataclass(frozen=True)
class PerceptionCapabilities:
    """What this install can actually do.

    A structure rather than a boolean because the 503 has to name what is
    absent: "no vision model configured" and "ffmpeg not found" send an
    operator to two different places, and a route that can only say "not
    configured" sends them to neither.
    """

    vision: bool
    asr: bool
    ffmpeg: bool

    def any_model(self) -> bool:
        """Whether anything here can perceive rather than merely describe.

        With neither model, `represent` still returns a metadata stub -- "Image
        x.png, 64x48 PNG, 469 bytes" -- and storing that would put a sentence
        no human wrote into the corpus to be extracted as evidence. So this is
        the question the route asks before doing any work.
        """
        return self.vision or self.asr

    def missing(self) -> tuple[str, ...]:
        absent = []
        if not self.vision:
            absent.append("no vision model (AGENT_VISION_MODEL)")
        if not self.asr:
            absent.append("no transcriber (AGENT_TRANSCRIBER_URL)")
        if not self.ffmpeg:
            # Names both binaries because `ffmpeg_present()` requires both:
            # an operator told only "ffmpeg" would install it, restart, and
            # meet the identical 503 with `ffprobe` still missing.
            absent.append("ffmpeg or ffprobe not found on PATH")
        return tuple(absent)


class PerceptionPort(Protocol):
    async def perceive(self, *, sha256: str, max_chars: int) -> Perceived:
        """Read the blob stored under `sha256` into text and locators.

        Raises rather than returning a stub when the medium cannot be read at
        all; a capability that is merely absent arrives as a `degradation`.
        """
        ...

    def capabilities(self) -> PerceptionCapabilities:
        """What this install can do, without awaiting anything.

        Synchronous on purpose, and the reason is a caller: the web route
        consults this *before* enqueuing perception work, and the library's own
        builder is `async def`. See `ReadEverythingPerception` for the ruling
        this follows from -- capabilities are declared from configuration
        rather than probed, so this needs no event loop.
        """
        ...


#: Reads the configured character cap for one perception. A callable rather
#: than an int so nothing in the application layer imports
#: `infrastructure.config` -- no other module here does -- and so a cap changed
#: in the environment is not frozen into whatever object composition built
#: first.
MaxChars = Callable[[], int]

#: What a derived text source is called. One spelling, in one place: the domain
#: deliberately does not enforce it (see `StoreDerivedText`'s docstring), so
#: this function is the only thing keeping the perceiver, the console and
#: anything that later resolves a transcript agreeing about the name.
DERIVED_SUFFIX = "#perceived"


def derived_source_id(parent: str) -> str:
    """The `source_id` a perception of `parent` is stored under."""
    return f"{parent}{DERIVED_SUFFIX}"


class NotPerceivable(Exception):
    """The named source holds text; there is nothing in it to perceive.

    Its own type rather than `UnknownDocument` because the two answer
    different status codes and send an operator to different places: "no such
    id" is a typo, "that id holds prose" is a misunderstanding of what the
    button does. `decide` refuses this too, and would say so -- but only
    *after* the port has been called and paid for, which is the one thing this
    use case exists to sequence.
    """


class SourceDropped(Exception):
    """The medium is here and somebody excluded it.

    Its own type because the alternative was answering "no such source", which
    is the conflation `CorpusReadPort.read_media` exists to forbid: an operator
    told a recording does not exist goes looking for an ingest that never
    happened, rather than at the drop somebody made on purpose. Reached here by
    a route that docstring did not anticipate -- `read_media` hides a dropped
    row by default and `read_document` answers None for media, so both reads
    fail and the honest reason is in neither answer.

    Refusing rather than perceiving is `unextracted`'s reasoning: a drop is a
    judgement that the source should not inform the project, and a transcript
    of it would be extracted into the graph the drop was meant to keep it out
    of.
    """


class MediaBytesMissing(Exception):
    """The record is here and its blob is not: a dangling reference.

    Detected here rather than at the route, and the reason is which layer
    holds the handle. `perceive` already has the `MediaHandle`; the route has
    only a project and a `source_id`, so answering 410 from up there would mean
    issuing a second `read_media` purely to inspect `stat` -- a second read of
    one record, in the layer this application deliberately keeps out of the
    business of assembling readers.

    Advisory by nature, and that is not an argument against it: the blob can
    vanish between this check and the read either way. What it buys is that the
    operator sees the same answer the content route gives one click away (410,
    "the bytes are no longer stored") instead of a library traceback from
    inside the perceiving adapter.
    """


class PerceptionUnavailable(Exception):
    """This install has no model that could read a medium.

    Raised rather than degraded, and this is the load-bearing refusal of the
    whole feature. With neither a vision model nor a transcriber `represent`
    still succeeds -- it returns a metadata stub, "Image x, 64x48 PNG, 469
    bytes" -- and storing that would put a sentence no human wrote into the
    corpus, where extraction would read it as evidence and a citation would
    quote it back as if a source had said it.

    Carries `PerceptionCapabilities.missing()` in its message: a 503 that can
    only say "not configured" sends nobody anywhere.
    """


@dataclass(frozen=True)
class PerceptionReport:
    """What one perception stored, for a caller that has to say so.

    Carries `locator_map` as the JSON that was written rather than as the
    `LocatorSpan` tuple it came from: this is the record of what the event
    holds, and a caller comparing it against a stored row should be comparing
    the same string. `application/locators.py` is what turns it back into
    locators.
    """

    source_id: str
    derived_from: str
    char_count: int
    locator_map: str
    perceived_with: str
    degradations: tuple[str, ...]


class MediaPerceiver:
    """Reads a stored medium through the perception port into a derived source.

    `DocumentExtractor`'s shape, deliberately: keyword-only collaborators and a
    `corpus_readers` callable per project, because both are services the web
    layer must not assemble and both serve any project rather than one.

    What it buys, and the reason this is a use case and not a route body: a
    medium becomes an ordinary text source. Nothing downstream -- chunking,
    extraction, `corpus_spans.quote`, the citation renderer -- learns a thing
    about media. The one place the medium reappears is `locators.resolve`,
    which is pure and reads a field.
    """

    def __init__(
        self,
        *,
        port: PerceptionPort,
        corpus_readers: CorpusReaders,
        corpus: AggregateRepository[Corpus],
        max_chars: MaxChars,
    ) -> None:
        self._port = port
        self._corpus_readers = corpus_readers
        self._corpus = corpus
        self._max_chars = max_chars

    async def perceive(self, project_id: UUID, source_id: str) -> PerceptionReport:
        """Read one stored medium and keep what came back.

        **Perceive first, store second**, mirroring `store_media`'s reasoning
        one level up. The cost of this order is that a store the domain
        refuses leaves a model call already paid for, which is money. The cost
        of the other order is a derived record claiming a perception that did
        not happen -- the dangling reference this design refused to allow,
        pointing at a reading rather than at bytes. Cheap failure over
        expensive one, the same trade `store_media` makes between an orphan
        blob and a record pointing at nothing.
        `test_a_failed_perception_stores_nothing` is what holds it.

        The two refusals below both precede the call, and for one reason
        between them: each is a case where the port would be paid for an
        answer that is thrown away. `decide` refuses a text parent as well,
        and better -- but only after the money is spent, which is why this is
        not the duplicate pre-check it looks like.
        """
        handle = await self.resolve(project_id, source_id)

        capabilities = self._port.capabilities()
        if not capabilities.any_model():
            raise PerceptionUnavailable(
                "this install cannot perceive media: " + "; ".join(capabilities.missing())
            )

        perceived = await self._port.perceive(
            # The digest, not the source id and not a path: the blob store is
            # content-addressed and the digest is the whole address.
            sha256=handle.record.sha256,
            max_chars=self._max_chars(),
        )

        locator_map = json.dumps(
            [
                {
                    "char_start": span.char_start,
                    "char_end": span.char_end,
                    "locator": span.locator,
                }
                for span in perceived.locators
            ]
        )
        parent_title = handle.record.title or handle.record.source_id
        derived = derived_source_id(source_id)
        corpus = await self._corpus.load_or_create(project_id)
        corpus.execute(
            StoreDerivedText(
                corpus_id=project_id,
                source_id=derived,
                derived_from=source_id,
                text=perceived.text,
                # No sha256: `decide` computes it, because this is text and
                # the domain has the bytes. Supplying one would make
                # `by_digest` a claim where it is currently a fact.
                locator_map=locator_map,
                perceived_with=perceived.fingerprint,
                degradations=json.dumps(list(perceived.degradations)),
                title=f"{parent_title} (perceived)",
            )
        )
        await self._corpus.save(corpus)
        return PerceptionReport(
            source_id=derived,
            derived_from=source_id,
            char_count=len(perceived.text),
            locator_map=locator_map,
            perceived_with=perceived.fingerprint,
            degradations=perceived.degradations,
        )

    async def resolve(self, project_id: UUID, source_id: str) -> MediaHandle:
        """The medium this id names, or the reason there is nothing to read.

        Split out of `perceive` rather than duplicated at its one other
        caller. The web route enqueues perception rather than running it --
        transcribing an hour of audio would hold the connection open for
        minutes -- but it still has to answer *now* whether the id names a
        medium at all, because a 404 delivered later through a progress pane
        is a 404 nobody connects to the button they pressed. Two copies of
        these four refusals would drift, and the drift would show up as the
        route and the job disagreeing about what a dropped source is.

        Cheap on purpose: every read here is against the corpus projection,
        and none of it touches the perception port or the blob bytes. That is
        what makes it affordable to run twice -- once at the route, once again
        inside `perceive` when the job actually starts.
        """
        reader = self._corpus_readers(project_id)
        handle = await reader.read_media(source_id)
        if handle is None:
            # Three states arrive here as one `None`, and every extra read
            # below is on the failure path only. Text: `read_media` declines
            # it, `read_document` finds it. Dropped media: `read_media` hides
            # it by default, and only the second read with `include_dropped`
            # can tell it from an id nobody ever claimed -- which is the
            # distinction `CorpusReadPort.read_media`'s docstring insists on
            # and which this method got wrong until a reviewer measured it.
            if await reader.read_document(source_id, include_dropped=True) is not None:
                raise NotPerceivable(
                    f"source {source_id!r} holds text; there is nothing in it to perceive"
                )
            dropped = await reader.read_media(source_id, include_dropped=True)
            if dropped is not None:
                raise SourceDropped(
                    f"source {source_id!r} was dropped: {dropped.record.dropped_reason}"
                )
            raise UnknownDocument(f"no media source {source_id!r} in project {project_id}")

        if handle.stat is None:
            # Before the capability check and before the port, because it is
            # free and the other two are not: there is no reading to be had
            # from bytes that are gone, whatever this install can do.
            raise MediaBytesMissing(f"the bytes for {source_id!r} are no longer stored")

        return handle

    async def unperceived(self, project_id: UUID) -> tuple[str, ...]:
        """Every live medium with no transcript, in listing order.

        **This has no caller yet, and that is deliberate rather than a loose
        end.** There is no batch-perceive route and no "Transcribe all" control
        in this slice; the control is a later one's, and `grep` finds only
        `tests/application/test_perception.py` calling this today. It was
        written here because the exclusion rule below -- that batch perception
        must not resurrect a dropped transcript -- was worked out here, against
        this slice's own fold, and is recorded in the ledger as the longest
        ruling of the run. Deleting it and re-deriving it beside the future
        button would mean re-deriving the reasoning too, and the reasoning is
        the expensive part. Read the guarantee below as describing what batch
        perception *will* do, not as one anything currently provides.

        The mirror of `DocumentExtractor.unextracted`, down to taking the
        listing's order so a "perceive all" walks the page the reader is
        looking at.

        **Perceivedness is read off `derived_from`, not off the id
        convention.** `StoreDerivedText.source_id` is unconstrained by design
        so a second model can perceive one medium under its own id, and a
        check for `f"{parent}#perceived"` would go on offering perception for a
        medium that already has a transcript under some other name -- the
        operator who accepted would get a third.

        **The two sets are drawn from the listing at different widths, and
        that asymmetry is the whole of this method's care.** A *dropped medium*
        is not a candidate, for `unextracted`'s reason: a drop is a judgement
        that the source should not inform the project, and a transcript of it
        would be extracted into the graph the drop was meant to keep it out of.
        But a *dropped transcript* still counts its parent as perceived, and
        the default listing cannot say so because it hides the row.

        What the narrower reading would cost is a wrong write, not a stalled
        queue -- this docstring claimed the opposite until a reviewer measured
        it. Superseding a derived source does not merely replace the text: the
        `CorpusDerivedTextStored` fold builds a fresh `TextRecord` carrying no
        `dropped_reason`, so the exclusion is erased and the transcript returns
        to the listing, to chunking and to extraction. A batch "perceive all"
        that re-offered such a parent would undo an operator's deliberate
        exclusion with nobody having asked for it.

        **An explicit single `perceive` may still un-drop, and that is
        accepted rather than deferred.** It is not an anomaly of this feature;
        it is the same property every source in this corpus has.
        `CorpusEditor.restore` is *implemented* as a re-store and says so, on
        the strength of `evolve` not carrying `dropped_reason` across, guarded
        by `test_storing_over_a_dropped_source_id_brings_it_back`. Refusing it
        only for derived text would make perception the one source kind whose
        re-store behaves differently, for a rule nothing else obeys. What is
        closed here is the path where nobody chose it: batch perception can no
        longer reach the case at all.

        Order is the listing's, so a "perceive all" walks the page the reader
        is looking at -- `unextracted`'s reason.
        """
        # One read at the wider width rather than two reads at two widths.
        # Both sets come out of it -- dropped rows are filtered back out for
        # the candidates below -- and the alternative pays a second projection
        # query to have the default listing do that filtering implicitly. The
        # cost of this shape is that "dropped media are excluded" is now a
        # condition a reader has to see here, where it used to be inherited
        # from `list_sources`' default; it is spelled out rather than implied
        # for exactly that reason.
        listings = await self._corpus_readers(project_id).list_sources(include_dropped=True)
        perceived = {
            listing.record.derived_from
            for listing in listings
            # `isinstance` rather than `getattr(..., "derived_from", None)`:
            # `SourceRecord` is a discriminated union of two shapes the type
            # checker can see, and a `getattr` would quietly report every
            # medium as unperceived if the field were ever renamed.
            if isinstance(listing.record, TextRecord) and listing.record.derived_from
        }
        return tuple(
            listing.record.source_id
            for listing in listings
            if isinstance(listing.record, MediaRecord)
            and listing.record.dropped_reason is None
            and listing.record.source_id not in perceived
        )

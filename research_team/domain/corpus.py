"""A corpus: the source text a project was built from, kept rather than discarded.

Extraction reads a document, writes a graph, and throws the document away.
That makes every provenance claim downstream unfalsifiable -- a citation can
name a source, but nothing can go back and check that the source says it. This
aggregate is the other half: the log keeps the bytes, so a quote can be
verified against them years later.

**The state holds no text.** `DocumentRecord` carries metadata and a digest;
the text lives only in the `CorpusDocumentStored` payload, and retrieval is a
read model's job. Snapshots are taken every 50 events, and a text field here
would fold whole corpora into each one. The cost is that answering "what does
s1 say" needs a projection rather than a state read, which is the trade we
want: the fold stays cheap and constant-sized, and retrieval is a query.

**No creation event.** A corpus has no attributes of its own -- no name, no
settings -- so `CorpusCreated` would be an empty payload whose only effect is
to make the first store fail if a caller forgot it. It shares its UUID with
its project and is a distinct stream by `StreamId(aggregate_id, "Corpus")`,
so there is nothing for creation to establish that the project's own creation
has not already established. The first `CorpusDocumentStored` creates it. The
house `status: "new" | "created"` vocabulary is kept anyway, because it is
what a reader of `project.py` expects and because "empty" still has to answer
for itself: a drop against a corpus that never held anything is a caller bug
worth naming, not a silent no-op.

**Supersession is by `source_id`.** Storing a `source_id` that already exists
replaces its record -- a re-fetch of the same URI is a revision of one
document, not a second document. The earlier text is still in the log and
still folds into any read model that wants versions; only the index moves to
the new bytes, since "current" is the only question state can usefully answer.
The alternative, rejecting a re-store and forcing a drop first, would make the
ordinary case (refetching a page that changed) a two-command dance whose
intermediate state is a corpus with a hole in it.

Identical bytes under a *different* `source_id` are detectable via `by_digest`
but not refused. The same document legitimately arrives at two URIs, and the
domain has no basis for choosing which one the caller meant; detection is what
the ingest path needs to skip re-extraction, and prevention is not its call.

**One `source_id` namespace holds both text and media.** A source is a source
whichever kind its bytes are, `by_digest` and supersession-by-`source_id` mean
the same thing for either, and a second namespace would need its own answer to
every question this module already answers for text -- for no reader-visible
gain, since nothing downstream cares which namespace an id came from. A
`source_id` cannot change kind once claimed: `decide` refuses a store that
would flip it, in both directions, because supersession is a revision of one
source and a kind change is a different source wearing the old id.

**For media the digest is supplied, and that is a deliberate weakening.** The
bytes never reach the domain -- holding a video in memory to hand it to a pure
function is not a thing to do -- so `CorpusMediaStored.sha256` is what the blob
store computed while streaming, and `by_digest` is a claim for those entries
rather than a fact. `application/blobs.py` carries the mitigation: `put`
returns the digest and there is no parameter by which a caller could offer a
different one, so a wrong digest requires a bug in the store rather than a
mistake at a call site.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal
from uuid import UUID

from eventsource import CommandRejectedError, DeciderAggregate, DomainEvent, register_event
from pydantic import BaseModel, Field

UNREADABLE_DEGRADATIONS = ("<degradations could not be read from the event>",)
"""What `evolve` records when an event's `degradations` payload will not parse.

Angle-bracketed so it cannot be mistaken for a degradation a perception model
actually reported -- this is the state saying it failed to read a field, not a
transcriber saying it failed to see something. Exported rather than inlined
because a reader of a `TextRecord` may want to test for it, and a string
literal repeated at both ends is a string literal that drifts at one end.
"""


@register_event
class CorpusDocumentStored(DomainEvent):
    """The text of a source, kept verbatim. Also the corpus's creation event.

    `published_at` is text, not a date: sources report dates in whatever shape
    they please, and parsing at the boundary would either lose the ones that
    do not fit or invent precision the source never claimed.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    text: str
    sha256: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


@register_event
class CorpusDocumentDropped(DomainEvent):
    """A source was excluded, and why.

    The reason is required and non-empty. A document that disappears without
    one is indistinguishable from one that was never fetched, which is the
    silent-drop failure the intake research independently called the worst
    one -- the corpus looks complete and nobody can tell that it is not.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    reason: str


@register_event
class CorpusMediaStored(DomainEvent):
    """A media source was stored: the claim about it, never its bytes.

    `sha256` is where the bytes are and what proves they are the ones this
    event meant. Unlike `CorpusDocumentStored.sha256` it is *supplied* rather
    than computed -- see this module's docstring, and `application/blobs.py`
    for why that is a hazard rather than a trap.

    `published_at` is text for the same reason it is on the document event:
    sources report dates in whatever shape they please.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    sha256: str
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


@register_event
class CorpusDerivedTextStored(DomainEvent):
    """What a perception model made of a stored medium.

    A separate event from `CorpusDocumentStored` because a derived source has
    to stay permanently distinguishable from a fetched one: a quote from a
    transcript is a quote from a model's reading of an audio track, and
    provenance that cannot tell those apart is the unfalsifiable-provenance
    failure this module exists to prevent, one level up.

    `locator_map` is JSON rather than a structured field because the locator
    union (`TimeSpan | PageRef | BBox | CharSpan | ByteRange`) belongs to
    `readeverything` and will evolve there. A structured field here would make
    every locator kind it adds a schema change in this repository, in exchange
    for queries nobody makes -- the map is read whole or not at all, since
    resolving one offset needs every segment.

    `perceived_with` is `CapabilitySet.fingerprint()`: which models, at which
    revisions, produced this. Two transcripts of one video from two models are
    two different claims, and this is the field that says so.

    Additive: a build that predates this event ignores it in `evolve` and
    replays cleanly, which is what "events already written are not rewritten"
    buys. Nothing about `CorpusDocumentStored`'s shape changes.
    """

    aggregate_type: str = "Corpus"
    source_id: str
    derived_from: str
    text: str
    sha256: str
    locator_map: str
    perceived_with: str
    degradations: str
    title: str | None = None
    note: str | None = None
    """An operator's annotation, the same field every other source kind has.

    Added when `CorpusEditor.revise` was taught to edit a transcript: without
    it, a re-store of a derived record had nowhere to carry a note, so a
    transcript would have been the one source kind nobody could annotate.
    Additive and defaulted, so every `CorpusDerivedTextStored` written before
    it existed folds to `note=None` -- which is what those transcripts have.

    No `uri`, `published_at` or `fetched_at` beside it, and that is a
    distinction rather than an omission: those three are provenance for
    by-reference content the corpus did not create, and a transcript was not
    fetched from anywhere. Its provenance is `derived_from` plus
    `perceived_with`, and the medium it came from carries the rest.
    """


@dataclass(frozen=True)
class StoreSourceDocument:
    #: Which corpus to store into. Storing is what brings a corpus into
    #: existence, so this is the one command whose target cannot be read back
    #: off the state -- there is no state yet. Every later command takes its
    #: id from the fold of this one's event.
    corpus_id: UUID
    source_id: str
    text: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class DropSourceDocument:
    source_id: str
    reason: str


@dataclass(frozen=True)
class StoreSourceMedia:
    #: Carried for the same reason `StoreSourceDocument` carries it: storing is
    #: what brings a corpus into existence, so there is no state to read it off.
    corpus_id: UUID
    source_id: str
    sha256: str
    media_type: str
    byte_count: int
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None


@dataclass(frozen=True)
class StoreDerivedText:
    """Store what perception made of a medium.

    Carries `corpus_id` for `StoreSourceMedia`'s reason -- though unlike that
    one this can never be the creation command, since it requires a media
    source to already exist. Carried anyway so the three store commands have
    one shape; a command that omitted it would invite the question of why.

    **`source_id` is unconstrained here on purpose, and that is a decision
    rather than an omission.** The application spells a derived id
    `f"{parent}#perceived"`, and `decide` does not check it: naming is the
    caller's to choose, the aggregate's rules are about what an id *holds*
    rather than how it is spelled, and a domain that knew the convention would
    have to be edited to allow a second perception of one medium by a second
    model -- which the `perceived_with` field exists to make possible. What the
    aggregate does enforce is the part a naming convention cannot: that the
    parent exists, that it is media, that derivedness never flips, and that a
    transcript never changes which medium it is of. The tests here exploit the
    freedom deliberately (`source_id="notes", derived_from="vid"`) to reach
    refusals a convention-abiding id could not.
    """

    corpus_id: UUID
    source_id: str
    derived_from: str
    text: str
    locator_map: str
    perceived_with: str
    degradations: str
    title: str | None = None
    #: Mirrors `CorpusDerivedTextStored.note`; see there for why a transcript
    #: has a note and no `uri`.
    note: str | None = None


CorpusCommand = StoreSourceDocument | StoreSourceMedia | StoreDerivedText | DropSourceDocument


class SourceRecordBase(BaseModel):
    """What every source has, whatever its bytes are.

    Split out rather than repeated so a field added to provenance is added
    once. The two subclasses differ by exactly the one measure the other
    cannot give: characters against bytes.
    """

    source_id: str
    sha256: str
    uri: str | None = None
    title: str | None = None
    published_at: str | None = None
    note: str | None = None
    fetched_at: str | None = None
    """When the source was retrieved, for by-reference content the corpus did
    not create -- provenance, not a corpus fact. Carried through so a revise
    or restore that re-stores this record's own fields cannot silently zero
    it; see `CorpusEditor._store` for why that caller has to read it back
    before writing."""
    dropped_reason: str | None = None
    """Set means excluded. The record stays, so the exclusion stays auditable."""


class TextRecord(SourceRecordBase):
    """A source the corpus holds as prose. Deliberately not its text.

    Was `DocumentRecord`, renamed when media arrived: `document` had quietly
    come to mean both "a source" and "a source made of words", and the union
    below needs those to be different words.
    """

    kind: Literal["text"] = "text"
    char_count: int
    derived_from: str | None = None
    """The media source this was perceived from, or None for a fetched document.

    Not a third arm of `SourceRecord`. A derived source *is* text for every
    purpose a reader has -- it chunks, it quotes, it extracts -- and the
    discriminator's job is to answer "can I read this as prose". The cost is
    that this is a nullable field the type checker cannot force anyone to
    consider, and it is paid down in exactly one place: `decide` refuses any
    store that would change a source's derivedness, so nothing can quietly
    become or stop being a transcript.

    It refuses a *re-pointing* too -- a re-perception has to name the same
    parent. That is a second refusal rather than a corollary of the first: a
    transcript moving from one video to another stays derived throughout, so
    the derivedness guards see nothing wrong, and the field would change under
    a reader who had already cited it. This docstring claimed only the
    derivedness half until a reviewer noticed the gap.
    """
    perceived_with: str | None = None
    """The capability fingerprint that produced it. None for a fetched document."""
    degradations: tuple[str, ...] = ()
    """What the perception could not do -- "no vision model configured; frames
    were not described". Empty for a fetched document and for a complete
    perception; a reader cannot tell those two apart from here, and does not
    need to, because `derived_from` already does."""


class MediaRecord(SourceRecordBase):
    """A source whose bytes live in the blob store under `sha256`.

    Carries no path or URL to those bytes. The digest *is* the address, and a
    second locator stored here would be a thing that could disagree with it --
    which is precisely the failure the digest exists to make impossible.
    """

    kind: Literal["media"] = "media"
    media_type: str
    """The mimetype, as the ingest path determined it. Not re-sniffed here:
    the domain has no bytes to sniff."""
    byte_count: int


SourceRecord = Annotated[TextRecord | MediaRecord, Field(discriminator="kind")]
"""One `source_id` namespace, two shapes.

Discriminated on a literal rather than left as a bare union so pydantic
round-trips it without guessing and so the type checker -- not a runtime
`AttributeError` in a template -- finds the readers that assumed `.text`.
"""


class CorpusState(BaseModel):
    """Everything derivable from the corpus's event stream."""

    corpus_id: UUID | None = None
    """None before the corpus exists. Set by the fold of its first event.

    Optional because `initial_state()` takes no arguments (eventsource 0.12):
    the value before any event is one value for the aggregate *type*, and an
    id is not part of it.
    """

    status: Literal["new", "created"] = "new"
    documents: dict[str, SourceRecord] = Field(default_factory=dict)
    by_digest: dict[str, str] = Field(default_factory=dict)
    """sha256 -> source_id, for live documents only.

    A dropped document releases its digest: otherwise re-ingesting the same
    bytes would look like a duplicate of something the corpus no longer holds.
    """


def initial_state() -> CorpusState:
    return CorpusState()


def decide(command: CorpusCommand, state: CorpusState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `project.decide` does.

    The digest is computed here rather than accepted from the caller -- for
    text. A supplied sha256 makes `by_digest` a claim instead of a fact, and a
    wrong one stays invisible until two unrelated documents collide in it.

    **For media the digest is supplied, and that is a deliberate weakening.**
    The bytes never reach the domain -- holding a video in memory to hand it
    to a pure function is not a thing to do -- so `CorpusMediaStored.sha256`
    is what the blob store computed while streaming, and `by_digest` is a
    claim for those entries rather than a fact. `application/blobs.py`
    carries the mitigation: `put` returns the digest and there is no
    parameter by which a caller could offer a different one, so a wrong
    digest requires a bug in the store rather than a mistake at a call site.
    """
    corpus_id = state.corpus_id
    match command, state:
        # Both derivedness guards come before the kind guards below, and the
        # order is presently inert rather than load-bearing -- measured, not
        # reasoned: moving this pair beneath the kind guards leaves all 30
        # tests in `tests/domain/test_corpus.py` green. The two kind guards
        # match `StoreSourceDocument`-onto-media and `StoreSourceMedia`-onto-
        # text, and neither pattern can intercept either case here: a derived
        # record's kind is "text", not "media", and no kind guard mentions
        # `StoreDerivedText` at all. The task brief claimed the ordering was
        # what keeps a derivedness clash from being reported as a kind clash;
        # that is not true of this code as it stands.
        #
        # Kept in this order anyway, because it is the order that stays correct
        # if a kind guard ever widens -- a guard added for
        # `StoreSourceMedia`-onto-derived, say, would match before the
        # derivedness refusal and answer with the less specific message. The
        # cost of the placement is zero and the failure it forecloses is silent.
        #
        # **The inertness holds against those two kind guards and no further.**
        # It is a two-arm window, not a licence to move this pair anywhere: put
        # the `StoreSourceDocument` guard below the bare `StoreSourceDocument(),
        # _` arm, or either `StoreDerivedText` guard below the bare
        # `StoreDerivedText(derived_from=parent), _` arm, and the refusal does
        # not merely change its message -- it disappears, because the bare arms
        # match unconditionally and return an event. That is how a transcript
        # gets overwritten with prose nobody perceived, silently. Those two arms
        # are the floor. Also measured, on 2026-08-15: relocating the first
        # guard below the bare `StoreSourceDocument(), _` arm turns
        # `test_a_derived_document_cannot_be_overwritten_by_a_plain_one` red.
        case StoreSourceDocument(source_id=source_id), _ if _is_derived(state, source_id):
            raise CommandRejectedError(
                f"source {source_id!r} is derived from "
                f"{_derived_from(state, source_id)!r}; storing a fetched document "
                "under it would overwrite a transcript with prose nobody perceived"
            )

        # Named rather than written inline as `_kind_of(...) is not None and
        # not _is_derived(...)`: `ruff format` breaks that guard across three
        # lines with the call head stranded on the `case`, and the predicate is
        # the kind of thing a reader wants a name for regardless.
        case StoreDerivedText(source_id=source_id), _ if _holds_something_not_derived(
            state, source_id
        ):
            raise CommandRejectedError(
                f"source {source_id!r} is not derived; storing perceived text "
                "under it would replace a source with a reading of another one"
            )

        # Re-perceiving is a revision of one reading of one medium. Changing
        # which medium is not a revision -- it is a different claim wearing the
        # old id, and the derivedness guards above cannot see it, because the
        # record is derived before and after. Left open, a citation resolved
        # yesterday against a talk resolves today against a different talk, with
        # nothing in the state to show it moved. That is the unfalsifiable
        # provenance this module exists to prevent, so it is refused rather than
        # merely recorded.
        case StoreDerivedText(source_id=source_id, derived_from=parent), _ if (
            _repoints_a_transcript(state, source_id, parent)
        ):
            raise CommandRejectedError(
                f"source {source_id!r} is derived from "
                f"{_derived_from(state, source_id)!r}, not {parent!r}; a re-perception "
                "revises one reading of one medium and cannot move it to another"
            )

        case StoreSourceDocument(source_id=source_id), _ if (
            _kind_of(state, source_id) == "media"
        ):
            raise CommandRejectedError(
                f"source {source_id!r} holds media; storing text under it would "
                "change what the id means rather than revise it"
            )

        case StoreSourceMedia(source_id=source_id), _ if _kind_of(state, source_id) == "text":
            raise CommandRejectedError(
                f"source {source_id!r} holds text; storing media under it would "
                "change what the id means rather than revise it"
            )

        case StoreSourceDocument(), _:
            return [
                CorpusDocumentStored(
                    # From the command, not the state: this is the creation
                    # command, so on a fresh corpus `state.corpus_id` is None.
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    text=command.text,
                    sha256=hashlib.sha256(command.text.encode("utf-8")).hexdigest(),
                    uri=command.uri,
                    title=command.title,
                    published_at=command.published_at,
                    note=command.note,
                    fetched_at=command.fetched_at,
                )
            ]

        case StoreSourceMedia(), _:
            return [
                CorpusMediaStored(
                    # From the command, not the state: see the identical
                    # comment on the `StoreSourceDocument` case above.
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    sha256=command.sha256,
                    media_type=command.media_type,
                    byte_count=command.byte_count,
                    uri=command.uri,
                    title=command.title,
                    published_at=command.published_at,
                    note=command.note,
                    fetched_at=command.fetched_at,
                )
            ]

        case StoreDerivedText(derived_from=parent), _:
            parent_record = state.documents.get(parent)
            if parent_record is None:
                raise CommandRejectedError(f"unknown source {parent!r}")
            if parent_record.kind != "media":
                raise CommandRejectedError(
                    f"source {parent!r} holds text; there is nothing in it to perceive"
                )
            # Reject at the boundary, tolerate at the fold. `evolve` degrades
            # rather than raising on a malformed payload (see its case below),
            # because an event already written is never rewritten and one that
            # makes replay raise halfway is a data-surgery job on an append-only
            # log. But degrading is lossy and silent, so the command path -- the
            # one place a bad value can still be refused instead of stored -- is
            # where the shape is actually enforced. Neither half substitutes for
            # the other.
            _reject_unless_json_list_of_strings("degradations", command.degradations)
            _reject_unless_json_list_of_objects("locator_map", command.locator_map)
            return [
                CorpusDerivedTextStored(
                    # From the command for the same reason the two stores above
                    # read it from theirs -- though this one can never be the
                    # creation command, since it needs a media source to exist.
                    aggregate_id=command.corpus_id,
                    source_id=command.source_id,
                    derived_from=command.derived_from,
                    text=command.text,
                    # Computed, not supplied: this *is* text and the domain has
                    # the bytes, so `by_digest` stays a fact here. Media's
                    # supplied digest is the exception, not the pattern.
                    sha256=hashlib.sha256(command.text.encode("utf-8")).hexdigest(),
                    locator_map=command.locator_map,
                    perceived_with=command.perceived_with,
                    degradations=command.degradations,
                    title=command.title,
                    note=command.note,
                )
            ]

        # Storing is the only thing an empty corpus can do, since storing is
        # what brings it into existence.
        case _, CorpusState(status="new"):
            raise CommandRejectedError("corpus is empty")

        case DropSourceDocument(source_id=source_id, reason=reason), _:
            if not reason.strip():
                raise CommandRejectedError("a drop requires a reason")
            record = state.documents.get(source_id)
            if record is None:
                # Named, not just refused: the next thing anyone asks is which
                # id the corpus actually holds.
                raise CommandRejectedError(f"unknown source {source_id!r}")
            if record.dropped_reason is not None:
                raise CommandRejectedError(
                    f"source {source_id!r} already dropped: {record.dropped_reason}"
                )
            return [
                CorpusDocumentDropped(
                    aggregate_id=corpus_id, source_id=source_id, reason=reason
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def _kind_of(state: CorpusState, source_id: str) -> str | None:
    """Which shape a source id already holds, or None if it is free.

    A dropped record still counts. Its id is taken -- restore reads it back --
    and letting a drop free the id for the other kind would make restore
    resurrect a record whose kind no longer matches its row.
    """
    record = state.documents.get(source_id)
    return None if record is None else record.kind


def _is_derived(state: CorpusState, source_id: str) -> bool:
    """Whether a source id already holds perceived text rather than fetched.

    `getattr` rather than an isinstance narrow because `MediaRecord` has no
    such field and never will: media is the thing perceived, not the result.
    A free id is not derived, which is what makes the `StoreDerivedText` guard
    above fall through to the main case for a first perception.
    """
    record = state.documents.get(source_id)
    return record is not None and getattr(record, "derived_from", None) is not None


def _holds_something_not_derived(state: CorpusState, source_id: str) -> bool:
    """Whether the id is already taken by something that is not perceived text.

    A *free* id is not "not derived" for this purpose -- it is the ordinary
    first perception, and answering True here would refuse every transcript
    that has ever been stored. The two conditions are one predicate because
    getting either half alone wrong produces that failure.
    """
    return _kind_of(state, source_id) is not None and not _is_derived(state, source_id)


def _derived_from(state: CorpusState, source_id: str) -> str | None:
    """Which medium a source was perceived from, for naming it in a refusal."""
    record = state.documents.get(source_id)
    return getattr(record, "derived_from", None)


def _repoints_a_transcript(state: CorpusState, source_id: str, parent: str) -> bool:
    """Whether this store would move an existing transcript to a different medium.

    False for a free id -- that is a first perception, not a move. False for a
    re-perception naming the same parent, which is the ordinary case this
    aggregate supports.
    """
    return _is_derived(state, source_id) and _derived_from(state, source_id) != parent


def _reject_unless_json_list_of_strings(field: str, value: str) -> None:
    """Refuse a JSON-encoded degradations list that is not one.

    The check is `isinstance`-per-element rather than a bare `json.loads`
    because well-formed JSON of the wrong shape is the dangerous case, not
    malformed JSON. `'"no vision model"'` parses fine and `tuple()`s into
    fifteen single characters; `'{"a": 1}'` parses fine and `tuple()`s into the
    key. Both would reach a reader as a plausible-looking degradation list that
    the producer never wrote, and neither is caught by `tuple[str, ...]` on the
    record -- pydantic coerces `[1, 2]` to `("1", "2")` rather than complaining.
    """
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as error:
        raise CommandRejectedError(
            f"{field} must be a JSON list of strings; got {value!r}"
        ) from error
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise CommandRejectedError(f"{field} must be a JSON list of strings; got {value!r}")


def _reject_unless_json_list_of_objects(field: str, value: str) -> None:
    """Refuse a locator map that the resolver could not walk.

    A *list of objects*, not a list of strings: a locator map is a sequence of
    span records (`application/locators.py`'s `resolve` indexes it and reads
    `["locator"]` off an element), so the two JSON fields on this command have
    genuinely different shapes and one shared validator would be wrong for one
    of them.

    The element keys are deliberately not checked. The locator union belongs to
    `readeverything` and will grow arms there; checking keys here would make
    every locator kind it adds a refusal in this repository, which is the exact
    coupling `locator_map` is a JSON string to avoid. "A list whose elements are
    objects" is the whole invariant the resolver depends on, so it is the whole
    invariant enforced.
    """
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError) as error:
        raise CommandRejectedError(
            f"{field} must be a JSON list of objects; got {value!r}"
        ) from error
    if not isinstance(parsed, list) or not all(isinstance(item, dict) for item in parsed):
        raise CommandRejectedError(f"{field} must be a JSON list of objects; got {value!r}")


def _degradations_from(event: CorpusDerivedTextStored) -> tuple[str, ...]:
    """Read an event's degradations, never raising, whatever the payload says.

    `evolve` is documented total, and totality that holds for unknown events but
    not for known-but-malformed ones is not the property the docstring claims.
    `decide` refuses these payloads, so nothing this build writes reaches here
    broken -- but events already written are never rewritten, so a payload from
    an earlier build, a repair script, or a direct append is beyond the command
    path's reach, and one of them raising mid-fold would leave the whole stream
    unreplayable. A rejected command is recoverable; a poisoned log is not.

    The degraded value is a marker rather than `()`. An empty tuple already
    means something here -- `TextRecord.degradations` says a complete perception
    is empty -- so degrading to `()` would turn "this field could not be read"
    into a positive claim that perception went fine, which is the one reading
    guaranteed to be wrong. The marker says a value was there and could not be
    read, which is all that is honestly known at this point.
    """
    try:
        parsed = json.loads(event.degradations)
    except (ValueError, TypeError):
        return UNREADABLE_DEGRADATIONS
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return UNREADABLE_DEGRADATIONS
    return tuple(parsed)


def evolve(state: CorpusState, event: DomainEvent) -> CorpusState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.

    Total for *known but malformed* events too, which is a narrower promise
    than it sounds and used not to hold. `CorpusDerivedTextStored` carries two
    JSON strings, and the one this fold parses went through
    `tuple(json.loads(...))` until a reviewer pointed out that it both raises
    on bad JSON and silently invents a tuple from good JSON of the wrong shape.
    `decide` now refuses those payloads and `_degradations_from` degrades
    instead of raising -- rejection at the boundary, tolerance at the fold,
    because a rejected command costs a caller a retry and a poisoned log costs
    an append-only stream its replay.
    """
    match event:
        case CorpusDocumentStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                # Supersession: the old bytes are no longer what this id holds.
                del by_digest[previous.sha256]
            # First claimant of a digest keeps it, so the map answers "which
            # document already carries these bytes" with a stable id.
            by_digest.setdefault(event.sha256, event.source_id)
            record = TextRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                char_count=len(event.text),
                uri=event.uri,
                title=event.title,
                published_at=event.published_at,
                note=event.note,
                fetched_at=event.fetched_at,
            )
            return state.model_copy(
                update={
                    # The event is where the id enters the state: `decide` reads
                    # it back off `state` for every command but the first.
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )

        case CorpusMediaStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                del by_digest[previous.sha256]
            by_digest.setdefault(event.sha256, event.source_id)
            record = MediaRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                media_type=event.media_type,
                byte_count=event.byte_count,
                uri=event.uri,
                title=event.title,
                published_at=event.published_at,
                note=event.note,
                fetched_at=event.fetched_at,
            )
            return state.model_copy(
                update={
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )

        case CorpusDerivedTextStored():
            previous = state.documents.get(event.source_id)
            by_digest = dict(state.by_digest)
            if previous is not None and by_digest.get(previous.sha256) == event.source_id:
                # Identical supersession to `CorpusDocumentStored`: re-perceiving
                # a video under the same derived id has to release the previous
                # transcript's digest exactly as a re-fetch does, or the old
                # bytes go on claiming an id that no longer holds them.
                del by_digest[previous.sha256]
            by_digest.setdefault(event.sha256, event.source_id)
            record = TextRecord(
                source_id=event.source_id,
                sha256=event.sha256,
                char_count=len(event.text),
                title=event.title,
                note=event.note,
                derived_from=event.derived_from,
                perceived_with=event.perceived_with,
                # JSON on the event, tuple in the state: the list shape is
                # what the producer speaks and the immutable one is what a
                # pydantic state can hold without a shared mutable default.
                # Read through a helper rather than `tuple(json.loads(...))`
                # because that expression has two failure modes inside a fold
                # promised total -- it raises on malformed JSON, and it quietly
                # fabricates a plausible tuple from well-formed JSON of the
                # wrong shape. See `_degradations_from`.
                degradations=_degradations_from(event),
            )
            return state.model_copy(
                update={
                    "corpus_id": event.aggregate_id,
                    "status": "created",
                    "documents": {**state.documents, event.source_id: record},
                    "by_digest": by_digest,
                }
            )

        case CorpusDocumentDropped():
            record = state.documents.get(event.source_id)
            if record is None:
                return state
            by_digest = {
                digest: source_id
                for digest, source_id in state.by_digest.items()
                if source_id != event.source_id
            }
            return state.model_copy(
                update={
                    "documents": {
                        **state.documents,
                        event.source_id: record.model_copy(
                            update={"dropped_reason": event.reason}
                        ),
                    },
                    "by_digest": by_digest,
                }
            )

        case _:
            return state


class Corpus(DeciderAggregate[CorpusState, CorpusCommand]):
    """The imperative shell. Holds no rules -- it delegates all three.

    Mirrors `Project`'s shape exactly: the class attributes bind directly to
    the module-level functions rather than wrapping them in new method bodies,
    so there is exactly one implementation of each rule to keep in sync.
    """

    aggregate_type = "Corpus"

    initial_state = staticmethod(initial_state)
    decide = staticmethod(decide)
    evolve = staticmethod(evolve)

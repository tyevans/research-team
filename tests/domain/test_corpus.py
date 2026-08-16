import hashlib
from uuid import UUID, uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.domain.corpus import (
    UNREADABLE_DEGRADATIONS,
    CorpusDerivedTextStored,
    CorpusDocumentDropped,
    CorpusDocumentStored,
    CorpusMediaStored,
    CorpusState,
    DropSourceDocument,
    MediaRecord,
    StoreDerivedText,
    StoreSourceDocument,
    StoreSourceMedia,
    TextRecord,
    decide,
    evolve,
    initial_state,
)

CORPUS_ID = uuid4()
"""One id for the derived-text tests, where the existing tests each mint their own.

Those tests predate any helper that builds multi-source state; these build a
medium and then perceive it, and threading a freshly minted id through four
helpers per test would be noise around the thing under test. The id's value is
never asserted on here -- `test_media_creates_a_corpus_the_way_a_document_does`
is what pins that the event's id reaches the state."""


def _stored(corpus_id, source_id="s1", text="hello", **kwargs):
    [event] = decide(
        StoreSourceDocument(corpus_id=corpus_id, source_id=source_id, text=text, **kwargs),
        initial_state(),
    )
    return event


def _with(corpus_id, *events):
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


def test_storing_a_document_records_it():
    corpus_id = uuid4()

    [event] = decide(
        StoreSourceDocument(
            corpus_id=corpus_id, source_id="s1", text="hello", uri="https://x/1", title="One"
        ),
        initial_state(),
    )

    assert isinstance(event, CorpusDocumentStored)
    assert event.aggregate_id == corpus_id
    assert event.text == "hello"
    assert event.uri == "https://x/1"


def test_the_digest_is_derived_from_the_bytes_not_supplied():
    """The index only answers "are these the same bytes" if nothing can lie to it.

    A caller-supplied sha256 makes the map a claim rather than a fact, and a
    wrong one is invisible until two different documents collide in it.
    """
    corpus_id = uuid4()
    event = _stored(corpus_id, text="hello")

    assert event.sha256 == hashlib.sha256(b"hello").hexdigest()


def test_state_carries_metadata_but_never_text():
    """The snapshot-size invariant, pinned rather than intended.

    `SessionSummaryRunner` snapshots every 50 events; a text field here would
    put every document of every corpus into every snapshot. An invariant this
    cheap to violate has to fail a test the moment someone does.
    """
    assert "text" not in TextRecord.model_fields

    corpus_id = uuid4()
    state = _with(corpus_id, _stored(corpus_id, text="a longer body"))

    record = state.documents["s1"]
    assert isinstance(record, TextRecord)
    assert record.char_count == len("a longer body")
    dumped = state.documents["s1"].model_dump()
    assert not any("a longer body" in str(value) for value in dumped.values())


def test_the_first_stored_document_creates_the_corpus():
    corpus_id = uuid4()

    state = _with(corpus_id, _stored(corpus_id))

    assert state.status == "created"


def test_an_empty_corpus_rejects_everything_but_a_store():
    """There is no creation command, so "empty" has to answer for itself.

    Dropping from a corpus that has never held anything is a caller bug worth
    naming, not a no-op.
    """
    state = initial_state()

    with pytest.raises(CommandRejectedError, match="empty"):
        decide(DropSourceDocument(source_id="s1", reason="duplicate"), state)


def test_identical_bytes_under_a_new_source_id_are_detectable():
    corpus_id = uuid4()
    state = _with(corpus_id, _stored(corpus_id, source_id="s1", text="same"))

    state = evolve(state, _stored(corpus_id, source_id="s2", text="same"))

    digest = state.documents["s1"].sha256
    assert state.by_digest[digest] == "s1"
    assert state.documents["s2"].sha256 == digest


def test_restoring_the_same_source_id_with_new_bytes_supersedes():
    """Sources are revised in place; a re-fetch is not a new document.

    The old text stays in the log, so the earlier version is still readable;
    only the index moves forward, which is what "current" has to mean.
    """
    corpus_id = uuid4()
    state = _with(corpus_id, _stored(corpus_id, source_id="s1", text="v1"))
    old_digest = state.documents["s1"].sha256

    state = evolve(state, _stored(corpus_id, source_id="s1", text="v2 is longer"))

    record = state.documents["s1"]
    assert isinstance(record, TextRecord)
    assert record.char_count == len("v2 is longer")
    assert state.documents["s1"].sha256 != old_digest
    assert old_digest not in state.by_digest
    assert state.by_digest[state.documents["s1"].sha256] == "s1"


def test_storing_over_a_dropped_source_id_brings_it_back():
    """Storing asserts presence, so it has to clear the reason it was absent.

    Leaving `dropped_reason` set would leave a live document explaining why it
    is not there.

    Load-bearing for `CorpusEditor.restore` (`research_team/application/
    corpus_editing.py`), which is built entirely on this property: a restore
    is a re-store of a dropped document's own unchanged bytes, and this test
    is what would go red if `evolve` ever started carrying `dropped_reason`
    forward and silently removed the feature.
    """
    corpus_id = uuid4()
    state = _with(
        corpus_id,
        _stored(corpus_id, source_id="s1", text="v1"),
        CorpusDocumentDropped(aggregate_id=corpus_id, source_id="s1", reason="wrong paper"),
    )

    state = evolve(state, _stored(corpus_id, source_id="s1", text="v2"))

    assert state.documents["s1"].dropped_reason is None


def test_dropping_records_the_reason():
    corpus_id = uuid4()
    state = _with(corpus_id, _stored(corpus_id, source_id="s1"))

    [event] = decide(DropSourceDocument(source_id="s1", reason="paywalled stub"), state)

    assert isinstance(event, CorpusDocumentDropped)
    assert event.reason == "paywalled stub"
    assert evolve(state, event).documents["s1"].dropped_reason == "paywalled stub"


def test_a_drop_without_a_reason_is_rejected():
    """The silent drop is the failure mode every intake report named worst.

    A document that vanishes with no reason is indistinguishable from one that
    was never fetched, and nobody can tell which by reading the log.
    """
    corpus_id = uuid4()
    state = _with(corpus_id, _stored(corpus_id, source_id="s1"))

    for reason in ("", "   "):
        with pytest.raises(CommandRejectedError, match="reason"):
            decide(DropSourceDocument(source_id="s1", reason=reason), state)


def test_dropping_an_unknown_source_id_is_rejected():
    corpus_id = uuid4()
    state = _with(corpus_id, _stored(corpus_id, source_id="s1"))

    with pytest.raises(CommandRejectedError, match="unknown source"):
        decide(DropSourceDocument(source_id="nope", reason="typo"), state)


def test_dropping_twice_is_rejected():
    corpus_id = uuid4()
    state = _with(
        corpus_id,
        _stored(corpus_id, source_id="s1"),
        CorpusDocumentDropped(aggregate_id=corpus_id, source_id="s1", reason="first"),
    )

    with pytest.raises(CommandRejectedError, match="already dropped"):
        decide(DropSourceDocument(source_id="s1", reason="second"), state)


def test_a_dropped_document_no_longer_claims_its_digest():
    """Otherwise re-ingesting the same bytes would be refused by a ghost."""
    corpus_id = uuid4()
    stored = _stored(corpus_id, source_id="s1", text="body")
    state = _with(
        corpus_id,
        stored,
        CorpusDocumentDropped(aggregate_id=corpus_id, source_id="s1", reason="superseded"),
    )

    assert stored.sha256 not in state.by_digest


def test_evolve_ignores_unknown_events():
    """A stream may carry events this build has never heard of.

    Replay has to survive that rather than fail halfway through a fold.
    """
    corpus_id = uuid4()
    state = _with(corpus_id, _stored(corpus_id, source_id="s1"))

    unknown = DomainEvent(aggregate_id=corpus_id, aggregate_type="Corpus")

    assert evolve(state, unknown) == state


def test_storing_media_records_the_digest_it_was_given() -> None:
    """The one place the corpus takes a digest on trust rather than computing it.

    Asserted explicitly because it is a documented weakening of the guarantee
    in this module's docstring: the bytes never reach the domain, so `decide`
    cannot hash them. If a future change makes `decide` compute a digest for
    media, this test is the one that should fail and force the docstring to be
    reconciled with it.
    """
    corpus_id = uuid4()
    events = decide(
        StoreSourceMedia(
            corpus_id=corpus_id,
            source_id="v1",
            sha256="a" * 64,
            media_type="video/mp4",
            byte_count=1234,
            uri="https://example.test/talk.mp4",
        ),
        initial_state(),
    )
    assert len(events) == 1
    stored = events[0]
    assert isinstance(stored, CorpusMediaStored)
    assert stored.sha256 == "a" * 64
    assert stored.byte_count == 1234
    assert stored.media_type == "video/mp4"


def test_media_creates_a_corpus_the_way_a_document_does() -> None:
    """Storing is what brings a corpus into existence, whichever kind is stored.

    Fails if `StoreSourceMedia` falls through to the `status="new"` rejection
    that guards every non-storing command.
    """
    corpus_id = uuid4()
    state = evolve(
        initial_state(),
        decide(_store_media(corpus_id, "v1"), initial_state())[0],
    )
    assert state.status == "created"
    assert state.corpus_id == corpus_id
    record = state.documents["v1"]
    assert isinstance(record, MediaRecord)
    assert record.kind == "media"
    assert record.byte_count == 1234


def test_media_may_not_take_over_a_source_id_holding_text() -> None:
    """A URI that returned prose yesterday and a video today is not a revision.

    Supersession by `source_id` exists for re-fetches of one document. Letting
    a kind change ride on it would make `read_document` start answering `None`
    for a source that still exists, which is the silent half of this failure.
    The refusal names both kinds because the next question is which one is
    there now.
    """
    corpus_id = uuid4()
    state = evolve(
        initial_state(),
        decide(
            StoreSourceDocument(corpus_id=corpus_id, source_id="s1", text="prose"),
            initial_state(),
        )[0],
    )
    with pytest.raises(CommandRejectedError, match="text"):
        decide(_store_media(corpus_id, "s1"), state)


def test_text_may_not_take_over_a_source_id_holding_media() -> None:
    """The same refusal in the other direction.

    Written separately rather than parametrised: the two paths are two
    branches, and a single test passing proves only one of them.
    """
    corpus_id = uuid4()
    state = evolve(initial_state(), decide(_store_media(corpus_id, "v1"), initial_state())[0])
    with pytest.raises(CommandRejectedError, match="media"):
        decide(StoreSourceDocument(corpus_id=corpus_id, source_id="v1", text="prose"), state)


def test_media_is_dropped_by_the_same_command_text_is() -> None:
    """One drop command for one `source_id` namespace.

    A second drop command for media would be a second way to say one thing, and
    the citation path addresses an id without knowing its kind.
    """
    corpus_id = uuid4()
    state = evolve(initial_state(), decide(_store_media(corpus_id, "v1"), initial_state())[0])
    dropped = decide(DropSourceDocument(source_id="v1", reason="wrong talk"), state)
    state = evolve(state, dropped[0])
    assert state.documents["v1"].dropped_reason == "wrong talk"
    assert state.by_digest == {}


def _store_media(corpus_id: UUID, source_id: str) -> StoreSourceMedia:
    return StoreSourceMedia(
        corpus_id=corpus_id,
        source_id=source_id,
        sha256="a" * 64,
        media_type="video/mp4",
        byte_count=1234,
    )


def _store_derived(
    source_id: str,
    derived_from: str,
    text: str = "said something",
    degradations: str = "[]",
    locator_map: str = "[]",
) -> StoreDerivedText:
    return StoreDerivedText(
        corpus_id=CORPUS_ID,
        source_id=source_id,
        derived_from=derived_from,
        text=text,
        locator_map=locator_map,
        perceived_with="abc123",
        degradations=degradations,
    )


def _with_media(state: CorpusState, source_id: str, sha256: str = "a" * 64) -> CorpusState:
    """Fold a medium into an existing state.

    Goes through `decide` rather than constructing the event, so a state built
    here is one the aggregate could actually have reached. `sha256` is a
    parameter because two media under one digest would collide in `by_digest`
    and quietly make a supersession assertion mean something else.
    """
    command = StoreSourceMedia(
        corpus_id=CORPUS_ID,
        source_id=source_id,
        sha256=sha256,
        media_type="video/mp4",
        byte_count=1234,
    )
    return evolve(state, decide(command, state)[0])


def _state_with_media(source_id: str) -> CorpusState:
    return _with_media(initial_state(), source_id)


def _state_with_text(source_id: str, text: str = "prose") -> CorpusState:
    state = initial_state()
    command = StoreSourceDocument(corpus_id=CORPUS_ID, source_id=source_id, text=text)
    return evolve(state, decide(command, state)[0])


def _evolve_derived(
    state: CorpusState, source_id: str, derived_from: str, text: str = "first"
) -> CorpusState:
    return evolve(state, decide(_store_derived(source_id, derived_from, text=text), state)[0])


def test_derived_text_must_name_a_source_that_exists() -> None:
    """A derived source pointing at nothing is provenance that cannot be checked.

    Red before the change with an ImportError on `StoreDerivedText`; red after
    the command existed but before the `derived_from` lookup, because the
    aggregate would have happily emitted an event naming a source it did not
    hold.
    """
    state = _state_with_media("vid")
    with pytest.raises(CommandRejectedError, match="unknown source 'nope'"):
        decide(_store_derived(source_id="nope#perceived", derived_from="nope"), state)


def test_derived_text_must_name_media_not_text() -> None:
    """A transcript of a text document is a category error, and the aggregate
    is the only place that can see it -- the state holds every source's kind."""
    state = _state_with_text("paper")
    with pytest.raises(CommandRejectedError, match="holds text"):
        decide(_store_derived(source_id="paper#perceived", derived_from="paper"), state)


def test_a_plain_document_cannot_be_overwritten_by_a_derived_one() -> None:
    """Supersession by source_id means "a re-fetch is a revision". A transcript
    landing on a document's id is not a revision, for the same reason a video
    landing on one is not."""
    state = _state_with_text("notes")  # a plain document at that exact id
    state = _with_media(state, "vid")
    with pytest.raises(CommandRejectedError, match="not derived"):
        decide(_store_derived(source_id="notes", derived_from="vid"), state)


def test_a_derived_document_cannot_be_overwritten_by_a_plain_one() -> None:
    """The refusal in the other direction, written separately because it is a
    separate branch and one passing proves nothing about the other."""
    state = _state_with_media("vid")
    state = _evolve_derived(state, source_id="vid#perceived", derived_from="vid")
    with pytest.raises(CommandRejectedError, match="derived"):
        decide(
            StoreSourceDocument(
                corpus_id=CORPUS_ID, source_id="vid#perceived", text="hand written"
            ),
            state,
        )


def test_the_refusal_names_derivedness_not_kind() -> None:
    """Perceiving a medium onto its own id is refused for derivedness, not kind.

    The brief asked for this to be proved by moving the two derivedness guards
    below the existing kind guards and watching it go red. **It does not go
    red** -- measured on 2026-08-15, all 30 tests stay green with the pair
    relocated -- because no kind guard's pattern can match either new case; see
    the comment above them in `decide`. So this test does not pin the ordering.

    What it does pin is the message: a caller who aims a transcript at the very
    medium it came from is told the id is not derived, which is the actionable
    half, rather than told the id holds media, which they already knew. It goes
    red if the `StoreDerivedText` guard's condition is narrowed to text-only
    records, which is the plausible way this refusal gets lost.
    """
    state = _state_with_media("vid")
    with pytest.raises(CommandRejectedError, match="is not derived") as raised:
        decide(_store_derived(source_id="vid", derived_from="vid"), state)
    assert "holds media" not in str(raised.value)


def test_re_perceiving_supersedes_rather_than_accumulating() -> None:
    """Re-perceiving under one derived id is a revision, exactly as a re-fetch is.

    The `by_digest` half is the part that would fail silently: without the
    supersession branch the first transcript's digest keeps claiming this id
    forever, and a later ingest of those same bytes is deduplicated against a
    transcript the corpus no longer holds.
    """
    state = _state_with_media("vid")
    state = _evolve_derived(state, source_id="vid#perceived", derived_from="vid", text="first")
    first_digest = state.documents["vid#perceived"].sha256

    events = decide(
        _store_derived(source_id="vid#perceived", derived_from="vid", text="second"), state
    )
    state = evolve(state, events[0])

    record = state.documents["vid#perceived"]
    assert isinstance(record, TextRecord)
    assert record.char_count == len("second")
    assert record.derived_from == "vid"
    assert len(state.documents) == 2  # the media and its one transcript
    assert first_digest not in state.by_digest
    assert state.by_digest[record.sha256] == "vid#perceived"


def test_the_digest_of_derived_text_is_computed_not_supplied() -> None:
    """It is text and the aggregate has the bytes, so `by_digest` stays a fact.
    Media supplies its digest only because the domain never sees a video."""
    state = _state_with_media("vid")
    events = decide(
        _store_derived(source_id="vid#perceived", derived_from="vid", text="hello"), state
    )
    assert isinstance(events[0], CorpusDerivedTextStored)
    assert events[0].sha256 == hashlib.sha256(b"hello").hexdigest()


def test_a_stored_transcript_carries_its_perception_provenance() -> None:
    """`evolve` has to land the three new fields, not merely accept the event.

    An event no projection -- or no `evolve` case -- handles is APPLIED, not
    rejected, so an assertion that the fold "succeeded" would pass with the
    whole case deleted. These are assertions about the data.
    """
    state = _state_with_media("vid")
    state = _evolve_derived(state, source_id="vid#perceived", derived_from="vid")
    record = state.documents["vid#perceived"]
    assert isinstance(record, TextRecord)
    assert record.kind == "text"  # derived text is prose for every reader
    assert record.derived_from == "vid"
    assert record.perceived_with == "abc123"
    assert record.degradations == ()


def test_degradations_survive_the_fold_as_a_tuple() -> None:
    """The JSON-to-tuple conversion, pinned. Empty is the uninteresting case."""
    state = _state_with_media("vid")
    state = evolve(
        state,
        decide(
            _store_derived(
                source_id="vid#perceived",
                derived_from="vid",
                degradations='["no vision model configured; frames were not described"]',
            ),
            state,
        )[0],
    )
    record = state.documents["vid#perceived"]
    assert isinstance(record, TextRecord)
    assert record.degradations == ("no vision model configured; frames were not described",)


def test_a_fetched_document_is_not_derived() -> None:
    """The default that keeps every existing document out of the new refusals.

    Would pass with `decide` reverted; it is about `TextRecord`'s defaults, and
    it is what stops `_is_derived` reporting True for the whole existing corpus.
    """
    state = _state_with_text("paper")
    record = state.documents["paper"]
    assert isinstance(record, TextRecord)
    assert record.derived_from is None
    assert record.perceived_with is None
    assert record.degradations == ()


def test_a_transcript_can_be_dropped_like_any_other_source() -> None:
    """One `source_id` namespace, one drop command -- derivedness does not fork it."""
    state = _state_with_media("vid")
    state = _evolve_derived(state, source_id="vid#perceived", derived_from="vid")
    drop = DropSourceDocument(source_id="vid#perceived", reason="bad audio")
    state = evolve(state, decide(drop, state)[0])
    assert state.documents["vid#perceived"].dropped_reason == "bad audio"


def test_a_transcript_cannot_be_repointed_at_a_different_medium() -> None:
    """A re-perception revises one reading of one medium; it does not move it.

    The derivedness guards cannot catch this -- the record is derived before
    and after -- so it is a third refusal rather than a corollary. Left open, a
    citation resolved yesterday against one talk resolves today against
    another, with nothing in the state recording that it moved.
    """
    state = _state_with_media("vid")
    state = _with_media(state, "other_vid", sha256="b" * 64)
    state = _evolve_derived(state, source_id="vid#perceived", derived_from="vid")

    with pytest.raises(CommandRejectedError, match="not 'other_vid'"):
        decide(_store_derived(source_id="vid#perceived", derived_from="other_vid"), state)


def test_re_perceiving_the_same_medium_is_still_allowed() -> None:
    """The other side of the re-pointing refusal, and the reason it is narrow.

    Goes red if the guard is written as "an already-derived id may not be
    stored again", which refuses every second pass of the perception runner --
    the ordinary case, and the one `test_re_perceiving_supersedes...` depends
    on.
    """
    state = _state_with_media("vid")
    state = _evolve_derived(state, source_id="vid#perceived", derived_from="vid")

    events = decide(_store_derived(source_id="vid#perceived", derived_from="vid"), state)

    assert len(events) == 1


@pytest.mark.parametrize(
    "degradations",
    [
        pytest.param("not json at all", id="malformed"),
        pytest.param('"a single string"', id="json-string-tuples-into-characters"),
        pytest.param('{"a": 1}', id="json-object-tuples-into-keys"),
        pytest.param("5", id="json-number-raises-in-tuple"),
        pytest.param("[1, 2]", id="json-list-of-non-strings"),
        pytest.param("null", id="json-null"),
    ],
)
def test_degradations_that_is_not_a_json_list_of_strings_is_refused(degradations: str) -> None:
    """Reject at the boundary. Every case here is one `tuple(json.loads(...))` took.

    The two middle cases are the reason a `try`/`except` in `evolve` would not
    have been enough on its own: they are *well-formed* JSON, they raise
    nothing, and they produce a plausible-looking degradation list the producer
    never wrote -- a tuple of fifteen single characters, or a tuple of dict
    keys. `[1, 2]` is not caught by `tuple[str, ...]` on the record either;
    pydantic coerces it to `("1", "2")`.
    """
    state = _state_with_media("vid")
    command = _store_derived(
        source_id="vid#perceived", derived_from="vid", degradations=degradations
    )
    with pytest.raises(CommandRejectedError, match="must be a JSON list of strings") as raised:
        decide(command, state)
    # Asserted separately for the line-length reason given on the locator_map
    # test below; the refusal has to name the field or a caller cannot tell
    # which of the command's two JSON payloads it got wrong.
    assert "degradations" in str(raised.value)


@pytest.mark.parametrize(
    "locator_map",
    [
        pytest.param("not json at all", id="malformed"),
        pytest.param('{"spans": []}', id="json-object-not-a-list"),
        pytest.param('["a span"]', id="json-list-of-strings"),
    ],
)
def test_a_locator_map_the_resolver_could_not_walk_is_refused(locator_map: str) -> None:
    """The same boundary check, different shape -- and the shape difference matters.

    A locator map is a list of *span objects*, not of strings:
    `application/locators.py`'s `resolve` indexes the list and reads
    `["locator"]` off an element. Sharing one validator with `degradations`
    would have accepted `["a span"]` here and rejected every real map there.

    Element keys are deliberately unchecked; see
    `_reject_unless_json_list_of_objects`. `'[]'` and a list of objects both
    pass, which the other derived-text tests exercise on every call.
    """
    state = _state_with_media("vid")
    command = _store_derived(
        source_id="vid#perceived", derived_from="vid", locator_map=locator_map
    )
    with pytest.raises(CommandRejectedError, match="must be a JSON list of objects") as raised:
        decide(command, state)
    # The field name is asserted separately only because the one-line `match=`
    # carrying both runs past the line limit.
    assert "locator_map" in str(raised.value)


def test_a_real_locator_map_is_accepted() -> None:
    """The validator has to pass the shape Task 3 actually produces.

    Taken from the plan's own example rather than invented here, so this test
    fails if the check is tightened to something the producer does not emit.
    """
    state = _state_with_media("vid")
    locator_map = (
        '[{"char_start": 0, "char_end": 26, '
        '"locator": {"kind": "time_span", "start_s": 1.0, "end_s": 4.5}}]'
    )
    events = decide(
        _store_derived(source_id="vid#perceived", derived_from="vid", locator_map=locator_map),
        state,
    )
    assert isinstance(events[0], CorpusDerivedTextStored)
    assert events[0].locator_map == locator_map


@pytest.mark.parametrize(
    "degradations",
    ["not json at all", '"a single string"', '{"a": 1}', "5", "[1, 2]", "null"],
)
def test_evolve_never_raises_on_unreadable_degradations(degradations: str) -> None:
    """Tolerate at the fold. `decide` refuses these; a written event cannot be.

    Events already in a log are never rewritten, so a payload from an earlier
    build, a repair script or a direct append is beyond `decide`'s reach --
    and one of them raising here would leave the whole stream unreplayable,
    which is data surgery on an append-only log rather than a caller's retry.

    Constructed as an event directly, deliberately: routing through `decide`
    is exactly the path that now cannot produce these, so a test that went
    through it would be testing nothing.
    """
    state = _state_with_media("vid")
    event = CorpusDerivedTextStored(
        aggregate_id=CORPUS_ID,
        source_id="vid#perceived",
        derived_from="vid",
        text="hello",
        sha256=hashlib.sha256(b"hello").hexdigest(),
        locator_map="[]",
        perceived_with="abc123",
        degradations=degradations,
    )

    state = evolve(state, event)

    record = state.documents["vid#perceived"]
    assert isinstance(record, TextRecord)
    # The rest of the event still lands: an unreadable field degrades one
    # field, not the whole record.
    assert record.derived_from == "vid"
    assert record.char_count == len("hello")
    assert record.degradations == UNREADABLE_DEGRADATIONS


def test_an_unreadable_degradations_does_not_read_as_a_clean_perception() -> None:
    """Why the degraded value is a marker and not `()`.

    `TextRecord.degradations` documents empty as meaning perception was
    complete. Degrading an unreadable field to `()` would convert "this could
    not be read" into a positive claim that nothing went wrong -- the one
    reading guaranteed to be false. This test is what goes red if someone
    simplifies the marker away for shape tidiness.
    """
    state = _state_with_media("vid")
    event = CorpusDerivedTextStored(
        aggregate_id=CORPUS_ID,
        source_id="vid#perceived",
        derived_from="vid",
        text="hello",
        sha256=hashlib.sha256(b"hello").hexdigest(),
        locator_map="[]",
        perceived_with="abc123",
        degradations="{}",
    )

    record = evolve(state, event).documents["vid#perceived"]
    assert isinstance(record, TextRecord)
    assert record.degradations != ()
    assert len(record.degradations) == 1


def test_the_new_event_and_command_are_exported_from_the_domain_package() -> None:
    """Every sibling corpus event and store command is; these were not.

    Left unexported, Task 3 either adds them or imports from the submodule
    while importing its neighbours from the package.
    """
    import research_team.domain as domain

    assert domain.CorpusDerivedTextStored is CorpusDerivedTextStored
    assert domain.StoreDerivedText is StoreDerivedText
    # The marker too: a read model or an endpoint that wants to render "this
    # could not be read" differently has to compare against the constant rather
    # than re-type the string, and `SESSION_EVENTS` is the precedent for a
    # constant living in this list.
    assert domain.UNREADABLE_DEGRADATIONS is UNREADABLE_DEGRADATIONS
    for name in ("CorpusDerivedTextStored", "StoreDerivedText", "UNREADABLE_DEGRADATIONS"):
        assert name in domain.__all__


@pytest.mark.parametrize(
    "command",
    [
        StoreSourceDocument(
            corpus_id=CORPUS_ID, source_id="https://en.wikipedia.org/wiki/X", text="hi"
        ),
        _store_media(CORPUS_ID, "a/b"),
        _store_derived("a/b#perceived", "a/b"),
    ],
)
def test_a_source_id_holding_a_separator_is_refused(command) -> None:
    """A `/` in a source_id makes the document unreachable through the web layer.

    Refused in `decide` rather than at one writer, because every writer funnels
    through here: the fetch keep, `remember`, `remember_page`, the manual upload
    route and the media route all end in one of these three commands, and four
    of the five accept a caller-chosen id. A refusal that lived only in
    `redstring_adapter` would miss the two HTTP routes entirely.

    Measured rather than assumed: `{source_id}` is one path segment, uvicorn
    percent-decodes the path before Starlette routes it, so a `%2F` the browser
    correctly encoded arrives as a real separator and no route matches. See
    `test_a_url_shaped_id_never_reaches_the_handler`.
    """
    with pytest.raises(CommandRejectedError, match="separator"):
        decide(command, initial_state())


def test_a_hash_in_a_source_id_is_still_allowed() -> None:
    """Only `/` is refused, and the narrowness is deliberate.

    `derived_source_id` builds a transcript's id as `<parent>#perceived`
    (`application/perception.py`), so a blanket "no punctuation" rule would
    refuse every perception this project has ever stored. `#` is safe here for
    the reason `/` is not: uvicorn splits the request target on the raw `?` and
    `#` before unquoting, so a percent-encoded one decodes *into* the path and
    stays one segment.

    **This passes with the guard reverted**, and is not evidence the guard
    works -- `test_a_source_id_holding_a_separator_is_refused` is. It is here to
    fail on the plausible next edit, which is widening `"/" in source_id` to a
    charset or a slug pattern; that change would refuse every perception this
    project has ever stored, and nothing else in the suite would say so.
    """
    state = _with_media(initial_state(), "vid")

    [event] = decide(_store_derived("vid#perceived", "vid"), state)

    assert isinstance(event, CorpusDerivedTextStored)

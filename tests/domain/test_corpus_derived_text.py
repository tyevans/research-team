import hashlib
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain.research.corpus import (
    UNREADABLE_DEGRADATIONS,
    CorpusDerivedTextStored,
    CorpusState,
    DropSourceDocument,
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
is what pins that the event's id reaches the state.
"""


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

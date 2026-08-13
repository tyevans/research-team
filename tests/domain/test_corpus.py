from uuid import uuid4

import pytest
from eventsource import CommandRejectedError, DomainEvent

from research_team.domain.corpus import (
    CorpusDocumentDropped,
    CorpusDocumentStored,
    DocumentRecord,
    DropSourceDocument,
    StoreSourceDocument,
    decide,
    evolve,
    initial_state,
)


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
    import hashlib

    event = _stored(corpus_id, text="hello")

    assert event.sha256 == hashlib.sha256(b"hello").hexdigest()


def test_state_carries_metadata_but_never_text():
    """The snapshot-size invariant, pinned rather than intended.

    `SessionSummaryRunner` snapshots every 50 events; a text field here would
    put every document of every corpus into every snapshot. An invariant this
    cheap to violate has to fail a test the moment someone does.
    """
    assert "text" not in DocumentRecord.model_fields

    corpus_id = uuid4()
    state = _with(corpus_id, _stored(corpus_id, text="a longer body"))

    assert state.documents["s1"].char_count == len("a longer body")
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

    assert state.documents["s1"].char_count == len("v2 is longer")
    assert state.documents["s1"].sha256 != old_digest
    assert old_digest not in state.by_digest
    assert state.by_digest[state.documents["s1"].sha256] == "s1"


def test_storing_over_a_dropped_source_id_brings_it_back():
    """Storing asserts presence, so it has to clear the reason it was absent.

    Leaving `dropped_reason` set would leave a live document explaining why it
    is not there.
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

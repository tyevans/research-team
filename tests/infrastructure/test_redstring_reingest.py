from uuid import uuid4

import pytest
from eventsource import StreamId, collect

from research_team.infrastructure.knowledge import redstring_adapter
from research_team.infrastructure.persistence.event_store import (
    build_corpus_repository,
)
from research_team.knowledge.application import KnowledgeError, SourceRef


def _corpus_events(store, project_id):
    """The corpus stream's events, read directly rather than via a projection.

    The read model for the corpus is built in a separate workstream; reading
    the log keeps these assertions independent of it, and the log is the
    thing B12 is actually about -- a projection could be rebuilt, a missing
    event could not.
    """
    return collect(store.read_stream(StreamId(project_id, "Corpus")))


@pytest.mark.asyncio
async def test_re_ingesting_identical_bytes_stores_one_document(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")

    await adapter.ingest(source)
    await adapter.ingest(source)

    envelopes = await _corpus_events(store, project_id)
    assert len(envelopes) == 1


@pytest.mark.asyncio
async def test_re_ingesting_changed_bytes_records_the_revision(tmp_path, build_adapter):
    """Same id, new text is a revision -- both versions stay in the log.

    **The second ingest now raises**, and that is the subject of
    `test_re_ingesting_changed_text_is_refused_rather_than_reported_as_nothing`
    below. It is caught rather than avoided here because this test is about the
    corpus and the corpus half is unchanged: `_store_document` runs before
    extraction, so the revision is recorded whether or not the graph can be
    brought up to date with it. That ordering is deliberate and its reasoning is
    in `_store_document`'s docstring -- the text is the thing that cannot be
    recovered.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))
    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace and Babbage."))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.text for e in envelopes] == [
        "Ada Lovelace.",
        "Ada Lovelace and Babbage.",
    ]


@pytest.mark.asyncio
async def test_re_ingesting_changed_text_is_refused_rather_than_reported_as_nothing(
    tmp_path, build_adapter
):
    """A document whose text moved under a settled extraction is a loud failure.

    `build_graph` is given an `event_store` now -- it has to be, or extraction's
    entity links never reach the log -- so the aggregate is loaded rather than
    built fresh and `Document.record_extraction` can refuse. It keys on the
    **model version alone**, not on the content:

        if model_version in self._current.extraction_model_versions:
            return None

    So a re-ingest of *changed* text lands in the same branch as a re-ingest of
    unchanged text. Reported as a zero-entity success -- which is what this
    adapter did when the branch was first made reachable -- the corpus holds the
    new revision (`_store_document` ran) while the graph goes on describing the
    old one, and nothing anywhere says so. A silently wrong graph is the failure
    this repository is least willing to ship.

    The two cases are told apart by whether anything chunked the document afresh
    during the call: `record_chunking` keys on a signature carrying a digest of
    the text, so it refuses a repeat and emits for new bytes. Free, in the sense
    that the ingest already reads that stream to find the linked chunking.

    *Fails against:* the version that returns `IngestReport(entity_count=0)`
    here, which is the reading of the spec's ripple 2 and looks entirely
    reasonable -- "an unchanged document stops costing model calls" is true and
    is only half of what the branch covers.

    **Proved red on 2026-08-22** by deleting the `if chunking.signatures:` block
    so the branch falls through to the zero report: 2 failed --
    `DID NOT RAISE` here, and
    `test_re_ingesting_changed_bytes_records_the_revision`, which asserts the
    refusal from the corpus side.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    with pytest.raises(KnowledgeError) as raised:
        await adapter.ingest(
            SourceRef(source_id="notes", text="Ada Lovelace corresponded with Babbage.")
        )

    detail = str(raised.value)
    assert "notes" in detail, "the message has to name the document to be actionable"
    assert "source_id" in detail, (
        "and has to say what to do about it; the repairs are a new source id or "
        "a cleared project, and neither is guessable from 'already extracted'"
    )


@pytest.mark.asyncio
async def test_re_ingesting_identical_text_is_still_a_quiet_no_op(tmp_path, build_adapter):
    """The other half of the branch, which must stay silent.

    Without this the refusal above could be written as "raise whenever
    `record_extraction` refuses", which would make every re-ingest of an
    unchanged document a failure -- and re-ingesting unchanged documents is
    ordinary: `ExtractionQueue` retries, and `remember_page` on a page already
    remembered is a normal thing for a turn to do.

    **Proved red on 2026-08-22** by refusing on `built.event is None`
    unconditionally, ignoring the chunking signatures: 3 failed -- this one,
    `test_a_no_op_re_ingest_still_closes_its_pane`, and
    `test_ingest_reports_what_it_extracted`'s second call.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")

    await adapter.ingest(source)
    report = await adapter.ingest(source)

    assert report.entity_count == 0
    assert report.relationship_count == 0


@pytest.mark.asyncio
async def test_identical_bytes_under_a_new_id_are_stored_separately(tmp_path, build_adapter):
    """Two URIs can legitimately serve one document, and each needs its own record."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)
    text = "Ada Lovelace worked with Charles Babbage."

    await adapter.ingest(SourceRef(source_id="mirror-a", text=text))
    await adapter.ingest(SourceRef(source_id="mirror-b", text=text))

    envelopes = await _corpus_events(store, project_id)
    assert [e.event.source_id for e in envelopes] == ["mirror-a", "mirror-b"]


# --- concurrent ingest ------------------------------------------------------
#
# The model puts several tool calls in one assistant message and the executor
# runs them concurrently, so two `remember` calls land in the same moment. Both
# reach `_store_document`, both load the corpus at the same version, and the
# second save loses the compare-and-swap.
#
# What made this worth a fix rather than a shrug is where the error surfaced.
# `remember` catches `KnowledgeError` and nothing else, so an
# `OptimisticLockError` escaped the tool, escaped the executor, and was
# recorded as a `TurnFailed` -- the whole turn discarded because two of its
# tool calls were merely simultaneous. And because a corpus shares its
# project's UUID, the message named the *project*, which is why this reads as
# a project-level fault in the UI when nothing about the project was wrong.


@pytest.mark.asyncio
async def test_two_ingests_at_once_do_not_lose_one_to_a_lock_error(tmp_path, build_adapter):
    """Two `remember` calls in one assistant message must both land."""
    import asyncio

    project_id = uuid4()
    adapter, store, snapshot_store = build_adapter(tmp_path, project_id)

    reports = await asyncio.gather(
        adapter.ingest(SourceRef(source_id="a", text="Ada Lovelace wrote a program.")),
        adapter.ingest(SourceRef(source_id="b", text="Grace Hopper built a compiler.")),
    )

    assert len(reports) == 2
    # Both documents are in the corpus. A lost write here means a source the
    # user paid to fetch is silently absent, which is the failure the corpus
    # layer exists to prevent.
    corpus = build_corpus_repository(store, snapshot_store=snapshot_store)
    state = (await corpus.load(project_id)).state
    assert sorted(state.documents) == ["a", "b"]


@pytest.mark.asyncio
async def test_store_source_refuses_what_ingest_refuses(tmp_path, build_adapter) -> None:
    """Both refusals are kept, and the length one is the non-obvious half.

    Nothing here chunks the text, so the cap looks like it could be relaxed.
    It is not: a document over it can never be extracted later, so storing one
    would create a corpus entry no `remember_page` could ever complete.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.store_source(SourceRef(source_id="  ", text="body"))
    with pytest.raises(KnowledgeError):
        await adapter.store_source(
            SourceRef(source_id="huge", text="x" * (redstring_adapter.MAX_DOCUMENT_CHARS + 1))
        )

    assert await _corpus_events(store, project_id) == []


@pytest.mark.asyncio
async def test_storing_the_same_page_twice_records_it_once(tmp_path, build_adapter) -> None:
    """A run re-reading a page must not grow the corpus each time.

    Automatic saving makes this ordinary rather than exceptional: the model
    does not choose when this runs, so the same url arriving twice in one run
    is expected. The digest check in `_store_document` is what absorbs it, and
    this is the caller that depends on it.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(
        source_id="example-test-a",
        text="Ada Lovelace worked with Charles Babbage.",
        uri="https://example.test/a",
    )

    await adapter.store_source(source)
    await adapter.store_source(source)

    assert len(await _corpus_events(store, project_id)) == 1

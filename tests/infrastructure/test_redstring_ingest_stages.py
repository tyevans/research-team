from uuid import uuid4

import pytest
from eventsource import StreamId, collect
from redstring import SlidingWindowChunker

from research_team.infrastructure.knowledge import redstring_adapter
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
async def test_ingest_reports_its_stages_in_order(tmp_path, build_adapter):
    """The stage sequence, pinned.

    This is what stops a refactor from quietly silencing the pane: the
    sequence is the contract, not the individual calls.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    stages = [note.stage for note in notes]
    assert stages[0] == "storing"
    assert stages[1] == "extracting"
    assert "extracted" in stages
    assert stages[-1] == "consolidated"
    # Consolidation is per *batch* since `_consolidate` moved to
    # `resolve_many`, and the fake's two entities fit in one. So the counter
    # is announced twice for one batch -- before it, with nothing yet decided,
    # and after it, having reached `total`. The pane renders `index/total`,
    # and the trailing announce is what makes it arrive there rather than
    # stopping short and jumping to `consolidated`.
    consolidating = [note for note in notes if note.stage == "consolidating"]
    assert [note.index for note in consolidating] == [0, 2]
    assert all(note.total == 2 for note in consolidating)
    assert all(note.source_id == "notes" for note in notes)


@pytest.mark.asyncio
async def test_the_extracted_note_carries_the_counts_and_the_schema(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    extracted = next(note for note in notes if note.stage == "extracted")
    assert extracted.entities == report.entity_count
    assert extracted.relationships == report.relationship_count
    assert extracted.domain == report.domain


@pytest.mark.asyncio
async def test_model_calls_are_counted_from_inside_extraction(tmp_path, build_adapter):
    """`build_graph` takes no callbacks, so the provider is the way in.

    Without this the pane has nothing to show during the longest part of an
    ingest, and a slow model looks identical to a hung one.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    counted = [note.model_calls for note in notes if note.model_calls]
    assert counted, "no note reported a model call"
    assert max(counted) >= 1


@pytest.mark.asyncio
async def test_a_reporter_that_raises_does_not_fail_the_ingest(tmp_path, build_adapter):
    """A listener must not cost a document already fetched and paid for."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    def explode(note):
        raise RuntimeError("the listener is broken")

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=explode,
    )

    assert report.entity_count > 0


@pytest.mark.asyncio
async def test_a_failed_extraction_reports_a_failed_stage(tmp_path, build_adapter):
    """The pane must be able to say "it broke", not just stop updating."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    with pytest.raises(KnowledgeError):
        await adapter.ingest(
            SourceRef(
                source_id="notes", text="x" * (redstring_adapter.MAX_DOCUMENT_CHARS + 1)
            ),
            report=notes.append,
        )

    assert notes[-1].stage == "failed"
    assert notes[-1].detail


@pytest.mark.asyncio
async def test_a_no_op_re_ingest_still_closes_its_pane(tmp_path, build_adapter):
    """Same content, same model version: nothing new to record, but the pane

    still needs its closing note. A watcher cannot tell "already known" from
    "hung" if the second ingest goes quiet after `extracting`.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    source = SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")

    await adapter.ingest(source)
    notes = []
    await adapter.ingest(source, report=notes.append)

    stages = [note.stage for note in notes]
    assert "extracted" in stages
    assert stages[-1] == "consolidated"


@pytest.mark.asyncio
async def test_a_blank_source_id_announces_nothing(tmp_path, build_adapter):
    """There is no id to attribute a note to, so no note is made."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="   ", text="anything"), report=notes.append)

    assert notes == []


@pytest.mark.asyncio
async def test_fetched_at_reaches_the_stored_document(tmp_path, build_adapter) -> None:
    """The field has existed on the command and the event since the corpus
    layer landed, and has always been None on this path -- `remember` has no
    argument that could fill it. Fails if the adapter drops it again."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(
            source_id="s1",
            text="body",
            uri="https://example.com/a",
            fetched_at="2026-08-10T12:00:00+00:00",
        )
    )

    envelopes = await _corpus_events(store, project_id)
    stored = envelopes[0].event
    assert stored.fetched_at == "2026-08-10T12:00:00+00:00"


@pytest.mark.asyncio
async def test_a_source_without_a_fetch_time_leaves_it_unset(tmp_path, build_adapter) -> None:
    """`remember` cannot know when text it was handed was read, and a guessed
    timestamp would be worse than the absence it replaced."""
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.ingest(SourceRef(source_id="s1", text="body"))

    envelopes = await _corpus_events(store, project_id)
    stored = envelopes[0].event
    assert stored.fetched_at is None


@pytest.fixture
def captured_build_kwargs(monkeypatch):
    """Records the keyword arguments the adapter hands to `build_graph`.

    Deliberately not the `IngestReport`: nothing on the report reflects
    `concurrency` or `chunker`, so an assertion made there would pass whether
    or not either value ever left this adapter. The call is the only place the
    fact is observable without a real model and a stopwatch.
    """
    calls = []
    real_build_graph = redstring_adapter.build_graph

    async def recording_build_graph(document, **kwargs):
        calls.append(kwargs)
        return await real_build_graph(document, **kwargs)

    monkeypatch.setattr(redstring_adapter, "build_graph", recording_build_graph)
    return calls


@pytest.mark.asyncio
async def test_the_extraction_knobs_reach_build_graph(
    tmp_path, build_adapter, captured_build_kwargs
) -> None:
    """Both are plumbing, and plumbing is exactly what silently goes missing.

    This fails with the change reverted -- `concurrency` would be absent from
    the call rather than merely different, since the adapter did not pass it
    at all.
    """
    chunker = SlidingWindowChunker(default_chunk_size=2_000)
    adapter, _, _ = build_adapter(tmp_path, uuid4(), concurrency=8, chunker=chunker)

    await adapter.ingest(SourceRef(source_id="s1", text="body"))

    assert captured_build_kwargs[0]["concurrency"] == 8
    assert captured_build_kwargs[0]["chunker"] is chunker


@pytest.mark.asyncio
async def test_an_adapter_built_without_the_knobs_extracts_serially(
    tmp_path, build_adapter, captured_build_kwargs
) -> None:
    """The default is redstring's serial pipeline, not the configured value.

    `config` is read in the composition root and nowhere else, so a
    `RedstringKnowledge` built directly -- which is every test here, and any
    future caller that is not `build_container` -- gets `concurrency=1`, which
    upstream states is byte-identical to the pre-0.8.0 pipeline. The point is
    that turning concurrency on is a decision made in one visible place rather
    than a default that arrives everywhere at once.
    """
    adapter, _, _ = build_adapter(tmp_path, uuid4())

    await adapter.ingest(SourceRef(source_id="s1", text="body"))

    assert captured_build_kwargs[0]["concurrency"] == 1
    assert captured_build_kwargs[0]["chunker"] is None


@pytest.mark.asyncio
async def test_store_source_keeps_the_text_without_extracting_it(
    tmp_path, build_adapter, captured_build_kwargs
) -> None:
    """The whole point of the method: the document, and no model calls.

    `captured_build_kwargs` staying empty is the load-bearing assertion. Were
    this to call `ingest`, the corpus check would pass identically and the
    only visible difference would be minutes of wall clock and a model call
    per chunk -- which is exactly the mistake the method exists to prevent.
    """
    project_id = uuid4()
    adapter, store, _ = build_adapter(tmp_path, project_id)

    await adapter.store_source(
        SourceRef(
            source_id="example-test-ada",
            text="Ada Lovelace worked with Charles Babbage.",
            uri="https://example.test/ada",
            title="Ada Lovelace",
        )
    )

    envelopes = await _corpus_events(store, project_id)
    assert [envelope.event.source_id for envelope in envelopes] == ["example-test-ada"]
    assert captured_build_kwargs == []

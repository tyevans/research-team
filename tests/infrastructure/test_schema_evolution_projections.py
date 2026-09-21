"""Schema evolution tests for projections and domain aggregates.

Tests reading payloads written by older versions of projection-handled events
and domain aggregate events (such as judgements, corpus, ontology, media
proposals, socratic dialogues, and course catalogs), ensuring backwards
compatibility when new fields or events are introduced.
"""

import json
from datetime import UTC, datetime
from uuid import uuid4

import aiosqlite
from eventsource import StreamId, collect, replay

from research_team.domain.curriculum.curation import CourseFeatured
from research_team.domain.dialogue.socratic import SocraticProgressObserved
from research_team.domain.knowledge.judgements import (
    EntitiesHeldDistinct,
    EntitiesHeldSame,
    EntityKey,
    HoldDistinct,
    HoldSame,
    JudgementWithdrawn,
    WithdrawJudgement,
)
from research_team.domain.knowledge.ontology import OntologyDiscovered
from research_team.domain.research.media_proposals import MediaProposed
from research_team.infrastructure.persistence.event_store import (
    build_judgements_repository,
    build_socratic_dialogue_repository,
)
from research_team.infrastructure.persistence.read_models import (
    CorpusStore,
    SessionSummaryStore,
)


async def _write_old_event(
    db_path: str,
    session_id,
    version: int,
    event_type: str,
    payload: dict,
    aggregate_type: str = "Session",
) -> None:
    """Insert an event exactly as an older build would have left it.

    Deliberately bypasses the library: constructing the event through today's
    model would add today's fields, which is the very thing under test.
    """
    async with aiosqlite.connect(db_path) as connection:
        await connection.execute(
            "INSERT INTO events (event_id, aggregate_id, aggregate_type, event_type,"
            " version, timestamp, payload) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                str(uuid4()),
                str(session_id),
                aggregate_type,
                event_type,
                version,
                datetime.now(UTC).isoformat(),
                json.dumps(payload),
            ),
        )
        await connection.commit()


async def test_a_judgement_survives_the_round_trip_with_its_entity_keys_intact(store):
    """The genuine risk for these three events, and why the case differs from
    every other one in this file.

    Every other test here writes a payload in an *old* shape, because every
    other event grew a field after it was first written. `EntitiesHeldSame`,
    `EntitiesHeldDistinct` and `JudgementWithdrawn` are new -- there is no
    earlier shape to reproduce, so an \"old payload\" case here would be
    fiction.

    What is genuinely untested elsewhere is that `EntityKey`, a nested
    pydantic model, survives serialisation to JSON and back as a *model*
    rather than degrading to a plain dict. Nothing else in this log nests a
    model inside an event payload, so this is the one place that risk lives.
    Written through the aggregate and read back the ordinary way, not
    constructed and compared in memory -- which would prove nothing about the
    JSON round trip.
    """
    judgements_id = uuid4()
    left = EntityKey.of("JFK", "person")
    right = EntityKey.of("John F. Kennedy", "person")
    other_left = EntityKey.of("Iran", "place")
    other_right = EntityKey.of("Iraq", "place")
    repository = build_judgements_repository(store)

    aggregate = repository.create_new(judgements_id)
    aggregate.execute(
        HoldSame(judgements_id=judgements_id, keys=[left, right], reason="same president")
    )
    aggregate.execute(
        HoldDistinct(
            judgements_id=judgements_id,
            left=other_left,
            right=other_right,
            reason="different countries",
        )
    )
    await repository.save(aggregate)

    aggregate = await repository.load(judgements_id)
    held_id = next(
        judgement_id
        for judgement_id, record in aggregate.state.judgements.items()
        if record.kind == "same"
    )
    aggregate.execute(WithdrawJudgement(judgement_id=held_id, reason="mistake"))
    await repository.save(aggregate)

    stream = StreamId(judgements_id, "EntityJudgements")
    events = [envelope.event for envelope in await collect(store.read_stream(stream))]

    same_event = events[0]
    assert isinstance(same_event, EntitiesHeldSame)
    assert same_event.keys == [left, right]
    assert isinstance(same_event.keys[0], EntityKey)
    assert same_event.keys[0].normalized_name == left.normalized_name

    distinct_event = events[1]
    assert isinstance(distinct_event, EntitiesHeldDistinct)
    assert distinct_event.left == other_left
    assert distinct_event.right == other_right
    assert isinstance(distinct_event.left, EntityKey)

    withdrawn_event = events[-1]
    assert isinstance(withdrawn_event, JudgementWithdrawn)
    assert withdrawn_event.judgement_id == held_id


async def _write_corpus_log(store, db_path, project_id) -> None:
    """A three-event corpus log: a document, a medium, and a text derived from it.

    Written straight into the table rather than through the aggregate, for
    this file's usual reason -- today's model would add today's fields. The
    document payload is genuinely old-shaped (no `uri`, `title`,
    `published_at`, `note` or `fetched_at`), and the media payload carries
    every field its event declares, because `CorpusMediaStored` has had one
    shape since it was written.

    **The derived payload deliberately omits `note`, and that omission is the
    point rather than an oversight.** `CorpusDerivedTextStored` shipped with
    `title` alone; `note` was added afterwards, in the final fix pass, so that
    a transcript would not be the one source kind nobody could annotate. This
    payload is therefore the genuinely old shape of that event, and
    `test_a_corpus_log_replays_into_the_read_model` asserts `note is None` to
    hold it -- without that assertion the coverage is incidental, and a later
    tidy that \"completes\" this payload would delete the only proof that an
    event stored before the field existed still folds.
    """
    # Touches the store first so the `events` table exists to insert into --
    # the same reason `test_an_auto_run_started_before_the_fetch_grant_existed_
    # still_loads` above reads an empty stream before writing raw payloads.
    await collect(store.read_stream(StreamId(project_id, "Corpus")))
    await _write_old_event(
        db_path,
        project_id,
        version=1,
        event_type="CorpusDocumentStored",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Corpus",
            "aggregate_version": 1,
            "source_id": "s1",
            "text": "a paper about corpora",
            "sha256": "b" * 64,
        },
        aggregate_type="Corpus",
    )
    await _write_old_event(
        db_path,
        project_id,
        version=2,
        event_type="CorpusMediaStored",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Corpus",
            "aggregate_version": 2,
            "source_id": "v1",
            "sha256": "c" * 64,
            "media_type": "video/mp4",
            "byte_count": 4096,
        },
        aggregate_type="Corpus",
    )
    await _write_old_event(
        db_path,
        project_id,
        version=3,
        event_type="CorpusDerivedTextStored",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Corpus",
            "aggregate_version": 3,
            "source_id": "v1#perceived",
            "derived_from": "v1",
            "text": "A talk about otters.",
            "sha256": "d" * 64,
            "locator_map": json.dumps(
                [
                    {
                        "char_start": 0,
                        "char_end": 20,
                        "locator": {"kind": "time", "start_s": 0.0, "end_s": 8.0},
                    }
                ]
            ),
            "perceived_with": "vision=v1,asr=w1",
            "degradations": json.dumps([]),
        },
        aggregate_type="Corpus",
    )


async def test_a_build_without_the_corpus_projection_still_replays(store, db_path):
    """A new event type is additive: an older build replays a log holding it.

    This is `eventsource.replay`'s documented behaviour -- an event every
    projection ignores counts as applied -- and it is what \"events are not
    rewritten\" depends on. Asserted here rather than assumed, because the same
    property is the reason a *missing* projection is silent, and a reader of
    this file should meet both halves in one place.

    **This test used to be `test_a_build_without_the_media_projection_still_
    replays` and used to be dishonest.** Its docstring said `CorpusProjection`
    had no `@handles(CorpusMediaStored)` \"in this build\", so the media payload
    stood in for an older build's log. That handler now exists
    (`read_models.py`, `_on_media_stored`), and so does one for
    `CorpusDerivedTextStored` -- the test kept passing while demonstrating the
    opposite of what it claimed, because every event in its log was handled.
    Restructured rather than re-worded: the named property is worth keeping,
    and the only honest way to keep it is to replay against a projection that
    genuinely subscribes to none of these events. `SessionSummaryProjection`
    is that projection, in shipped code -- nothing here constructs a handler
    and then declines to register it. What the corpus projection *does* make
    of the same log is the test that follows.

    Proved red by hand before being trusted: `strict=True` with a projection
    whose `handle()` raises turns this into a `ReplayError`, so the assertion
    is on delivery rather than on the absence of an exception.
    """
    project_id = uuid4()
    await _write_corpus_log(store, db_path, project_id)

    sessions = await SessionSummaryStore.open(db_path)
    report = await replay(store, [sessions.projection], strict=True)

    # All three were delivered and rejected by nothing. `applied` counts an
    # event no projection subscribes to, which is the whole claim.
    assert report.applied == 3
    assert not report.failures


async def test_a_derived_text_payload_reads_back_as_a_text_row_pointing_at_its_medium(
    store, db_path
):
    """The other half: the build that *does* handle these events reads them.

    The derived row is the one worth checking. It lands in
    `corpus_documents` beside ordinary prose rather than in a table of its
    own, and it has to stay distinguishable from prose once it is there --
    `derived_from` is the field carrying that distinction, and a row that
    lost it would be a transcript indistinguishable from something a human
    wrote, which is the unfalsifiable-provenance failure
    `CorpusDerivedTextStored` exists to prevent.

    Asserts the row's fields, not `report.applied`: an event no projection
    handles counts as applied, so a count alone would pass against a build
    with `_on_derived_text` deleted. Measured -- commenting out that handler
    leaves the test above green and turns this one's `row is not None` red.
    """
    project_id = uuid4()
    await _write_corpus_log(store, db_path, project_id)

    corpus = await CorpusStore.open(db_path)
    report = await replay(store, [corpus.projection], strict=True)

    assert not report.failures
    document = await corpus.get(project_id, "s1")
    assert document is not None
    assert document.text == "a paper about corpora"
    assert document.sha256 == "b" * 64
    assert document.derived_from is None
    derived = await corpus.get(project_id, "v1#perceived")
    assert derived is not None
    assert derived.derived_from == "v1"
    assert derived.text == "A talk about otters."
    assert derived.perceived_with == "vision=v1,asr=w1"
    # The payload predates `note` -- see `_write_corpus_log`. Asserted rather
    # than left implicit, because this is the only place proving a
    # `CorpusDerivedTextStored` written before that field existed still folds,
    # and an unasserted omission is one tidy away from being \"completed\".
    assert derived.note is None


async def test_an_ontology_written_before_rejected_members_existed_still_loads(store, db_path):
    """`rejected_members` is a case-1 addition: absence must mean \"nothing was
    rejected\", not \"unknown\".

    The distinction is the whole point of the field. A class that found five of
    a declared six with an empty rejection list is a document genuinely short
    one; the same class with an *unrecorded* rejection is a model that invented
    a member. Those are opposite conclusions about whether to trust the pass,
    so the default has to state the first rather than stand in for the second.

    Writes the payload with the key absent, which is the only shape that proves
    the default fills in -- constructing the event through today's model would
    supply it. Would pass with `rejected_members` made required only if this
    fixture also stopped omitting it, and the omission is the test.

    Builds nothing from a repository: `Ontology` has no aggregate, by design
    (see `domain/ontology.py`), so the event is read straight off its stream.
    """
    project_id = uuid4()
    # Applies the schema, which the library does lazily -- otherwise `events`
    # does not exist yet to insert into. Same reason as the research-run case.
    await collect(store.read_stream(StreamId(project_id, "Ontology")))
    await _write_old_event(
        db_path,
        project_id,
        version=1,
        event_type="OntologyDiscovered",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "Ontology",
            "aggregate_version": 1,
            "project_id": str(project_id),
            "source_id": "sekaipedia-songs",
            "model_version": "some-old-model",
            "classes": [
                {
                    "name": "Difficulty",
                    "kind": "ordered_scale",
                    "declared_count": 6,
                    "evidence": {
                        "source_id": "sekaipedia-songs",
                        "start": 100,
                        "end": 180,
                    },
                    "members": [{"name": "EASY", "ordinal": 0}],
                }
            ],
        },
        aggregate_type="Ontology",
    )

    stream = StreamId(project_id, "Ontology")
    events = [envelope.event for envelope in await collect(store.read_stream(stream))]

    discovered = events[0]
    assert isinstance(discovered, OntologyDiscovered)
    assert discovered.classes[0].rejected_members == []
    # `evidence_quoted` is the same shape of change, added 2026-08-24, and this
    # payload omits it for free. True is the truthful default rather than a
    # convenient one: a build with no lenient pass could not have stored a
    # class whose span was anything but a located quote.
    assert discovered.classes[0].evidence_quoted is True
    # The rest of the payload survives the default filling in, which is what
    # separates \"the field defaulted\" from \"the whole class failed to parse\".
    assert discovered.classes[0].name == "Difficulty"
    assert discovered.classes[0].declared_count == 6
    assert discovered.classes[0].members[0].name == "EASY"
    assert discovered.classes[0].evidence.start == 100


async def test_a_media_proposal_written_before_thumbnail_url_existed_still_loads(
    store, db_path
):
    """`thumbnail_url` was not part of `MediaProposed`'s first shape.

    Absence has to mean \"no thumbnail was found\", not \"unknown\" -- a required
    field here would make every proposal a pre-thumbnail build ever wrote
    unreadable the moment the field landed, which is exactly the failure mode
    `domain/events.py` opens by naming. This is not a deliberate break (see
    the field's docstring in `media_proposals.py`): the field should simply
    tolerate absence, the same way `rejected_members` does above.

    Writes the payload with the key absent, which is the only shape that
    proves the default fills in -- constructing the event through today's
    model would supply it.

    Builds nothing from a repository: `MediaProposals` has no dedicated
    repository builder yet (this PR is deliberately inert -- nothing is
    wired), so the event is read straight off its stream, same as the
    `Ontology` case above.
    """
    project_id = uuid4()
    # Applies the schema lazily, same reason as the ontology and
    # research-run cases: `events` does not exist yet to insert into.
    await collect(store.read_stream(StreamId(project_id, "MediaProposals")))
    await _write_old_event(
        db_path,
        project_id,
        version=1,
        event_type="MediaProposed",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "MediaProposals",
            "aggregate_version": 1,
            "project_id": str(project_id),
            "proposal_id": "prop-1",
            "need_id": "need-1",
            "topic_id": "topic-1",
            "page_url": "https://example.com/page",
            "asset_url": "https://example.com/asset.jpg",
            "kind": "image",
            "title": "An asset",
            "reason": "it fit the need",
            "query": "example query",
        },
        aggregate_type="MediaProposals",
    )

    stream = StreamId(project_id, "MediaProposals")
    events = [envelope.event for envelope in await collect(store.read_stream(stream))]

    proposed = events[0]
    assert isinstance(proposed, MediaProposed)
    assert proposed.thumbnail_url == ""
    # The rest of the payload survives the default filling in, which is what
    # separates \"the field defaulted\" from \"the whole event failed to parse\".
    assert proposed.proposal_id == "prop-1"
    assert proposed.asset_url == "https://example.com/asset.jpg"


async def test_a_dialogue_written_before_the_opening_prompt_existed_still_loads(
    db_path, store
):
    """Case 1 of the strategy in `domain/events.py`: a field added with a
    default that means what its absence meant.

    `opening_prompt` was added to `SocraticDialogueStarted` after the first
    draft. An older payload has no key, the default fills in, and the value
    reads as \"the opening question was not recorded\" -- which is honest,
    because the dialogue is still resumable from its goal and its turns.

    Red against a build that makes `opening_prompt` required: every dialogue
    written before it existed stops loading, and the failure surfaces as a
    reader's dialogue simply refusing to resume.
    """
    dialogue_id = uuid4()
    # Applies the schema lazily, for the media-proposal case's reason: nothing
    # has written to this database yet, so `events` does not exist to insert
    # into. The brief's version of this test omitted the line and failed on
    # `no such table: events`.
    await collect(store.read_stream(StreamId(dialogue_id, "SocraticDialogue")))
    await _write_old_event(
        db_path,
        dialogue_id,
        1,
        "SocraticDialogueStarted",
        {
            "aggregate_id": str(dialogue_id),
            "aggregate_type": "SocraticDialogue",
            "aggregate_version": 1,
            "project_id": str(uuid4()),
            "topic": "the Nicene settlement",
            "goal": "understand what the creed settled",
            "stopping_condition": "the reader can state it in their own words",
            "opened_at": datetime.now(UTC).isoformat(),
        },
        aggregate_type="SocraticDialogue",
    )

    repository = build_socratic_dialogue_repository(store)
    dialogue = await repository.load(dialogue_id)

    assert dialogue.state.goal == "understand what the creed settled"
    assert dialogue.state.stopping_condition == ("the reader can state it in their own words")
    assert dialogue.state.is_started


async def test_a_course_featured_written_before_rank_existed_defaults_to_zero(store, db_path):
    """`rank` is a case-1 addition to `CourseFeatured`; absence must mean 0.

    0 is the lowest rank the hero row uses, so a payload written before
    ranking existed reads as \"unranked, sorts first\" rather than as an
    error -- there is no earlier meaning to preserve beyond \"this was
    featured\", and 0 is the value that already carried that meaning.

    Writes the payload with the key absent, which is the only shape that
    proves the default fills in -- constructing the event through today's
    model would supply it.

    Builds nothing from a repository: `CourseCatalog` has no aggregate, by
    design (see `domain/catalog_curation.py`), so the event is read straight
    off its stream, same as the `Ontology` case above.
    """
    project_id = uuid4()
    # Applies the schema lazily, for the media-proposal case's reason: nothing
    # has written to this database yet, so `events` does not exist to insert
    # into.
    await collect(store.read_stream(StreamId(project_id, "CourseCatalog")))
    await _write_old_event(
        db_path,
        project_id,
        version=1,
        event_type="CourseFeatured",
        payload={
            "aggregate_id": str(project_id),
            "aggregate_type": "CourseCatalog",
            "aggregate_version": 1,
            "project_id": str(project_id),
            "slug": "warp-drive",
        },
        aggregate_type="CourseCatalog",
    )

    stream = StreamId(project_id, "CourseCatalog")
    events = [envelope.event for envelope in await collect(store.read_stream(stream))]

    featured = events[0]
    assert isinstance(featured, CourseFeatured)
    assert featured.rank == 0
    # The rest of the payload survives the default filling in, which is what
    # separates \"the field defaulted\" from \"the whole event failed to parse\".
    assert featured.slug == "warp-drive"


async def test_an_observation_written_before_evidence_kinds_existed_reads_as_assessment(
    db_path, store
):
    """The same case for `SocraticProgressObserved.evidence`.

    The default is \"assessment\" and not \"attempt\", deliberately: an
    unlabelled observation is the model's judgement until something says
    otherwise, and defaulting to \"attempt\" would silently promote every old
    opinion to a graded fact -- which is the exact distinction `EvidenceKind`
    exists to keep.
    """
    dialogue_id = uuid4()
    # Applies the schema lazily, for the media-proposal case's reason: nothing
    # has written to this database yet, so `events` does not exist to insert
    # into. The brief's version of this test omitted the line and failed on
    # `no such table: events`.
    await collect(store.read_stream(StreamId(dialogue_id, "SocraticDialogue")))
    await _write_old_event(
        db_path,
        dialogue_id,
        1,
        "SocraticDialogueStarted",
        {
            "aggregate_id": str(dialogue_id),
            "aggregate_type": "SocraticDialogue",
            "aggregate_version": 1,
            "project_id": str(uuid4()),
            "topic": "t",
            "goal": "g",
            "stopping_condition": "s",
            "opened_at": datetime.now(UTC).isoformat(),
        },
        aggregate_type="SocraticDialogue",
    )
    await _write_old_event(
        db_path,
        dialogue_id,
        2,
        "SocraticProgressObserved",
        {
            "aggregate_id": str(dialogue_id),
            "aggregate_type": "SocraticDialogue",
            "aggregate_version": 2,
            "observation": "named the two parties",
        },
        aggregate_type="SocraticDialogue",
    )

    repository = build_socratic_dialogue_repository(store)
    dialogue = await repository.load(dialogue_id)

    assert dialogue.state.observations == ["named the two parties"]
    # And the kind it defaulted to, read off the stream because
    # `SocraticDialogueState` carries the observation texts and not their
    # evidence. Without this line the test passes with the default flipped to
    # \"attempt\" -- which is the failure the docstring above is about, so the
    # state assertion alone would not have been a test of it.
    stream = StreamId(dialogue_id, "SocraticDialogue")
    events = [envelope.event for envelope in await collect(store.read_stream(stream))]
    observed = events[-1]
    assert isinstance(observed, SocraticProgressObserved)
    assert observed.evidence == "assessment"

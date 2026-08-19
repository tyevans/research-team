"""The dialogue tables: what they store, and the order they refuse to lose.

Every assertion here is on a *row* and on the value the event carried, never on
"the append returned" or "replay completed". An event no projection handles
counts as APPLIED rather than rejected -- `strict` raises only when a handler
itself raises -- so a build with `SocraticDialogueProjection` never registered
replays perfectly cleanly and serves an empty table. Any assertion weaker than
"this row holds this value" passes against exactly the bug this feature is most
likely to ship with.

Modelled on `test_ask_read_model.py`, including driving through the aggregate
rather than appending raw: `SocraticDialogue` has a `decide` that refuses a
turn before a start and everything after a conclusion, and a test that bypassed
it could store a sequence the domain would have rejected.
"""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.domain.socratic_dialogue import (
    ConcludeSocraticDialogue,
    ObserveSocraticProgress,
    RecordSocraticTurn,
    SocraticDialogueStarted,
    StartSocraticDialogue,
)
from research_team.infrastructure.persistence import read_models
from research_team.infrastructure.persistence.event_store import (
    build_socratic_dialogue_repository,
)
from research_team.infrastructure.persistence.read_models import (
    SocraticDialogueProjection,
    SocraticDialogueRunner,
)


@pytest.fixture
def transcripts(store, publisher):
    return build_socratic_dialogue_repository(store, publisher)


@pytest.fixture
async def runner(db_path, store, publisher):
    started = SocraticDialogueRunner(store, db_path, publisher)
    await started.start()
    yield started
    await started.stop()


async def _dialogue(
    transcripts,
    project_id,
    dialogue_id,
    *,
    turns=(),
    observations=(),
    conclude=None,
    goal="understand what the creed settled",
    stopping_condition="the reader states it in their own words",
    opened_at=None,
):
    aggregate = transcripts.create_new(dialogue_id)
    aggregate.execute(
        StartSocraticDialogue(
            dialogue_id=dialogue_id,
            project_id=project_id,
            topic="the Nicene settlement",
            goal=goal,
            stopping_condition=stopping_condition,
            opening_prompt="What do you already believe about it?",
            # Passed explicitly where a test asserts on ordering: two
            # `datetime.now(UTC)` calls microseconds apart can collide, and a
            # tie in `opened_at desc` is resolved by nothing, so the ordering
            # assertion would fail once in a long while for no real reason.
            opened_at=opened_at if opened_at is not None else datetime.now(UTC),
        )
    )
    # `(what the reader answered, what the dialogue said back)` -- one
    # exchange, reader first. The question each `reply` answers is the previous
    # entry's `prompt`, or `opening_prompt` for the first.
    for reply, prompt, citations in turns:
        aggregate.execute(
            RecordSocraticTurn(
                dialogue_id=dialogue_id,
                reply=reply,
                prompt=prompt,
                citations=citations,
            )
        )
    for observation, evidence, detail in observations:
        aggregate.execute(
            ObserveSocraticProgress(
                dialogue_id=dialogue_id,
                observation=observation,
                evidence=evidence,
                detail=detail,
            )
        )
    if conclude is not None:
        aggregate.execute(ConcludeSocraticDialogue(dialogue_id=dialogue_id, reason=conclude))
    await transcripts.save(aggregate)


async def test_a_started_dialogue_stores_its_goal_and_stopping_condition(
    runner, transcripts, project_id
):
    """The two columns the whole feature rests on, asserted as stored values.

    This is the resumption path's source of truth: `SocraticDialogueService`
    reads these back when the live cache has dropped the dialogue, so a
    projection that stored the topic and dropped the goal would resume a
    dialogue aimed at nothing -- and every request would still answer 200.

    Red against a build with `SocraticDialogueProjection` unregistered, which
    is the failure this file exists for: `get` returns None and this fails on
    the attribute rather than on a status code that was never wrong.
    """
    dialogue_id = uuid4()
    await _dialogue(transcripts, project_id, dialogue_id)
    await runner.caught_up()

    row = await runner.get(dialogue_id)

    assert row is not None, "no row: the projection is not following the log"
    assert row.project_id == project_id
    assert row.topic == "the Nicene settlement"
    assert row.goal == "understand what the creed settled"
    assert row.stopping_condition == "the reader states it in their own words"
    assert row.opening_prompt == "What do you already believe about it?"
    assert row.status == "started"
    assert row.turn_count == 0


async def test_three_turns_come_back_in_the_order_they_were_asked(
    runner, transcripts, project_id
):
    """Order is the assertion, not the count. A read leaning on rowid ordering
    would pass until a `rebuild` reordered the inserts, which is why
    `SocraticTurnRow.position` is a stored column and `turns_for` sorts on it.
    """
    dialogue_id = uuid4()
    await _dialogue(
        transcripts,
        project_id,
        dialogue_id,
        turns=[
            ("It settled Arianism.", "Settled by whom?", (("source", "a"),)),
            ("The council of 325.", "And against whom?", ()),
            ("Against Arius.", "What did he actually claim?", (("source", "b"),)),
        ],
    )
    await runner.caught_up()

    turns = await runner.turns_for(dialogue_id)

    assert [turn.position for turn in turns] == [0, 1, 2]
    assert [turn.reply for turn in turns] == [
        "It settled Arianism.",
        "The council of 325.",
        "Against Arius.",
    ]
    assert [turn.prompt for turn in turns] == [
        "Settled by whom?",
        "And against whom?",
        "What did he actually claim?",
    ]
    assert turns[0].citations == [{"kind": "source", "id": "a"}]
    assert turns[1].citations == []

    row = await runner.get(dialogue_id)
    assert row.turn_count == 3
    # Precomputed from the newest turn rather than stored a second time. Red
    # against a projection that writes it only on start, where a resumed
    # dialogue would show the reader the opening question forever.
    assert row.pending_prompt == "What did he actually claim?"
    # And the utterance no turn holds: what the dialogue opened with.
    assert row.opening_prompt == "What do you already believe about it?"


async def test_the_speakers_are_not_swapped_on_the_way_into_the_table(
    runner, transcripts, project_id
):
    """The `prompt`/`reply` ruling, pinned a second time at the storage layer.

    Asserted with two texts that could not be mistaken for each other, because
    a projection that swapped them would produce a transcript that still reads
    as a conversation -- just one where the reader asks all the questions, and
    nothing but an assertion like this one would notice.

    Red against `prompt=event.reply`.
    """
    dialogue_id = uuid4()
    await _dialogue(
        transcripts,
        project_id,
        dialogue_id,
        turns=[("THE READER ANSWERED THIS", "THE DIALOGUE SAID THIS", ())],
    )
    await runner.caught_up()

    turn = (await runner.turns_for(dialogue_id))[0]

    assert turn.reply == "THE READER ANSWERED THIS"
    assert turn.prompt == "THE DIALOGUE SAID THIS"


async def test_an_observation_is_stored_with_the_kind_of_evidence_behind_it(
    runner, transcripts, project_id
):
    """A stopping condition met entirely by the model's own assessments is a
    dialogue that graded its own homework, and the only thing that makes that
    visible later is storing which kind each observation was. Red against a
    projection that stores the text and drops `evidence`.
    """
    dialogue_id = uuid4()
    await _dialogue(
        transcripts,
        project_id,
        dialogue_id,
        observations=[
            ("distinguished creed from council", "attempt", "mcq nicene-1 correct"),
            ("used homoousios correctly", "assessment", ""),
        ],
    )
    await runner.caught_up()

    row = await runner.get(dialogue_id)

    assert row.observations == [
        {
            "observation": "distinguished creed from council",
            "evidence": "attempt",
            "detail": "mcq nicene-1 correct",
        },
        {
            "observation": "used homoousios correctly",
            "evidence": "assessment",
            "detail": "",
        },
    ]


async def test_a_concluded_dialogue_says_so_and_says_why(runner, transcripts, project_id):
    """Both columns, because either alone is a dialogue that ended for no
    stated reason. Red against a projection that handles the conclusion by
    setting `status` and dropping `reason` -- a dialogue abandoned halfway
    would then be indistinguishable from one that met its stopping condition,
    which is the single fact this feature is trying to establish.
    """
    dialogue_id = uuid4()
    await _dialogue(transcripts, project_id, dialogue_id, conclude="met")
    await runner.caught_up()

    row = await runner.get(dialogue_id)

    assert row.status == "concluded"
    assert row.concluded_reason == "met"


async def test_only_this_project_s_dialogues_are_listed(runner, transcripts, project_id):
    """Red against a `for_project` with no filter, which would list every
    reader's dialogue on every project's page.

    **Two dialogues on the mine project, not one**, so the `opened_at desc`
    ordering is exercised rather than merely present: with a single row a
    reversed sort passes, and the history list would be drawn oldest-first
    with nothing failing. An earlier draft of this test seeded one per project
    and had exactly that hole.
    """
    older, newer, theirs = uuid4(), uuid4(), uuid4()
    await _dialogue(transcripts, project_id, older, opened_at=datetime(2026, 8, 1, tzinfo=UTC))
    await _dialogue(transcripts, project_id, newer, opened_at=datetime(2026, 8, 2, tzinfo=UTC))
    await _dialogue(transcripts, uuid4(), theirs)
    await runner.caught_up()

    listed = await runner.for_project(project_id)

    assert [row.id for row in listed] == [newer, older]


async def test_a_rebuild_reproduces_the_positions_and_the_derived_question(
    runner, transcripts, project_id
):
    """`rebuild()` truncates and replays, and is allowed here for the reason it
    is allowed on the ask tables: every column comes from an event payload,
    including `position`, which the projection derives in log order and
    therefore reproduces. Red against a `position` taken from a row count read
    at insert time under a different physical order.

    **The second assertion is the one to keep.** `pending_prompt` is the only
    value in these tables that is *derived from another stored value* -- it is
    the newest turn's `prompt`, precomputed. Everything else is copied straight
    off an event, so nothing else here can disagree with the log. A projection
    that wrote it on start and forgot to overwrite it per turn, or that wrote
    it from the wrong field, produces a dialogue whose transcript reads
    perfectly and whose "what am I answering?" is a question from three
    exchanges ago -- and a rebuild is the moment that surfaces, which is the
    worst time to find it.

    This is the assertion the team lead asked for against an earlier draft that
    stored the outstanding question twice, in the form that survives now that
    it is stored once and derived. It is not awkward to write, which is the
    signal that the redundancy is at the right level: a read model precomputing
    something is fine, a log holding two copies of one utterance was not.
    """
    dialogue_id = uuid4()
    await _dialogue(
        transcripts,
        project_id,
        dialogue_id,
        turns=[("1", "a?", ()), ("2", "b?", ()), ("3", "c?", ())],
    )
    await runner.caught_up()
    before = [(turn.position, turn.prompt) for turn in await runner.turns_for(dialogue_id)]
    # The invariant, before the rebuild: the precomputed question is the newest
    # thing the dialogue actually said.
    assert (await runner.get(dialogue_id)).pending_prompt == before[-1][1] == "c?"

    await runner.rebuild()

    after = [(turn.position, turn.prompt) for turn in await runner.turns_for(dialogue_id)]
    assert after == before
    # And the derived value still agrees with the turns it was derived from.
    # A replay in a different physical order is exactly what would break this
    # while leaving every other column identical.
    assert (await runner.get(dialogue_id)).pending_prompt == after[-1][1]


async def test_a_turn_against_a_dialogue_the_projection_never_saw_is_dropped():
    """The same policy `AskConversationStore.record` states: `decide` refuses a
    turn before a start, so the only way to arrive here is a log whose head
    this projection never saw, and a DLQ entry per turn would bury a real
    failure under a stream that cannot be repaired anyway.

    Driving it through a projection is not reachable from a test -- a rebuild
    from a checkpoint that skipped the head is not something the runner can be
    put into -- so this asserts the store's own guard directly, which is the
    honest reachable version.
    """
    from research_team.infrastructure.persistence.read_models import SocraticDialogueStore

    store = await SocraticDialogueStore.open(":memory:")
    try:
        await store.record(
            uuid4(),
            reply="nothing",
            prompt="orphan?",
            citations=[],
            recorded_at=datetime.now(UTC),
        )
        assert await store.turns_for(uuid4()) == []
    finally:
        await store.close()


class _ProjectionMissingItsStartHandler(SocraticDialogueProjection):
    """`SocraticDialogueProjection` with the start handler's `@handles` gone.

    Overriding the method without re-decorating is what strips it:
    `HandlerRegistry` scans the *instance's* methods for the decorator's
    marker, and this override carries none, so `subscribed_to()` comes back
    with three event types instead of four. Verified by the test below rather
    than assumed -- an override that stayed registered would make the whole
    test vacuous, which is why it is asserted first.
    """

    async def _on_started(self, event) -> None:  # pragma: no cover - never routed
        await super()._on_started(event)


async def test_a_dialogue_whose_start_nothing_handles_is_silently_empty(
    db_path, store, publisher, transcripts, project_id, monkeypatch
):
    """The measurement that justifies every other assertion in this file.

    Measured on 2026-08-17, not reasoned: with the start handler unregistered,
    a dialogue is started through the aggregate and **nothing raises, no DLQ
    entry is written, and `get` answers None**. A read model that is silently
    empty is what a missing handler produces -- so an assertion like "the
    request succeeded" or "the projection started" stays green against exactly
    the bug this feature is most likely to ship with, and every assertion here
    is on a row and a carried value for that reason.

    **Two mechanisms produce that silence and this test exercises the second
    one.** CLAUDE.md records that an event *delivered* to a projection that
    ignores it counts as APPLIED rather than rejected -- `strict=True` raises
    only when a `handle()` itself raises. What happens here is one step
    earlier: `SubscriptionConfig` leaves `event_types=None`, so
    `EventFilter.from_subscriber` derives the filter from the projection's
    `@handles` set, and the event is never *delivered* at all. Different paths,
    identical symptom, and neither one raises.

    **Why the obvious version of this test cannot work.** The natural place for
    this is `test_a_started_dialogue_stores_its_goal_and_stopping_condition`
    with the decorator removed -- and that test cannot fail on `row is None`
    for the defect it names. Because the event is filtered out, the
    subscription's `last_processed_position` never advances past it, so
    `runner.caught_up()` blocks for its full timeout and raises `TimeoutError`
    from the helper before any assertion runs. Hence the fixed settle below
    rather than `caught_up`: it is the only way to reach the assertion that
    matters.

    A fixed settle is a cost, stated plainly: one second of wall clock, and a
    machine slow enough to need more would make this pass for the wrong reason.
    That is tolerable only because the assertion is `is None` -- a false pass
    here means the test proved nothing, not that a defect shipped.
    """
    monkeypatch.setattr(
        read_models, "SocraticDialogueProjection", _ProjectionMissingItsStartHandler
    )
    assert (
        SocraticDialogueStarted not in _ProjectionMissingItsStartHandler(None).subscribed_to()
    ), "the override did not strip the handler; this test proves nothing"

    runner = SocraticDialogueRunner(store, db_path, publisher)
    await runner.start()
    try:
        dialogue_id = uuid4()
        await _dialogue(transcripts, project_id, dialogue_id)
        # Not `caught_up()` -- see the docstring. Nothing else in this file
        # sleeps on a clock.
        await asyncio.sleep(1.0)

        assert await runner.get(dialogue_id) is None
        assert await runner.failures() == []
    finally:
        await runner.stop()

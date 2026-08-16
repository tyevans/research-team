"""The ask tables: what they store, and the order they refuse to lose.

Every assertion here is on a *row* and on the value the event carried, never
on "the append returned" or "replay completed". An event no projection
handles counts as APPLIED rather than rejected -- `strict` raises only when a
handler itself raises -- so a build with `AskConversationProjection` never
registered replays perfectly cleanly and serves an empty table. Any assertion
weaker than "this row holds this value" passes against exactly the bug this
feature is most likely to ship with.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.domain.ask_conversation import RecordAskTurn, StartAskConversation
from research_team.infrastructure.persistence.event_store import (
    build_ask_conversation_repository,
)
from research_team.infrastructure.persistence.read_models import AskConversationRunner


@pytest.fixture
def transcripts(store, publisher):
    return build_ask_conversation_repository(store, publisher)


@pytest.fixture
async def runner(db_path, store, publisher):
    started = AskConversationRunner(store, db_path, publisher)
    await started.start()
    yield started
    await started.stop()


async def _ask(transcripts, project_id, conversation_id, turns):
    """Start a conversation and record its turns, through the aggregate.

    Driven through the repository rather than appended raw, unlike the
    ontology tests: `AskConversation` has an aggregate and `AskService` uses
    it, so a test that bypassed it could store a turn ordering `decide` would
    have refused.
    """
    aggregate = transcripts.create_new(conversation_id)
    aggregate.execute(
        StartAskConversation(
            conversation_id=conversation_id,
            project_id=project_id,
            opened_at=datetime.now(UTC),
        )
    )
    for question, answer, citations in turns:
        aggregate.execute(
            RecordAskTurn(
                conversation_id=conversation_id,
                question=question,
                answer=answer,
                citations=citations,
            )
        )
    await transcripts.save(aggregate)


async def test_three_turns_come_back_in_the_order_they_were_asked(
    runner, transcripts, project_id
):
    """Order is the assertion, not the count. A read that leaned on rowid
    ordering would pass this until a `rebuild` reordered the inserts, which is
    why `AskTurnRow.position` is a stored column and `turns_for` sorts on it.
    """
    conversation_id = uuid4()
    await _ask(
        transcripts,
        project_id,
        conversation_id,
        [
            ("first?", "one", (("source", "a"),)),
            ("second?", "two", ()),
            ("third?", "three", (("source", "b"),)),
        ],
    )
    await runner.caught_up()

    turns = await runner.turns_for(conversation_id)

    assert [turn.question for turn in turns] == ["first?", "second?", "third?"]
    assert [turn.answer for turn in turns] == ["one", "two", "three"]
    assert [turn.position for turn in turns] == [0, 1, 2]


async def test_each_turns_citations_stay_with_the_turn_that_produced_them(
    runner, transcripts, project_id
):
    """The failure this catches is citations accumulating onto the
    conversation instead of the turn -- which reads correctly for a
    one-turn conversation and attributes the wrong sources for any other."""
    conversation_id = uuid4()
    await _ask(
        transcripts,
        project_id,
        conversation_id,
        [
            ("first?", "one", (("source", "a"),)),
            ("second?", "two", ()),
            ("third?", "three", (("source", "b"), ("source", "c"))),
        ],
    )
    await runner.caught_up()

    turns = await runner.turns_for(conversation_id)

    assert [turn.citations for turn in turns] == [
        [{"kind": "source", "id": "a"}],
        [],
        [{"kind": "source", "id": "b"}, {"kind": "source", "id": "c"}],
    ]


async def test_a_conversation_records_the_project_it_was_asked_of(
    runner, transcripts, project_id
):
    conversation_id = uuid4()
    await _ask(transcripts, project_id, conversation_id, [("q?", "a", ())])
    await runner.caught_up()

    row = await runner.get(conversation_id)

    assert row is not None
    assert row.project_id == project_id
    assert row.turn_count == 1
    # The first question, so a history list has something to show without
    # loading every turn of every conversation it lists.
    assert row.first_question == "q?"


async def test_one_projects_conversations_are_invisible_to_another(
    runner, transcripts, project_id
):
    """The spec asks for it directly: asking project A must leave project B
    alone. The feed is scoped separately, and could be right while this was
    wrong."""
    mine, theirs = uuid4(), uuid4()
    await _ask(transcripts, project_id, mine, [("mine?", "a", ())])
    await _ask(transcripts, uuid4(), theirs, [("theirs?", "b", ())])
    await runner.caught_up()

    listed = await runner.for_project(project_id)

    assert [row.id for row in listed] == [mine]


async def test_an_unknown_conversation_is_none_rather_than_an_error(runner, project_id):
    assert await runner.get(uuid4()) is None


async def test_a_rebuild_reproduces_the_turns_in_the_same_order(
    runner, transcripts, project_id
):
    """Every column here comes from an event payload, so a truncate-and-replay
    must reproduce the table exactly -- including `position`, which is derived
    during projection rather than carried by the event. Would pass with
    `position` computed from the row count *at read time* only if the read
    order were already right, which is the thing under test."""
    conversation_id = uuid4()
    await _ask(
        transcripts,
        project_id,
        conversation_id,
        [("first?", "one", ()), ("second?", "two", ()), ("third?", "three", ())],
    )
    await runner.caught_up()

    await runner.rebuild()

    turns = await runner.turns_for(conversation_id)
    assert [turn.question for turn in turns] == ["first?", "second?", "third?"]
    assert [turn.position for turn in turns] == [0, 1, 2]

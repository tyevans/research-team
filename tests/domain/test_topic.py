"""The topic's rules, as three pure functions.

Same shape as `test_decider.py`: no aggregate, no repository, no event loop.
`decide` takes a command and a state and returns events or raises; `evolve`
takes a state and an event and returns the next state.

`decide` doubles as the inventory of legal transitions, so a transition with no
test here is one nobody has claimed is legal.
"""

from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain.corpus import SourceDocumentStored
from research_team.domain.topic import (
    AcknowledgeTrigger,
    AddSubQuestion,
    LinkEntity,
    LinkSource,
    OpenTopic,
    RecordContest,
    RecordFinding,
    RecordGap,
    RecordInvestigation,
    ResolveContest,
    ResolveSubQuestion,
    SetTopicStatus,
    Topic,
    TopicGapRecorded,
    TopicOpened,
    UnlinkSource,
    decide,
    evolve,
    initial_state,
)


def run(state, *commands):
    """Fold a sequence of commands through decide/evolve. The whole harness."""
    for command in commands:
        for event in decide(command, state):
            state = evolve(state, event)
    return state


def opened(topic_id=None, project_id=None, **kwargs):
    """A topic that has been opened and nothing else."""
    return run(
        initial_state(),
        OpenTopic(
            topic_id=topic_id or uuid4(),
            project_id=project_id or uuid4(),
            question=kwargs.get("question", "does the thing work?"),
            rationale=kwargs.get("rationale", "it is on the critical path"),
            scope=kwargs.get("scope", ""),
        ),
    )


# ---------------- creation ----------------


def test_opening_a_topic_records_the_question_and_its_rationale():
    topic_id, project_id = uuid4(), uuid4()

    [event] = decide(
        OpenTopic(
            topic_id=topic_id,
            project_id=project_id,
            question="what is the escalation threshold?",
            rationale="two SMEs disagreed in intake",
        ),
        initial_state(),
    )

    assert isinstance(event, TopicOpened)
    assert event.aggregate_id == topic_id
    assert event.project_id == project_id
    assert event.rationale == "two SMEs disagreed in intake"


def test_a_topic_without_a_rationale_is_refused():
    """The defence against an autonomous run manufacturing its own work.

    A topic that appears with no reason cannot be told apart from one invented
    to keep a loop busy, which is why this is a domain rule and not a nicety
    enforced by whichever caller happens to remember.
    """
    with pytest.raises(CommandRejectedError, match="rationale"):
        decide(
            OpenTopic(topic_id=uuid4(), project_id=uuid4(), question="q?", rationale="   "),
            initial_state(),
        )


def test_a_topic_without_a_question_is_refused():
    with pytest.raises(CommandRejectedError, match="question"):
        decide(
            OpenTopic(topic_id=uuid4(), project_id=uuid4(), question="", rationale="because"),
            initial_state(),
        )


def test_a_topic_cannot_be_opened_twice():
    with pytest.raises(CommandRejectedError, match="already opened"):
        decide(
            OpenTopic(topic_id=uuid4(), project_id=uuid4(), question="q?", rationale="r"),
            opened(),
        )


@pytest.mark.parametrize(
    "command",
    [
        AddSubQuestion(key="a", question="q?"),
        LinkSource(source_id="s1"),
        RecordFinding(summary="found"),
        RecordInvestigation(at_position="p1"),
    ],
    ids=lambda c: type(c).__name__,
)
def test_nothing_is_accepted_before_the_topic_is_opened(command):
    with pytest.raises(CommandRejectedError, match="not opened"):
        decide(command, initial_state())


# ---------------- sub-questions ----------------


def test_sub_questions_start_open_and_resolve():
    state = run(opened(), AddSubQuestion(key="a", question="what is the number?"))
    assert state.open_sub_questions == ["a"]

    state = run(state, ResolveSubQuestion(key="a", answer="24 hours"))
    assert state.open_sub_questions == []
    assert state.sub_questions["a"].answer == "24 hours"


def test_a_sub_question_cannot_be_added_twice():
    state = run(opened(), AddSubQuestion(key="a", question="q?"))
    with pytest.raises(CommandRejectedError, match="already exists"):
        decide(AddSubQuestion(key="a", question="q?"), state)


def test_resolving_an_unknown_sub_question_names_it():
    with pytest.raises(CommandRejectedError, match="nope"):
        decide(ResolveSubQuestion(key="nope", answer="x"), opened())


def test_a_sub_question_cannot_be_resolved_twice():
    state = run(
        opened(),
        AddSubQuestion(key="a", question="q?"),
        ResolveSubQuestion(key="a", answer="first"),
    )
    with pytest.raises(CommandRejectedError, match="already resolved"):
        decide(ResolveSubQuestion(key="a", answer="second"), state)


def test_resolving_requires_an_actual_answer():
    state = run(opened(), AddSubQuestion(key="a", question="q?"))
    with pytest.raises(CommandRejectedError, match="answer"):
        decide(ResolveSubQuestion(key="a", answer="  "), state)


# ---------------- links ----------------


def test_linking_the_same_source_twice_is_a_no_op_rather_than_a_rejection():
    """An autonomous round that re-reads a source it already linked did nothing
    wrong, and raising here would fail the whole turn over it."""
    state = run(opened(), LinkSource(source_id="s1"))

    assert decide(LinkSource(source_id="s1"), state) == []
    assert state.source_ids == ["s1"]


def test_unlinking_requires_a_reason_and_removes_the_link():
    state = run(opened(), LinkSource(source_id="s1"))

    with pytest.raises(CommandRejectedError, match="reason"):
        decide(UnlinkSource(source_id="s1", reason=""), state)

    state = run(state, UnlinkSource(source_id="s1", reason="not about this after all"))
    assert state.source_ids == []


def test_unlinking_something_never_linked_is_refused():
    with pytest.raises(CommandRejectedError, match="not linked"):
        decide(UnlinkSource(source_id="ghost", reason="r"), opened())


def test_entities_link_and_deduplicate():
    state = run(opened(), LinkEntity(entity_id="e1", name="Ada"))
    assert decide(LinkEntity(entity_id="e1"), state) == []
    assert state.entity_ids == ["e1"]


# ---------------- investigation and findings ----------------


def test_the_first_investigation_moves_a_topic_to_investigating():
    state = run(opened(), RecordInvestigation(at_position="p1"))

    assert state.status == "investigating"
    assert state.investigations == 1
    assert state.last_investigated_at == "p1"


def test_an_investigation_snapshots_the_finding_count_at_the_time():
    """What makes thrash computable without consulting the log.

    The next look compares `findings` against this snapshot; if nothing moved,
    the look produced nothing -- regardless of what it said about itself.
    """
    state = run(
        opened(),
        RecordInvestigation(at_position="p1"),
        RecordFinding(summary="learned something"),
        RecordInvestigation(at_position="p2"),
    )

    assert state.findings == 1
    assert state.findings_at_last_investigation == 1


def test_an_investigation_must_say_where_the_log_stood():
    with pytest.raises(CommandRejectedError, match="log stood"):
        decide(RecordInvestigation(at_position=""), opened())


def test_an_investigation_can_say_how_it_ended():
    """ "nothing recorded" and "failed" were the same field with different
    English, so nothing downstream could tell a fruitless round from a broken
    one."""
    events = decide(RecordInvestigation(at_position="p1", outcome="failed"), opened())

    assert events[0].outcome == "failed"


def test_an_investigation_that_does_not_say_leaves_it_unset():
    """None means "written before this was recorded", and is not one of the
    three outcomes. Defaulting to a real value would assert something about
    rounds nobody observed."""
    events = decide(RecordInvestigation(at_position="p1"), opened())

    assert events[0].outcome is None


def test_a_finding_needs_a_summary():
    with pytest.raises(CommandRejectedError, match="summary"):
        decide(RecordFinding(summary="   "), opened())


def test_a_gap_records_what_was_looked_for_and_what_was_tried() -> None:
    """The twin of a finding. A run that searched five ways and found nothing
    otherwise leaves only the free text "nothing recorded", which every later
    run has to re-derive the absence from."""
    state = opened()

    events = decide(
        RecordGap(
            looking_for="a critique of backward design",
            tried=["backward design critique", "wiggins mctighe criticism"],
        ),
        state,
    )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, TopicGapRecorded)
    assert event.looking_for == "a critique of backward design"
    assert event.tried == ["backward design critique", "wiggins mctighe criticism"]


def test_a_gap_with_nothing_tried_is_refused() -> None:
    """A gap with an empty `tried` is indistinguishable from never having
    looked, which is the exact confusion this event exists to remove."""
    state = opened()

    with pytest.raises(CommandRejectedError, match="tried"):
        decide(RecordGap(looking_for="a critique", tried=[]), state)


def test_a_gap_with_only_blank_entries_in_tried_is_refused() -> None:
    """`tried=["  "]` names nothing attempted, same as `tried=[]` -- but would
    pass a naive `if not tried:` check, since the list itself is non-empty.
    This is the regression the blank-filtering guards against: simplify the
    check to a length test and this test fails while the one above still
    passes."""
    state = opened()

    with pytest.raises(CommandRejectedError, match="tried"):
        decide(RecordGap(looking_for="a critique", tried=["  ", ""]), state)


def test_a_gap_with_nothing_looked_for_is_refused() -> None:
    state = opened()

    with pytest.raises(CommandRejectedError):
        decide(RecordGap(looking_for="  ", tried=["something"]), state)


def test_a_recorded_gap_counts_but_changes_nothing_else() -> None:
    """Specifically: it does not change status. A run that could mark its own
    questions unanswerable could empty its queue without answering anything,
    which is what `TopicPort` having no `close_topic` exists to prevent."""
    state = opened()

    after = evolve(
        state, TopicGapRecorded(aggregate_id=state.topic_id, looking_for="x", tried=["y"])
    )

    assert after.gaps == state.gaps + 1
    assert after.status == state.status
    assert after.findings == state.findings
    assert after.sub_questions == state.sub_questions


# ---------------- contests ----------------


def test_a_contest_is_recorded_and_resolved_with_a_justification():
    state = run(
        opened(),
        RecordContest(key="threshold", nature="24h vs 48h", source_ids=["s1", "s2"]),
    )
    assert state.unresolved_contests == ["threshold"]

    state = run(
        state,
        ResolveContest(
            key="threshold",
            resolution="both, under different tiers",
            justification="tier 1 is 24h; the SMEs each assumed their own tier",
        ),
    )
    assert state.unresolved_contests == []


def test_resolving_a_contest_requires_a_justification():
    state = run(opened(), RecordContest(key="k", nature="a vs b"))
    with pytest.raises(CommandRejectedError, match="justification"):
        decide(ResolveContest(key="k", resolution="a", justification=""), state)


def test_an_unknown_contest_cannot_be_resolved():
    with pytest.raises(CommandRejectedError, match="unknown contest"):
        decide(ResolveContest(key="ghost", resolution="x", justification="y"), opened())


# ---------------- status ----------------


def test_status_changes_need_a_justification():
    with pytest.raises(CommandRejectedError, match="justification"):
        decide(SetTopicStatus(to_status="answered", justification=""), opened())


def test_a_closed_topic_is_no_longer_live():
    state = run(
        opened(),
        SetTopicStatus(to_status="not_pursuing", justification="out of scope for this course"),
    )

    assert state.status == "not_pursuing"
    assert not state.is_live


def test_setting_the_status_it_already_has_is_refused():
    state = run(opened(), SetTopicStatus(to_status="answered", justification="done"))
    with pytest.raises(CommandRejectedError, match="already answered"):
        decide(SetTopicStatus(to_status="answered", justification="again"), state)


# ---------------- acknowledgements ----------------


def test_an_acknowledgement_requires_a_reason_and_an_expiry():
    """A silenced alarm with no end is one nobody remembers silencing."""
    with pytest.raises(CommandRejectedError, match="reason"):
        decide(
            AcknowledgeTrigger(trigger="topic.new_material", reason="", until_position="p9"),
            opened(),
        )
    with pytest.raises(CommandRejectedError, match="expiry"):
        decide(
            AcknowledgeTrigger(
                trigger="topic.new_material", reason="known", until_position=""
            ),
            opened(),
        )


def test_an_acknowledgement_is_recorded_against_its_trigger():
    state = run(
        opened(),
        AcknowledgeTrigger(
            trigger="topic.new_material", reason="bulk import, reviewed", until_position="p9"
        ),
    )

    assert state.acknowledgements["topic.new_material"].until_position == "p9"


# ---------------- the aggregate ----------------


def test_evolve_ignores_events_it_has_no_branch_for():
    """A stream carrying an event this build does not know must still replay.

    Exercised with a genuinely foreign event rather than a synthetic one: the
    store is shared, so a corpus event really can reach a fold that has no
    branch for it, and leaving the state alone is what keeps that from failing
    a replay halfway through.
    """
    state = opened()

    foreign = SourceDocumentStored(
        aggregate_id=uuid4(), source_id="s1", text="hello", sha256="abc"
    )

    assert evolve(state, foreign) is state


def test_the_aggregate_refuses_a_command_aimed_at_a_different_topic():
    """`ChecksCommandTarget`, applied to the one command that carries an id."""
    topic = Topic(uuid4())

    with pytest.raises(CommandRejectedError, match="targets"):
        topic.execute(
            OpenTopic(topic_id=uuid4(), project_id=uuid4(), question="q?", rationale="r")
        )


def test_the_aggregate_folds_its_own_events():
    topic = Topic(uuid4())
    topic.execute(
        OpenTopic(
            topic_id=topic.aggregate_id,
            project_id=uuid4(),
            question="q?",
            rationale="r",
        )
    )
    topic.execute(LinkSource(source_id="s1"))

    assert topic.state.status == "open"
    assert topic.state.source_ids == ["s1"]

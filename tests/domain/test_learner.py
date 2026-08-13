"""One learner's progress through a course's components.

Three things this aggregate is responsible for, and nearly every test is an
instance of one:

**An attempt is a fact, and facts accumulate.** Answering the same item three
times produces three attempts, not one item in a final state. The count and the
sequence are the pedagogically interesting part -- an item that took three goes
is a different observation from one that landed first time, and a design that
overwrites cannot tell them apart.

**Having once been right is not undone by later being wrong.** `correct` is
sticky and `best_score` is a maximum, because a learner revisiting a completed
item to check something should not lose the completion.

**A rewrite is recorded, never resolved.** The digest of the body each attempt
was made against is stored, and the aggregate does not act on it. Whether a
reworded question invalidates an earlier attempt is a pedagogical call.
"""

from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain.learner import (
    LearnerChecklistRecorded,
    LearnerItemAnswered,
    LearnerItemCompleted,
    RecordAttempt,
    RecordChecklistState,
    decide,
    evolve,
    initial_state,
)


def _attempt(progress_id, *, correct=False, score=0.0, digest="d1", **kwargs):
    return RecordAttempt(
        progress_id=progress_id,
        path=kwargs.pop("path", "/lesson.md"),
        component_id=kwargs.pop("component_id", "sev-1"),
        component_type=kwargs.pop("component_type", "mcq"),
        digest=digest,
        correct=correct,
        score=score,
        **kwargs,
    )


def _with(*events):
    state = initial_state()
    for event in events:
        state = evolve(state, event)
    return state


def _apply(command, state):
    events = decide(command, state)
    for event in events:
        state = evolve(state, event)
    return events, state


# --- recording an attempt ---------------------------------------------------


def test_an_attempt_is_recorded_with_its_verdict():
    progress_id = uuid4()

    events = decide(
        _attempt(progress_id, correct=True, score=1.0, response=[1], at=7), initial_state()
    )

    answered = events[0]
    assert isinstance(answered, LearnerItemAnswered)
    assert answered.aggregate_id == progress_id
    assert answered.path == "/lesson.md"
    assert answered.component_id == "sev-1"
    assert answered.response == [1]
    assert answered.correct is True
    assert answered.score == 1.0
    # The moment the file was graded against, so the verdict stays checkable
    # after the question is revised.
    assert answered.at == 7


def test_the_first_attempt_creates_the_stream():
    """No creation event: progress has no attributes of its own, so one would
    be an empty payload whose only effect is to make the first attempt fail."""
    progress_id = uuid4()

    assert initial_state().status == "new"
    _, state = _apply(_attempt(progress_id), initial_state())

    assert state.status == "created"
    assert state.progress_id == progress_id


def test_three_attempts_at_one_item_are_three_attempts():
    progress_id = uuid4()
    state = initial_state()

    for _ in range(3):
        _, state = _apply(_attempt(progress_id, score=0.5), state)

    record = state.item("/lesson.md", "sev-1")
    assert record.attempts == 3
    # Still one item. The sequence lives in the log; the fold counts.
    assert len(state.items) == 1


def test_two_items_are_tracked_separately():
    progress_id = uuid4()
    state = initial_state()

    _, state = _apply(_attempt(progress_id, component_id="sev-1"), state)
    _, state = _apply(_attempt(progress_id, component_id="sev-2"), state)

    assert len(state.items) == 2
    assert state.item("/lesson.md", "sev-1").attempts == 1
    assert state.item("/lesson.md", "sev-2").attempts == 1


def test_the_same_id_in_two_files_is_two_items():
    """Identity is `(path, component_id)`. Ids are only unique within a
    document -- `derive_id` numbers by position -- so keying on the id alone
    would merge two unrelated questions the moment a course had two lessons."""
    progress_id = uuid4()
    state = initial_state()

    _, state = _apply(_attempt(progress_id, path="/one.md"), state)
    _, state = _apply(_attempt(progress_id, path="/two.md"), state)

    assert len(state.items) == 2


# --- completion -------------------------------------------------------------


def test_a_correct_answer_completes_the_item():
    progress_id = uuid4()

    events = decide(_attempt(progress_id, correct=True, score=1.0), initial_state())

    assert isinstance(events[0], LearnerItemAnswered)
    completed = events[1]
    assert isinstance(completed, LearnerItemCompleted)
    assert completed.attempts == 1


def test_completion_says_how_many_tries_it_took():
    progress_id = uuid4()
    state = initial_state()

    _, state = _apply(_attempt(progress_id, correct=False), state)
    _, state = _apply(_attempt(progress_id, correct=False), state)
    events, state = _apply(_attempt(progress_id, correct=True, score=1.0), state)

    completed = next(e for e in events if isinstance(e, LearnerItemCompleted))
    assert completed.attempts == 3


def test_a_wrong_answer_completes_nothing():
    progress_id = uuid4()

    events = decide(_attempt(progress_id, correct=False, score=0.5), initial_state())

    assert len(events) == 1
    assert isinstance(events[0], LearnerItemAnswered)


def test_an_item_is_completed_once_however_often_it_is_answered_again():
    """ "When did this land" is a different question from "how many times was it
    tried", and a completion re-emitted on every later correct answer would
    answer the first question with the last date."""
    progress_id = uuid4()
    state = initial_state()

    _, state = _apply(_attempt(progress_id, correct=True, score=1.0), state)
    events, state = _apply(_attempt(progress_id, correct=True, score=1.0), state)

    assert not any(isinstance(e, LearnerItemCompleted) for e in events)


def test_being_wrong_later_does_not_undo_having_been_right():
    progress_id = uuid4()
    state = initial_state()

    _, state = _apply(_attempt(progress_id, correct=True, score=1.0), state)
    _, state = _apply(_attempt(progress_id, correct=False, score=0.25), state)

    record = state.item("/lesson.md", "sev-1")
    assert record.correct is True
    assert record.best_score == 1.0
    # The most recent verdict is still visible; it just is not the whole story.
    assert record.last_score == 0.25
    assert record.attempts == 2


def test_completing_an_item_the_second_time_round_still_marks_it_correct():
    progress_id = uuid4()
    state = initial_state()

    _, state = _apply(_attempt(progress_id, correct=False, score=0.0), state)
    assert state.item("/lesson.md", "sev-1").correct is False

    _, state = _apply(_attempt(progress_id, correct=True, score=1.0), state)
    assert state.item("/lesson.md", "sev-1").correct is True


# --- a rewritten item -------------------------------------------------------


def test_the_body_an_attempt_was_made_against_is_recorded():
    """Nothing survives an author rewriting an item under the same id, so the
    digest is stored rather than the fact being lost. What to *do* about a
    changed digest is a pedagogical call this aggregate does not make."""
    progress_id = uuid4()
    state = initial_state()

    _, state = _apply(_attempt(progress_id, digest="before"), state)
    assert state.item("/lesson.md", "sev-1").last_digest == "before"

    _, state = _apply(_attempt(progress_id, digest="after"), state)
    record = state.item("/lesson.md", "sev-1")
    assert record.last_digest == "after"
    # Not reset. The learner's history is intact and the change is visible.
    assert record.attempts == 2


# --- checklists -------------------------------------------------------------


def test_checklist_state_is_remembered():
    """`persist: true` used to be accepted and ignored."""
    progress_id = uuid4()

    [event] = decide(
        RecordChecklistState(
            progress_id=progress_id,
            path="/runbook.md",
            component_id="triage",
            checked=[2, 0],
        ),
        initial_state(),
    )

    assert isinstance(event, LearnerChecklistRecorded)
    # Canonical: two clients reporting the same boxes in a different order must
    # not read as two different states.
    assert event.checked == [0, 2]


def test_checklist_state_replaces_rather_than_accumulates():
    progress_id = uuid4()
    state = initial_state()

    _, state = _apply(
        RecordChecklistState(
            progress_id=progress_id, path="/r.md", component_id="t", checked=[0, 1, 2]
        ),
        state,
    )
    _, state = _apply(
        RecordChecklistState(
            progress_id=progress_id, path="/r.md", component_id="t", checked=[1]
        ),
        state,
    )

    # Unticking is a thing a person does, and a delta-shaped event could not
    # express it without the fold being right about every event ever dropped.
    assert state.item("/r.md", "t").checked == [1]


def test_a_repeated_box_is_recorded_once():
    progress_id = uuid4()

    [event] = decide(
        RecordChecklistState(
            progress_id=progress_id, path="/r.md", component_id="t", checked=[1, 1, 1]
        ),
        initial_state(),
    )

    assert event.checked == [1]


def test_a_checklist_can_be_the_first_thing_a_learner_does():
    progress_id = uuid4()

    _, state = _apply(
        RecordChecklistState(
            progress_id=progress_id, path="/r.md", component_id="t", checked=[0]
        ),
        initial_state(),
    )

    assert state.status == "created"
    assert state.progress_id == progress_id


def test_a_negative_box_index_is_refused():
    with pytest.raises(CommandRejectedError):
        decide(
            RecordChecklistState(
                progress_id=uuid4(), path="/r.md", component_id="t", checked=[-1]
            ),
            initial_state(),
        )


# --- refusals ---------------------------------------------------------------


@pytest.mark.parametrize("path,component_id", [("", "x"), ("/a.md", "")])
def test_an_attempt_without_an_address_is_refused(path, component_id):
    """An attempt nothing can be attributed to is not progress, it is noise --
    and it would sit in the log forever looking like a real record."""
    with pytest.raises(CommandRejectedError):
        decide(
            RecordAttempt(
                progress_id=uuid4(),
                path=path,
                component_id=component_id,
                component_type="mcq",
                digest="d",
            ),
            initial_state(),
        )


# --- replay -----------------------------------------------------------------


def test_an_unknown_event_leaves_the_state_alone():
    """A stream carrying an event this build does not know about still replays
    instead of failing halfway through."""
    from research_team.domain.events import TurnCompleted

    state = _with(
        LearnerItemAnswered(
            aggregate_id=uuid4(),
            path="/a.md",
            component_id="x",
            component_type="mcq",
            digest="d",
            correct=True,
            score=1.0,
        )
    )

    after = evolve(state, TurnCompleted(aggregate_id=uuid4(), turn_index=1))
    assert after == state


def test_completion_folds_to_nothing_because_the_attempt_already_said_it():
    """Two sources for one fact is how they come to disagree."""
    progress_id = uuid4()
    answered = LearnerItemAnswered(
        aggregate_id=progress_id,
        path="/a.md",
        component_id="x",
        component_type="mcq",
        digest="d",
        correct=True,
        score=1.0,
    )
    completed = LearnerItemCompleted(
        aggregate_id=progress_id, path="/a.md", component_id="x", attempts=1
    )

    assert _with(answered, completed) == _with(answered)

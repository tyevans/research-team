"""What a course-authoring run's stream will and will not accept.

The rules here are all about *ordering*, because that is the only thing this
aggregate can get wrong on its own: it holds no arithmetic and no policy. What
it holds is the guarantee that a run's account of itself cannot contradict
itself -- a course recorded after the run settled would mean a session id
exists that the run's own status says was never authored, and the projection
would happily write both.
"""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain import UserMessageSent
from research_team.domain.course_authoring_run import (
    CourseAuthored,
    CourseAuthoringRunSettled,
    RecordAuthoredCourse,
    RecordAuthoringFailure,
    SettleCourseAuthoringRun,
    StartCourseAuthoringRun,
    decide,
    evolve,
    initial_state,
)

RUN = uuid4()
PROJECT = uuid4()


def _started():
    """A run in flight over three targets."""
    event = decide(
        StartCourseAuthoringRun(
            run_id=RUN,
            project_id=PROJECT,
            kind="path",
            targets=("rome", "carthage", "complete"),
            started_at=datetime(2026, 8, 22, tzinfo=UTC),
        ),
        initial_state(),
    )[0]
    return evolve(initial_state(), event)


def test_a_run_records_its_targets_before_any_of_them_happen():
    """`targets` is on the start event, not derived from what followed.

    The difference between the list and the outcome is the answer a reader
    wants: a run that settled with four of nine is only legible if the nine
    were written down first.
    """
    state = _started()

    assert state.status == "running"
    assert state.targets == ["rome", "carthage", "complete"]
    assert state.authored == []


def test_an_authored_course_carries_the_session_that_holds_it():
    """The one fact nothing else on the log records."""
    session_id = uuid4()

    event = decide(RecordAuthoredCourse(RUN, "rome", session_id), _started())[0]

    assert isinstance(event, CourseAuthored)
    assert event.target == "rome"
    assert event.session_id == session_id
    assert evolve(_started(), event).authored == [("rome", session_id)]


def test_the_fold_pairs_a_target_with_its_session_rather_than_keeping_two_lists():
    """A mismatch is unrepresentable here, not merely unlikely.

    The wire frame carries `completed` and `sessions` as parallel arrays and
    `courseLinks` in the browser has to defend against them disagreeing. This
    asserts the *source* of those arrays cannot produce the disagreement.
    """
    first, second = uuid4(), uuid4()
    state = _started()
    for target, session_id in (("rome", first), ("carthage", second)):
        state = evolve(state, decide(RecordAuthoredCourse(RUN, target, session_id), state)[0])

    assert state.authored == [("rome", first), ("carthage", second)]


@pytest.mark.parametrize("status", ["done", "failed", "cancelled"])
def test_a_run_can_settle_as_each_of_the_three_endings(status):
    """`cancelled` is a first-class ending, not a flavour of `failed`.

    Both leave a partial set of courses behind, and a reader that cannot tell
    a person pressing stop from the work breaking misreads every one of them.
    """
    event = decide(
        SettleCourseAuthoringRun(RUN, status, datetime(2026, 8, 22, tzinfo=UTC)), _started()
    )[0]

    assert isinstance(event, CourseAuthoringRunSettled)
    assert evolve(_started(), event).status == status


@pytest.mark.parametrize(
    "command",
    [
        RecordAuthoredCourse(RUN, "rome", uuid4()),
        RecordAuthoringFailure(RUN, "rome", "the model refused"),
        SettleCourseAuthoringRun(RUN, "done", datetime(2026, 8, 22, tzinfo=UTC)),
    ],
    ids=["authored", "failed", "settle"],
)
def test_nothing_is_recorded_against_a_run_that_never_started(command):
    state = initial_state()

    with pytest.raises(CommandRejectedError):
        decide(command, state)


@pytest.mark.parametrize(
    "command",
    [
        RecordAuthoredCourse(RUN, "carthage", uuid4()),
        RecordAuthoringFailure(RUN, "carthage", "too late"),
        SettleCourseAuthoringRun(RUN, "cancelled", datetime(2026, 8, 22, tzinfo=UTC)),
    ],
    ids=["authored", "failed", "settle-again"],
)
def test_a_settled_run_is_a_closed_account(command):
    """Nothing is appended after the settle, including a second settle.

    The second settle is the one with a live caller: `cancel` and the driving
    loop are two paths to the same run, and if `cancel` appended the
    cancellation itself they would race. It does not -- the loop settles on its
    way out -- and this is what would fail if that ever changed.
    """
    state = _started()
    state = evolve(
        state,
        decide(
            SettleCourseAuthoringRun(RUN, "done", datetime(2026, 8, 22, tzinfo=UTC)), state
        )[0],
    )

    with pytest.raises(CommandRejectedError):
        decide(command, state)


def test_a_run_cannot_be_started_twice():
    with pytest.raises(CommandRejectedError):
        decide(
            StartCourseAuthoringRun(
                run_id=RUN,
                project_id=PROJECT,
                kind="path",
                targets=("rome",),
                started_at=datetime(2026, 8, 22, tzinfo=UTC),
            ),
            _started(),
        )


def test_the_fold_ignores_an_event_from_another_aggregate():
    """Total, like every other fold in the domain.

    A `Session` event reaching this fold is not a state it has to have an
    opinion about -- returning the state unchanged is what lets a replay walk
    a store shared with sessions, the corpus and redstring's documents without
    a branch per foreign type.
    """
    state = _started()

    unrelated = UserMessageSent(
        aggregate_id=uuid4(), message={"role": "user", "content": "hi"}
    )

    assert evolve(state, unrelated) == state

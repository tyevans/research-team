from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain.project import (
    AdvanceTip,
    CreateProject,
    DeleteProject,
    JoinProject,
    ProjectCreated,
    ProjectDeleted,
    ProjectSessionJoined,
    ProjectTipAdvanced,
    decide,
    evolve,
    initial_state,
)


def test_creating_a_project_emits_project_created():
    project_id = uuid4()
    state = initial_state()

    [event] = decide(CreateProject(project_id=project_id, name="research"), state)

    assert isinstance(event, ProjectCreated)
    assert event.aggregate_id == project_id
    assert event.name == "research"


def test_a_project_cannot_be_created_twice():
    project_id = uuid4()
    state = evolve(initial_state(), ProjectCreated(aggregate_id=project_id, name="research"))

    with pytest.raises(CommandRejectedError, match="already created"):
        decide(CreateProject(project_id=project_id, name="research"), state)


def test_commands_before_creation_are_rejected():
    state = initial_state()

    with pytest.raises(CommandRejectedError, match="not created"):
        decide(JoinProject(session_id=uuid4()), state)


def test_a_session_joins_and_inherits_the_current_tip():
    project_id, first, second = uuid4(), uuid4(), uuid4()
    state = initial_state()
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        ProjectSessionJoined(aggregate_id=project_id, session_id=first, inherited_at=0),
        ProjectTipAdvanced(aggregate_id=project_id, session_id=first, at_event=12),
    ):
        state = evolve(state, event)

    [event] = decide(JoinProject(session_id=second), state)

    assert isinstance(event, ProjectSessionJoined)
    assert event.aggregate_id == project_id
    assert event.session_id == second
    assert event.inherited_at == 12


def test_a_second_concurrent_session_is_rejected_by_name():
    project_id, holder = uuid4(), uuid4()
    state = initial_state()
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        ProjectSessionJoined(aggregate_id=project_id, session_id=holder, inherited_at=0),
    ):
        state = evolve(state, event)

    with pytest.raises(CommandRejectedError, match=str(holder)):
        decide(JoinProject(session_id=uuid4()), state)


def test_advancing_the_tip_releases_the_project():
    project_id, session_id = uuid4(), uuid4()
    state = initial_state()
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        ProjectSessionJoined(aggregate_id=project_id, session_id=session_id, inherited_at=0),
        ProjectTipAdvanced(aggregate_id=project_id, session_id=session_id, at_event=7),
    ):
        state = evolve(state, event)

    assert state.active_session_id is None
    assert state.tip_session_id == session_id
    assert state.tip_at_event == 7


def test_only_the_active_session_may_advance_the_tip():
    project_id, holder = uuid4(), uuid4()
    state = initial_state()
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        ProjectSessionJoined(aggregate_id=project_id, session_id=holder, inherited_at=0),
    ):
        state = evolve(state, event)

    with pytest.raises(CommandRejectedError, match="does not hold"):
        decide(AdvanceTip(session_id=uuid4(), at_event=3), state)


def _created(project_id, name="research"):
    return evolve(initial_state(), ProjectCreated(aggregate_id=project_id, name=name))


def test_deleting_a_free_project_emits_project_deleted():
    project_id = uuid4()

    events = decide(DeleteProject(), _created(project_id))

    assert [type(e) for e in events] == [ProjectDeleted]
    assert events[0].aggregate_id == project_id


def test_a_deleted_project_keeps_what_it_was():
    """A tombstone, not an erasure: the history is still the truth."""
    project_id, session_id = uuid4(), uuid4()
    state = _created(project_id, name="atlas")
    for event in (
        ProjectSessionJoined(aggregate_id=project_id, session_id=session_id, inherited_at=0),
        ProjectTipAdvanced(aggregate_id=project_id, session_id=session_id, at_event=4),
        ProjectDeleted(aggregate_id=project_id),
    ):
        state = evolve(state, event)

    assert state.status == "deleted"
    assert state.name == "atlas"
    assert state.member_session_ids == [session_id]
    assert state.tip_session_id == session_id
    assert state.tip_at_event == 4


def test_a_held_project_cannot_be_deleted_until_it_is_released():
    project_id, holder = uuid4(), uuid4()
    state = evolve(
        _created(project_id),
        ProjectSessionJoined(aggregate_id=project_id, session_id=holder, inherited_at=0),
    )

    with pytest.raises(CommandRejectedError, match=str(holder)):
        decide(DeleteProject(), state)


def test_a_deleted_project_refuses_everything_afterwards():
    project_id = uuid4()
    state = evolve(_created(project_id), ProjectDeleted(aggregate_id=project_id))

    with pytest.raises(CommandRejectedError, match="already deleted"):
        decide(DeleteProject(), state)
    # The one that matters: a join would hand out a lineage nothing maintains.
    with pytest.raises(CommandRejectedError, match="has been deleted"):
        decide(JoinProject(session_id=uuid4()), state)
    with pytest.raises(CommandRejectedError, match="has been deleted"):
        decide(AdvanceTip(session_id=uuid4(), at_event=1), state)


def test_evolve_ignores_unknown_events():
    project_id = uuid4()
    state = evolve(initial_state(), ProjectCreated(aggregate_id=project_id, name="r"))

    assert evolve(state, ProjectCreated(aggregate_id=project_id, name="other")) is not None


# --- catching a tip up after its session was released -------------------------


def _released(project_id, session_id, at):
    """A project whose tip names `session_id` at `at`, held by nobody."""
    state = initial_state()
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        ProjectSessionJoined(aggregate_id=project_id, session_id=session_id, inherited_at=0),
        ProjectTipAdvanced(aggregate_id=project_id, session_id=session_id, at_event=at),
    ):
        state = evolve(state, event)
    return state


def test_the_tip_session_may_move_the_tip_further_along_its_own_stream():
    """Releasing does not close a session, so work continues past the release.

    Without this arm that work is unreachable: the tip names the right stream
    and a point before it. Fails with the change reverted on the rejection
    `only_the_active_session_may_advance_the_tip` used to cover every case of.
    """
    project_id, session_id = uuid4(), uuid4()

    events = decide(
        AdvanceTip(session_id=session_id, at_event=12), _released(project_id, session_id, 7)
    )

    assert [type(e) for e in events] == [ProjectTipAdvanced]
    assert events[0].at_event == 12


def test_the_tip_may_not_move_backwards():
    """Backwards is not a catch-up. It is a decision about which work counts,
    and no caller means it -- a release passes `session.version`, which only
    grows, and a catch-up passes the stream length, which only grows.

    Passes with the change reverted, which is the point: this and the two
    below are the fence around the new arm, not evidence of it. They fail on
    a relaxation written one condition too wide, which is the likeliest way to
    get this wrong.
    """
    project_id, session_id = uuid4(), uuid4()

    with pytest.raises(CommandRejectedError, match="does not hold"):
        decide(
            AdvanceTip(session_id=session_id, at_event=3), _released(project_id, session_id, 7)
        )


def test_a_session_that_is_not_the_tip_may_not_catch_it_up():
    """The relaxation is for the stream the project is already pointing at.

    A stranger claiming the tip would repoint the project's whole filesystem at
    a stream it never adopted, which is the failure the original holder check
    was there to prevent and which is unchanged.
    """
    project_id, session_id = uuid4(), uuid4()

    with pytest.raises(CommandRejectedError, match="does not hold"):
        decide(
            AdvanceTip(session_id=uuid4(), at_event=12), _released(project_id, session_id, 7)
        )


def test_a_held_project_refuses_a_catch_up_from_the_old_tip():
    """Once somebody has forked from the tip, the old session's later work is a
    real divergence rather than a continuation, and moving the tip to it would
    discard the holder's inheritance. Whoever holds it is the only writer."""
    project_id, old_tip, holder = uuid4(), uuid4(), uuid4()
    state = evolve(
        _released(project_id, old_tip, 7),
        ProjectSessionJoined(aggregate_id=project_id, session_id=holder, inherited_at=7),
    )

    with pytest.raises(CommandRejectedError, match="does not hold"):
        decide(AdvanceTip(session_id=old_tip, at_event=12), state)

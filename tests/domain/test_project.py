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
    ProjectTipAdvanced,
    SessionJoinedProject,
    decide,
    evolve,
    initial_state,
)


def test_creating_a_project_emits_project_created():
    project_id = uuid4()
    state = initial_state(project_id)

    [event] = decide(CreateProject(name="research"), state)

    assert isinstance(event, ProjectCreated)
    assert event.aggregate_id == project_id
    assert event.name == "research"


def test_a_project_cannot_be_created_twice():
    project_id = uuid4()
    state = evolve(
        initial_state(project_id), ProjectCreated(aggregate_id=project_id, name="research")
    )

    with pytest.raises(CommandRejectedError, match="already created"):
        decide(CreateProject(name="research"), state)


def test_commands_before_creation_are_rejected():
    state = initial_state(uuid4())

    with pytest.raises(CommandRejectedError, match="not created"):
        decide(JoinProject(session_id=uuid4()), state)


def test_a_session_joins_and_inherits_the_current_tip():
    project_id, first, second = uuid4(), uuid4(), uuid4()
    state = initial_state(project_id)
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        SessionJoinedProject(aggregate_id=project_id, session_id=first, inherited_at=0),
        ProjectTipAdvanced(aggregate_id=project_id, session_id=first, at_event=12),
    ):
        state = evolve(state, event)

    [event] = decide(JoinProject(session_id=second), state)

    assert isinstance(event, SessionJoinedProject)
    assert event.aggregate_id == project_id
    assert event.session_id == second
    assert event.inherited_at == 12


def test_a_second_concurrent_session_is_rejected_by_name():
    project_id, holder = uuid4(), uuid4()
    state = initial_state(project_id)
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        SessionJoinedProject(aggregate_id=project_id, session_id=holder, inherited_at=0),
    ):
        state = evolve(state, event)

    with pytest.raises(CommandRejectedError, match=str(holder)):
        decide(JoinProject(session_id=uuid4()), state)


def test_advancing_the_tip_releases_the_project():
    project_id, session_id = uuid4(), uuid4()
    state = initial_state(project_id)
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        SessionJoinedProject(aggregate_id=project_id, session_id=session_id, inherited_at=0),
        ProjectTipAdvanced(aggregate_id=project_id, session_id=session_id, at_event=7),
    ):
        state = evolve(state, event)

    assert state.active_session_id is None
    assert state.tip_session_id == session_id
    assert state.tip_at_event == 7


def test_only_the_active_session_may_advance_the_tip():
    project_id, holder = uuid4(), uuid4()
    state = initial_state(project_id)
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        SessionJoinedProject(aggregate_id=project_id, session_id=holder, inherited_at=0),
    ):
        state = evolve(state, event)

    with pytest.raises(CommandRejectedError, match="does not hold"):
        decide(AdvanceTip(session_id=uuid4(), at_event=3), state)


def _created(project_id, name="research"):
    return evolve(
        initial_state(project_id), ProjectCreated(aggregate_id=project_id, name=name)
    )


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
        SessionJoinedProject(aggregate_id=project_id, session_id=session_id, inherited_at=0),
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
        SessionJoinedProject(aggregate_id=project_id, session_id=holder, inherited_at=0),
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
    state = evolve(
        initial_state(project_id), ProjectCreated(aggregate_id=project_id, name="r")
    )

    assert evolve(state, ProjectCreated(aggregate_id=project_id, name="other")) is not None

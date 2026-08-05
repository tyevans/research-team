import pytest
from uuid import uuid4

from research_team.domain.project import (
    AdvanceTip,
    CreateProject,
    JoinProject,
    ProjectCreated,
    ProjectState,
    ProjectTipAdvanced,
    SessionJoinedProject,
    decide,
    evolve,
    initial_state,
)
from eventsource import CommandRejectedError


def test_creating_a_project_emits_project_created():
    project_id = uuid4()
    state = initial_state(project_id)

    [event] = decide(CreateProject(name="research"), state)

    assert isinstance(event, ProjectCreated)
    assert event.aggregate_id == project_id
    assert event.name == "research"


def test_a_project_cannot_be_created_twice():
    project_id = uuid4()
    state = evolve(initial_state(project_id), ProjectCreated(aggregate_id=project_id, name="research"))

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


def test_evolve_ignores_unknown_events():
    project_id = uuid4()
    state = evolve(initial_state(project_id), ProjectCreated(aggregate_id=project_id, name="r"))

    assert evolve(state, ProjectCreated(aggregate_id=project_id, name="other")) is not None

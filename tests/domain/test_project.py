import re
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain.project import (
    AdvanceStage,
    AdvanceTip,
    CreateProject,
    DeleteProject,
    JoinProject,
    ProjectCreated,
    ProjectDeleted,
    ProjectSessionJoined,
    ProjectStageAdvanced,
    ProjectTipAdvanced,
    ProjectWorkflowSelected,
    SelectWorkflow,
    current_stage_of,
    decide,
    evolve,
    initial_state,
)
from research_team.workflows import hybrid_default, ubd_pure


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


# --- workflows ---------------------------------------------------------------
#
# Stage lives on `Project` rather than on a session because a run outspans any
# one session: `start_in_project` forks the filesystem from the project tip and
# deliberately does not carry the conversation, so a session-scoped record of
# stage would be lost at exactly the moment a run continues. Real presets are
# used throughout rather than fixtures -- `Preset` validates on construction
# and a minimal well-formed one is more code than importing a shipped one, and
# a rule that only holds against a toy preset is not worth having.


def _with_workflow(project_id, preset=hybrid_default):
    state = _created(project_id)
    return evolve(
        state,
        ProjectWorkflowSelected(
            aggregate_id=project_id, preset_id=preset.id, preset_version=preset.version
        ),
    )


def test_selecting_a_workflow_emits_workflow_selected():
    project_id = uuid4()

    [event] = decide(SelectWorkflow(preset=hybrid_default), _created(project_id))

    assert isinstance(event, ProjectWorkflowSelected)
    assert event.preset_id == "hybrid.default"
    assert event.preset_version == hybrid_default.version


def test_a_selected_workflow_leaves_the_project_at_the_presets_first_stage():
    project_id = uuid4()

    state = _with_workflow(project_id)

    assert state.preset_id == "hybrid.default"
    assert state.current_stage is None
    assert current_stage_of(state, hybrid_default).id == "tyler.step0.intake"


def test_selecting_a_second_workflow_is_rejected_naming_the_current_one():
    """The refusal names what the caller will ask about next, as `JoinProject` does."""
    state = _with_workflow(uuid4())

    with pytest.raises(CommandRejectedError, match=re.escape("hybrid.default")):
        decide(SelectWorkflow(preset=ubd_pure), state)


def test_advancing_moves_to_the_next_stage_in_the_preset():
    project_id = uuid4()
    state = _with_workflow(project_id)

    [event] = decide(
        AdvanceStage(
            preset=hybrid_default,
            to_stage="hybrid.step1.framing",
            decided_by="human",
            gate_decision="approve",
        ),
        state,
    )

    assert isinstance(event, ProjectStageAdvanced)
    assert event.from_stage == "tyler.step0.intake"
    assert event.to_stage == "hybrid.step1.framing"
    assert event.decided_by == "human"
    assert event.gate_decision == "approve"

    state = evolve(state, event)
    assert state.current_stage == "hybrid.step1.framing"
    assert state.stage_history == ["hybrid.step1.framing"]
    assert current_stage_of(state, hybrid_default).id == "hybrid.step1.framing"


def test_advancing_to_a_stage_the_preset_does_not_have_is_rejected():
    state = _with_workflow(uuid4())

    with pytest.raises(CommandRejectedError, match=re.escape("ubd.stage1.desired_results")):
        decide(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="ubd.stage1.desired_results",
                decided_by="human",
                gate_decision="approve",
            ),
            state,
        )


def test_advancing_out_of_order_is_rejected():
    """Skipping is the failure this whole aggregate exists to prevent."""
    state = _with_workflow(uuid4())

    with pytest.raises(CommandRejectedError, match=re.escape("hybrid.step1.framing")):
        decide(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="tyler.step1b.candidates",
                decided_by="human",
                gate_decision="approve",
            ),
            state,
        )


def test_advancing_backwards_is_rejected():
    project_id = uuid4()
    state = evolve(
        _with_workflow(project_id),
        ProjectStageAdvanced(
            aggregate_id=project_id,
            from_stage="tyler.step0.intake",
            to_stage="hybrid.step1.framing",
            decided_by="human",
            gate_decision="approve",
        ),
    )

    with pytest.raises(CommandRejectedError, match=re.escape("tyler.step0.intake")):
        decide(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="tyler.step0.intake",
                decided_by="human",
                gate_decision="approve",
            ),
            state,
        )


def test_advancing_past_the_final_stage_is_rejected():
    project_id = uuid4()
    state = _with_workflow(project_id)
    for earlier, later in zip(
        [stage.id for stage in hybrid_default.stages],
        [stage.id for stage in hybrid_default.stages[1:]],
        strict=False,
    ):
        state = evolve(
            state,
            ProjectStageAdvanced(
                aggregate_id=project_id,
                from_stage=earlier,
                to_stage=later,
                decided_by="human",
                gate_decision="approve",
            ),
        )

    assert state.current_stage == "hybrid.step10.outcomes"
    with pytest.raises(CommandRejectedError, match="final stage"):
        decide(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="anything",
                decided_by="human",
                gate_decision="approve",
            ),
            state,
        )


def test_advancing_before_a_workflow_is_selected_is_rejected():
    with pytest.raises(CommandRejectedError, match="no workflow"):
        decide(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="hybrid.step1.framing",
                decided_by="human",
                gate_decision="approve",
            ),
            _created(uuid4()),
        )


def test_advancing_against_a_different_preset_than_the_project_runs_is_rejected():
    """The command carries the preset, so the two can disagree; they must not.

    Validating order needs the stage list, and the domain will not reach for a
    registry to find it. That makes the caller's preset an input the aggregate
    has to check against its own record rather than trust.
    """
    state = _with_workflow(uuid4())

    with pytest.raises(CommandRejectedError, match=re.escape("ubd.pure")):
        decide(
            AdvanceStage(
                preset=ubd_pure,
                to_stage="ubd.step1.context",
                decided_by="human",
                gate_decision="approve",
            ),
            state,
        )


def test_a_deleted_project_refuses_workflow_commands_too():
    """The `status="deleted"` guard sits above everything; these inherit it free."""
    project_id = uuid4()
    state = evolve(_with_workflow(project_id), ProjectDeleted(aggregate_id=project_id))

    with pytest.raises(CommandRejectedError, match="has been deleted"):
        decide(SelectWorkflow(preset=hybrid_default), state)
    with pytest.raises(CommandRejectedError, match="has been deleted"):
        decide(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="hybrid.step1.framing",
                decided_by="human",
                gate_decision="approve",
            ),
            state,
        )


def test_workflow_commands_before_creation_are_rejected():
    with pytest.raises(CommandRejectedError, match="not created"):
        decide(SelectWorkflow(preset=hybrid_default), initial_state())


def test_a_project_with_no_workflow_has_no_current_stage():
    assert current_stage_of(_created(uuid4()), hybrid_default) is None


def test_selecting_a_workflow_keeps_everything_else_about_the_project():
    project_id, session_id = uuid4(), uuid4()
    state = evolve(
        _created(project_id, name="atlas"),
        ProjectSessionJoined(aggregate_id=project_id, session_id=session_id, inherited_at=0),
    )

    state = evolve(
        state,
        ProjectWorkflowSelected(
            aggregate_id=project_id, preset_id="hybrid.default", preset_version="1"
        ),
    )

    assert state.name == "atlas"
    assert state.active_session_id == session_id
    assert state.member_session_ids == [session_id]


def test_the_reviewers_verdict_is_recorded_beside_the_evidence():
    """`decision` is the human's verdict; `gate_decision` is what they were shown.

    Fails with the change reverted: `AdvanceStage` has no `decision` to pass
    and `ProjectStageAdvanced` no field to hold it, so this is a TypeError before it
    is an assertion.
    """
    state = _with_workflow(uuid4())

    [event] = decide(
        AdvanceStage(
            preset=hybrid_default,
            to_stage="hybrid.step1.framing",
            decided_by="human",
            gate_decision="4 of 4 declared artifacts present; no invariant failures",
            decision="approve_with_edits",
        ),
        state,
    )

    assert event.decision == "approve_with_edits"
    assert event.gate_decision.startswith("4 of 4")


def test_an_advance_with_no_stated_verdict_reads_as_an_approval():
    """Case 1 of the evolution strategy: absence means what it always meant.

    Every `ProjectStageAdvanced` written before this field existed was an advance a
    human let through, so `approve` is the only default that does not invent a
    verdict nobody gave.
    """
    [event] = decide(
        AdvanceStage(
            preset=hybrid_default,
            to_stage="hybrid.step1.framing",
            decided_by="human",
            gate_decision="looks right",
        ),
        _with_workflow(uuid4()),
    )

    assert event.decision == "approve"


@pytest.mark.parametrize("verdict", ["amend_upstream", "send_back", "halt"])
def test_the_three_decisions_that_are_not_advances_are_refused(verdict):
    """A verdict that means "do not advance" may not ride on an advance.

    `workflow-engine.md` §3.4 records that four of the five `Decision` values
    cannot be expressed; adding this field without this refusal would make
    three of them *appear* expressible, on an event whose only meaning is that
    the stage moved. A log saying a reviewer sent the work back, on the event
    recording that the work went forward, is worse than one that says nothing.
    """
    with pytest.raises(CommandRejectedError, match=re.escape(verdict)):
        decide(
            AdvanceStage(
                preset=hybrid_default,
                to_stage="hybrid.step1.framing",
                decided_by="human",
                gate_decision="",
                decision=verdict,
            ),
            _with_workflow(uuid4()),
        )


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

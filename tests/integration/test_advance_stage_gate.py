"""The gate itself: the tool bound, the human asked, the stage moved.

Everything this exercises was already covered somewhere -- the domain rules in
`tests/domain/test_project.py`, the floor in `tests/infrastructure/
test_workflow_tools.py`, the filter in `test_stage_middleware.py`. All of it
passed while `advance_stage` was never registered with any agent, because every
test that needed a stage change executed `AdvanceStage` against the aggregate
directly. Each part was proven and the join between them was not, which is the
shape of gap that survives a green suite.

So nothing here reaches past the model. A stage moves because a scripted model
asked for the tool, a policy floor turned that into an interrupt, and an
`ApprovalPort` answered -- the same path a person clicking approve travels.
"""

from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.application import ApprovalDecision, ApprovalRequest, AutonomyPolicy
from research_team.application.autonomy import ADVANCE_STAGE_TOOL
from research_team.domain import CreateProject, SelectWorkflow, ToolCallDecided
from research_team.workflows import hybrid_default
from tests.conftest import ToolAwareFakeChatModel

FRAMING = "hybrid.step1.framing"


class ToolRecordingChatModel(ToolAwareFakeChatModel):
    """Remembers what it was bound: the tools the model could actually call."""

    seen: list[list[str]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "ToolRecordingChatModel":
        self.seen.append([getattr(tool, "name", str(tool)) for tool in tools])
        return self

    @property
    def last_bound(self) -> set[str]:
        return set(self.seen[-1]) if self.seen else set()


class ScriptedApprovals:
    """An `ApprovalPort` that answers from a script and records what it was asked."""

    def __init__(self, *decisions: ApprovalDecision) -> None:
        self._decisions = list(decisions)
        self.seen: list[ApprovalRequest] = []

    async def decide(self, request: ApprovalRequest) -> ApprovalDecision:
        self.seen.append(request)
        return self._decisions.pop(0) if self._decisions else ApprovalDecision("approve")


def _quiet_model() -> ToolRecordingChatModel:
    return ToolRecordingChatModel(
        responses=[AIMessage(content="noted", id="a1"), AIMessage(content="noted", id="a2")]
    )


def _advancing_model(rationale: str = "the intake artifacts are written and cited"):
    """Asks to advance, then replies to whatever came back."""
    return ToolRecordingChatModel(
        responses=[
            AIMessage(
                content="",
                id="a1",
                tool_calls=[
                    {
                        "name": ADVANCE_STAGE_TOOL,
                        "args": {"rationale": rationale},
                        "id": "t1",
                    }
                ],
            ),
            AIMessage(content="acknowledged", id="a2"),
        ]
    )


async def _project(application, *, workflow: bool = True):
    project_id = uuid4()
    project = application.service.projects.create_new(project_id)
    project.execute(CreateProject(name="course"))
    if workflow:
        project.execute(SelectWorkflow(preset=hybrid_default))
    await application.service.projects.save(project)
    return project_id


async def _in_project(application, project_id):
    await application.attach_project(project_id)
    return await application.service.start_in_project(project_id)


async def _stage_of(application, project_id) -> str | None:
    return (await application.service.project_state(project_id)).current_stage


async def test_advance_stage_is_bound_when_a_workflow_is_selected(build_application):
    """The one assertion whose absence let the whole gate go unwired."""
    model = _quiet_model()
    application = await build_application(model=model)
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "hello")

    assert ADVANCE_STAGE_TOOL in model.last_bound


async def test_advance_stage_is_absent_without_a_workflow(build_application):
    """A project running no workflow has no stage boundary to cross."""
    model = _quiet_model()
    application = await build_application(model=model)
    project_id = await _project(application, workflow=False)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "hello")

    assert ADVANCE_STAGE_TOOL not in model.last_bound


async def test_advance_stage_survives_a_stage_that_claims_other_tools(build_application):
    """No stage may withdraw the gate, including stages that name a tool list.

    `hybrid.step1.framing` claims `list_sources` and `read_source` and nothing
    else. If the gate were filtered like an ordinary stage tool, a run would
    reach that stage and be unable to leave it -- wedged, with the model's only
    honest report being that it has no way forward.
    """
    model = _advancing_model()
    model.responses = [*model.responses, AIMessage(content="still here", id="a3")]
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    application = await build_application(model=model, approvals=approvals)
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    # Turn one runs in `tyler.step0.intake`, which claims all three read tools.
    await application.service.run_turn(session_id, "are we done here?")
    assert {ADVANCE_STAGE_TOOL, "graph_search"} <= model.last_bound

    # The approval moved the project on; turn two runs in framing, which does
    # not claim `graph_search` -- and must still be leavable.
    assert await _stage_of(application, project_id) == FRAMING
    await application.service.run_turn(session_id, "what now?")

    assert ADVANCE_STAGE_TOOL in model.last_bound
    assert "graph_search" not in model.last_bound


async def test_calling_advance_stage_interrupts_and_asks_a_human(build_application):
    """The fact the whole gate design rests on, and it was never asserted."""
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    application = await build_application(model=_advancing_model(), approvals=approvals)
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "are we done here?")

    assert [request.tool_name for request in approvals.seen] == [ADVANCE_STAGE_TOOL]
    assert approvals.seen[0].args["rationale"]


async def test_an_approved_advance_actually_moves_the_project(build_application):
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    application = await build_application(model=_advancing_model(), approvals=approvals)
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    assert await _stage_of(application, project_id) is None

    await application.service.run_turn(session_id, "are we done here?")

    assert await _stage_of(application, project_id) == FRAMING


async def test_a_rejected_advance_leaves_the_project_where_it_was(build_application):
    """A refusal has to be inert, or the gate is theatre."""
    approvals = ScriptedApprovals(ApprovalDecision("reject", message="not yet"))
    application = await build_application(model=_advancing_model(), approvals=approvals)
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "are we done here?")

    assert await _stage_of(application, project_id) is None


async def test_the_decision_is_recorded_on_the_session_log(build_application):
    """The audit trail the gate exists to produce, at the only place it survives."""
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    application = await build_application(model=_advancing_model(), approvals=approvals)
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "are we done here?")

    decisions = [
        event
        for event in await application.service.history(session_id)
        if isinstance(event, ToolCallDecided) and event.tool_name == ADVANCE_STAGE_TOOL
    ]
    assert [(event.decision, event.decided_by) for event in decisions] == [
        ("approve", "human")
    ]


async def test_without_an_approval_port_the_gate_refuses_rather_than_opens(
    build_application,
):
    """No human wired means no stage boundary crossed.

    `_decide` refuses a gated call when there is nobody to ask. That is the
    right direction for this tool specifically: a headless process advancing a
    workflow unattended is the failure the gate exists to prevent, and it would
    otherwise be the default for anyone who forgot to pass a port.
    """
    application = await build_application(model=_advancing_model())
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "are we done here?")

    assert await _stage_of(application, project_id) is None


async def test_a_denied_policy_keeps_the_gate_shut_even_with_a_port(build_application):
    approvals = ScriptedApprovals(ApprovalDecision("approve"))
    policy = AutonomyPolicy()
    policy.set(ADVANCE_STAGE_TOOL, "deny")
    application = await build_application(
        model=_advancing_model(), approvals=approvals, policy=policy
    )
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "are we done here?")

    assert approvals.seen == []
    assert await _stage_of(application, project_id) is None


async def test_a_preset_naming_the_gate_cannot_hide_it_from_the_other_stages(
    build_application, monkeypatch
):
    """The trap the exemption exists to disarm.

    `managed_tools_for` is the union of every stage's declared tools, and the
    middleware hides whatever is in that union and not in the current stage. No
    shipped preset names `advance_stage`, so today it falls outside the union
    and is visible everywhere by accident. The day one stage names it -- a
    plausible edit, since a `decide` stage is exactly where you would think to
    write it down -- it would join the union and vanish from every stage that
    did not, wedging the run. Subtracting it explicitly is what makes the
    current behaviour a decision instead of a coincidence.
    """
    from research_team import composition

    named = hybrid_default.stages[0].model_copy(
        update={"tools": (*hybrid_default.stages[0].tools, ADVANCE_STAGE_TOOL)}
    )
    mutated = hybrid_default.model_copy(update={"stages": (named, *hybrid_default.stages[1:])})
    monkeypatch.setattr(composition, "PRESETS", {mutated.id: mutated})

    model = _advancing_model()
    model.responses = [*model.responses, AIMessage(content="still here", id="a3")]
    application = await build_application(
        model=model, approvals=ScriptedApprovals(ApprovalDecision("approve"))
    )
    project_id = await _project(application)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "are we done here?")
    assert await _stage_of(application, project_id) == FRAMING

    # Framing does not name the gate; the stage that does is behind us.
    await application.service.run_turn(session_id, "what now?")
    assert ADVANCE_STAGE_TOOL in model.last_bound


async def test_a_workflow_selected_after_the_project_was_attached_still_gets_the_tool(
    build_application,
):
    """Selection happens over HTTP on an already-attached project.

    `POST /api/projects/{id}/workflow` writes the event and returns; nothing
    re-attaches. If the tool were registered when the project attached, a
    project that chose its workflow through the UI -- which is every project --
    would run without a gate until something happened to re-attach it. That is
    why registration is resolved per turn rather than per attachment.
    """
    model = _quiet_model()
    application = await build_application(model=model)
    project_id = await _project(application, workflow=False)
    session_id = await _in_project(application, project_id)

    await application.service.run_turn(session_id, "hello")
    assert ADVANCE_STAGE_TOOL not in model.last_bound

    project = await application.service.projects.load(project_id)
    project.execute(SelectWorkflow(preset=hybrid_default))
    await application.service.projects.save(project)

    await application.service.run_turn(session_id, "hello again")
    assert ADVANCE_STAGE_TOOL in model.last_bound

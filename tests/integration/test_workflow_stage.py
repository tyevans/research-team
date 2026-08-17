"""A stage gate through the composed application, not through stubs.

Unit tests can prove `StageMiddleware` filters a list. They cannot prove the
composition root ever hands it one, that the fold reaches the right project, or
that the tools it withdraws were registered in the first place -- and every one
of those is a way stages break while the middleware's own tests stay green. So
these drive a fake model through a real `create_deep_agent`, and assert on what
the model was bound.

The project advances to `hybrid.step1.framing`, which claims `list_sources` and
`read_source` but not `graph_search`. That asymmetry is the whole test: all
three tools are registered when the project attaches, and only the stage
decides which of them the model can see.
"""

from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.domain import AdvanceStage, CreateProject, SelectWorkflow, SessionPurpose
from research_team.workflows import hybrid_default
from tests.conftest import ToolAwareFakeChatModel, start_session

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


def _model() -> ToolRecordingChatModel:
    return ToolRecordingChatModel(
        responses=[AIMessage(content="done", id="a1"), AIMessage(content="done", id="a2")]
    )


async def _project(application, *, workflow: bool, advance: bool = False):
    project_id = uuid4()
    project = application.service.projects.create_new(project_id)
    project.execute(CreateProject(project_id=project_id, name="course"))
    if workflow:
        project.execute(SelectWorkflow(preset=hybrid_default))
        if advance:
            project.execute(
                AdvanceStage(
                    preset=hybrid_default,
                    to_stage=FRAMING,
                    decided_by="human",
                    gate_decision="approve",
                )
            )
    await application.service.projects.save(project)
    return project_id


async def test_a_tool_outside_the_current_stage_is_not_callable(build_application):
    model = _model()
    application = await build_application(model=model)
    project_id = await _project(application, workflow=True, advance=True)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id, SessionPurpose.CHAT)

    await application.service.run_turn(session_id, "hi")

    assert {"list_sources", "read_source"} <= model.last_bound
    assert "graph_search" not in model.last_bound


async def test_the_hidden_tool_was_registered_all_along(build_application):
    """Proves the filter did the hiding, not a gap in what was wired.

    `managed_tools_for` takes the union across every stage precisely so this
    holds: registration cannot be per-stage, because a tool absent at agent
    creation cannot be added to a later one.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project(application, workflow=True, advance=True)
    await application.attach_project(project_id)

    assert "graph_search" in {tool.name for tool in application.turns_tools()}


async def test_a_project_with_no_workflow_sees_every_registered_tool(build_application):
    """Selecting nothing has to leave the agent exactly as it was."""
    model = _model()
    application = await build_application(model=model)
    project_id = await _project(application, workflow=False)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id, SessionPurpose.CHAT)

    await application.service.run_turn(session_id, "hi")

    assert {"list_sources", "read_source", "graph_search"} <= model.last_bound


async def test_a_session_outside_a_project_is_not_gated(build_application):
    model = _model()
    application = await build_application(model=model)
    session_id = await start_session(application.service)

    await application.service.run_turn(session_id, "hi")

    assert "fetch" in model.last_bound


async def test_the_first_stage_is_in_force_before_anything_advances(build_application):
    """`current_stage` is None until an advance; the preset's first stage still gates.

    The two cases `current_stage_of` exists to collapse -- and the one that
    would otherwise leave a freshly-selected workflow ungated for its whole
    first stage, which is the stage that decides what the run is even about.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project(application, workflow=True)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id, SessionPurpose.CHAT)

    await application.service.run_turn(session_id, "hi")

    # `tyler.step0.intake` claims all three, so a gate that resolved it
    # correctly withdraws nothing -- indistinguishable here from a gate that
    # never ran, which is why `test_the_stage_is_refolded_between_turns` starts
    # from this same state and then advances out of it.
    assert {"list_sources", "read_source", "graph_search"} <= model.last_bound


async def test_the_stage_is_refolded_between_turns(build_application):
    """Advancing mid-session changes the next turn, with no rebuild.

    The reason the provider is asked per turn rather than once: the executor
    outlives the stage, and a middleware resolved at construction would gate
    the rest of the run by wherever the project happened to stand when the
    application was built.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project(application, workflow=True)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id, SessionPurpose.CHAT)

    await application.service.run_turn(session_id, "hi")
    assert "graph_search" in model.last_bound

    project = await application.service.projects.load(project_id)
    project.execute(
        AdvanceStage(
            preset=hybrid_default,
            to_stage=FRAMING,
            decided_by="human",
            gate_decision="approve",
        )
    )
    await application.service.projects.save(project)

    await application.service.run_turn(session_id, "again")
    assert "graph_search" not in model.last_bound

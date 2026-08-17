"""Which kinds of turn the workflow attaches to, measured at the provider seam.

`running_workflow` used to ask one question -- does this session's project have
a preset -- and could not tell a research round from a person. These drive a
fake model through a real `create_deep_agent` on a project that has selected a
workflow and advanced past its first stage, and assert on what the model was
actually bound and actually sent.

The stage matters, and choosing it wrong weakens the measurement rather than
breaking it. `StageMiddleware` is a denylist over the *union* of every stage's
declared tools, and `_permits` gives a tool back only if the **current** stage
claims it -- so the loss is per stage: total on a stage claiming nothing,
partial on one claiming some. Across the three presets only five of 33 stages
declare any `tools` at all, and every preset's first stage is one of them.

`ubd.step1.context` is used because it declares none, and it is one advance
past `ubd.step0.intake` -- the ordinary case rather than an edge. An earlier
version of this file sat on `hybrid.step1.framing`, which claims `list_sources`
and `read_source`, and could therefore only pin `graph_search` being withdrawn.
"""

from typing import Any
from uuid import uuid4

from langchain_core.messages import AIMessage

from research_team.domain import AdvanceStage, CreateProject, SelectWorkflow, SessionPurpose
from research_team.workflows import ubd_pure
from tests.conftest import ToolAwareFakeChatModel

CONTEXT = "ubd.step1.context"
CORPUS_TOOLS = {"list_sources", "read_source", "graph_search"}


class RecordingChatModel(ToolAwareFakeChatModel):
    """Records both halves of what crossed the boundary: bound tools and prompt.

    One model rather than two because the two defects are one wiring fault, and
    a test that recorded them from separate turns could not say they were the
    same turn's tools and the same turn's system message.
    """

    bound: list[list[str]] = []
    prompts: list[str] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RecordingChatModel":
        self.bound.append([getattr(tool, "name", str(tool)) for tool in tools])
        return self

    def _generate(self, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        self.prompts.append("\n".join(str(getattr(m, "text", "")) for m in messages))
        return super()._generate(messages, *args, **kwargs)

    @property
    def last_bound(self) -> set[str]:
        return set(self.bound[-1]) if self.bound else set()

    @property
    def last_prompt(self) -> str:
        return self.prompts[-1] if self.prompts else ""


def _model() -> RecordingChatModel:
    model = RecordingChatModel(
        responses=[AIMessage(content="done", id="a1"), AIMessage(content="done", id="a2")]
    )
    model.bound = []
    model.prompts = []
    return model


async def _project_at_context(application):
    """A `ubd.pure` project one advance past intake, at a stage claiming no tools."""
    project_id = uuid4()
    project = application.service.projects.create_new(project_id)
    project.execute(CreateProject(project_id=project_id, name=f"course {project_id}"))
    project.execute(SelectWorkflow(preset=ubd_pure))
    project.execute(
        AdvanceStage(
            preset=ubd_pure,
            to_stage=CONTEXT,
            decided_by="human",
            gate_decision="approve",
        )
    )
    await application.service.projects.save(project)
    return project_id


async def test_a_research_round_is_not_given_the_workflow(build_application):
    """The three defects, one assertion each.

    All three failed before the `running_workflow` early return and pass after.
    Commenting the early return out fails all three again -- checked, not
    assumed.

    Assertion (3) uses the **strong form**: `RecordingChatModel.bind_tools`
    records the set that survives `StageMiddleware._permits` inside
    `awrap_model_call`, so this is the tools the model could actually call, not
    the raw registration. The weaker form the brief allows (assert no
    `stage_gate` middleware, and separately that a `CHAT` session on this stage
    does withdraw the three) was not needed: the sibling harness in
    `test_workflow_stage.py` already reaches the bound set.

    (3) is the one a test written only from the bug report would miss, and it
    is the one that silently breaks rounds: `StageMiddleware` is a denylist
    over the union of every stage's declared tools, so on a stage that declares
    none -- 26 of the 33 stages across the three presets -- `list_sources`,
    `read_source` and `graph_search` are all withdrawn, and a round cannot read
    the corpus it exists to read. `ubd.step1.context` is such a stage, so the
    full loss is what this pins.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at_context(application)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(
        project_id, SessionPurpose.RESEARCH_ROUND
    )

    await application.service.run_turn(session_id, "investigate the topic")

    # (1) An unattended call on a tool floored at `ask` is an approval nobody
    # answers, so the round must not be able to reach it at all.
    assert "advance_stage" not in model.last_bound
    # (2) The reported symptom: the stage's methodology in the system message
    # arguing with the round's own instructions in the user message.
    assert "## Current stage" not in model.last_prompt
    assert "This project runs a staged workflow" not in model.last_prompt
    # (3) The unreported one.
    assert model.last_bound >= CORPUS_TOOLS


async def test_a_person_still_gets_the_workflow(build_application):
    """The mirror, and what stops the fix being "delete StageMiddleware".

    Same preset, same stage, `purpose=CHAT`: `advance_stage` is bound, the
    system message names the current stage, and the stage's denylist is in
    force -- all three corpus tools withdrawn, because `ubd.step1.context`
    claims none of them. That is exactly the evidence for (3) above, read the
    other way: the same stage, the same union, and only the purpose differs.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at_context(application)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id, SessionPurpose.CHAT)

    await application.service.run_turn(session_id, "hi")

    assert "advance_stage" in model.last_bound
    assert "## Current stage" in model.last_prompt
    assert not (model.last_bound & CORPUS_TOOLS)

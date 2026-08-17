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

from research_team.application.grants import FetchGrant
from research_team.domain import AdvanceStage, CreateProject, SelectWorkflow, SessionPurpose
from research_team.domain.corpus import StoreSourceDocument
from research_team.workflows import ubd_pure
from tests.conftest import ToolAwareFakeChatModel

CONTEXT = "ubd.step1.context"
CORPUS_TOOLS = {"list_sources", "read_source", "graph_search"}

# Sent by both tests, so the pair differs in the purpose and nothing else. A
# round's real prompt and a person's "hi" would be the more natural pair and
# would also be a second moving variable: neither test could then say the
# purpose was what decided the outcome.
TURN_PROMPT = "investigate the topic"

# The first line of `WORKFLOW_PROMPT`, spelled once. Both tests read it -- the
# round asserting its absence and the mirror its presence -- so the round's
# assertion cannot start passing because the phrase was reworded or dropped
# from the chain entirely.
WORKFLOW_PROMPT_MARKER = "This project runs a staged workflow"


class RecordingChatModel(ToolAwareFakeChatModel):
    """Records both halves of what crossed the boundary: bound tools and prompt.

    One model rather than two because the two defects are one wiring fault, and
    a test that recorded them from separate turns could not say they were the
    same turn's tools and the same turn's system message.
    """

    bound: list[list[str]] = []
    prompts: list[str] = []
    # The tool objects themselves, not just their names. A name says a `fetch`
    # was bound; it cannot say *which* `fetch`, and C1 was two `fetch` tools
    # differing only in what they were built with.
    objects: list[list[Any]] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RecordingChatModel":
        self.bound.append([getattr(tool, "name", str(tool)) for tool in tools])
        self.objects.append(list(tools))
        return self

    def _generate(self, messages: list[Any], *args: Any, **kwargs: Any) -> Any:
        self.prompts.append("\n".join(str(getattr(m, "text", "")) for m in messages))
        return super()._generate(messages, *args, **kwargs)

    def last_tool(self, name: str) -> Any:
        return next(
            (tool for tool in self.objects[-1] if getattr(tool, "name", None) == name),
            None,
        )

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
    model.objects = []
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

    await application.service.run_turn(session_id, TURN_PROMPT)

    # (1) An unattended call on a tool floored at `ask` is an approval nobody
    # answers, so the round must not be able to reach it at all.
    assert "advance_stage" not in model.last_bound
    # (2) The reported symptom: the stage's methodology in the system message
    # arguing with the round's own instructions in the user message. Both
    # absences have their witness in the mirror below, which asserts the same
    # two strings are present for a CHAT session on this same stage.
    assert "## Current stage" not in model.last_prompt
    assert WORKFLOW_PROMPT_MARKER not in model.last_prompt
    # (3) The unreported one.
    assert model.last_bound >= CORPUS_TOOLS


async def test_a_person_still_gets_the_workflow(build_application):
    """The mirror, and what stops the fix being "delete StageMiddleware".

    Same preset, same stage, `purpose=CHAT`: `advance_stage` is bound, the
    system message names the current stage, and the stage's denylist is in
    force -- all three corpus tools withdrawn, because `ubd.step1.context`
    claims none of them. That is exactly the evidence for (3) above, read the
    other way: the same stage, the same union, the same user message, and only
    the purpose differs.

    It is also the witness for the round's two *absence* assertions. An absence
    proves nothing on its own -- drop `WORKFLOW_PROMPT` from the chain
    altogether and the round test still goes green, for the wrong reason. So
    both strings are asserted present here.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at_context(application)
    await application.attach_project(project_id)
    session_id = await application.service.start_in_project(project_id, SessionPurpose.CHAT)

    await application.service.run_turn(session_id, TURN_PROMPT)

    assert "advance_stage" in model.last_bound
    assert "## Current stage" in model.last_prompt
    assert WORKFLOW_PROMPT_MARKER in model.last_prompt
    assert not (model.last_bound & CORPUS_TOOLS)


STORED_URL = "https://example.invalid/already-have-this"
STORED_TEXT = "Tollers were bred in Yarmouth County."


def _free(tool: Any, name: str) -> Any:
    """One of `build_fetch_tool`'s captured arguments, off the tool's closure.

    `fetch` is a closure over `corpus`, `keep`, `grant` and the rest, and none
    of them is reachable as an attribute. Read this way rather than not
    asserted at all: `keep`'s effect is a network read followed by a corpus
    write, and a test that drove that would be testing httpx. The closure is
    the only place the wiring is visible without one.
    """
    inner = tool.coroutine
    index = inner.__code__.co_freevars.index(name)
    return inner.__closure__[index].cell_contents


async def test_a_rounds_granted_fetch_still_reads_and_keeps_the_project_corpus(
    build_application,
):
    """C1: `granted_tools` wanted a project id and was taking it off the workflow.

    A run registers a grant whether or not hosts were granted
    (`application/research_run.py`), and `_compose` shadows by name with
    `granted_tools` last -- so for a round this `fetch` *is* the `fetch`, and
    it replaces the corpus-carrying `project_fetch`. Deriving its project id
    from `running_workflow` therefore meant that giving a round no workflow
    also took away the corpus it reads and the keeper that saves what it
    fetches, silently, on every round.

    The corpus half is asserted behaviourally, and that is what makes this red
    rather than merely different: a `fetch` built with `corpus=None` never
    consults `stored_page`, so it goes to the network for a URL the project
    already holds. Against the pre-fix code this call leaves the process; with
    the reader bound it returns the stored text without a request.

    The keeper half is read off the closure, for the reason `_free` gives.
    Asserting only "a fetch was bound" would pass with both of them `None` --
    which was the shipped behaviour.
    """
    model = _model()
    application = await build_application(model=model)
    project_id = await _project_at_context(application)
    await application.attach_project(project_id)

    corpus = await application.knowledge._corpus.load_or_create(project_id)
    corpus.execute(
        StoreSourceDocument(
            corpus_id=project_id,
            source_id="s1",
            text=STORED_TEXT,
            uri=STORED_URL,
        )
    )
    await application.knowledge._corpus.save(corpus)
    await application.corpus_caught_up()

    session_id = await application.service.start_in_project(
        project_id, SessionPurpose.RESEARCH_ROUND
    )
    # An empty grant, which is what a run with no granted hosts registers --
    # the case that makes this land on every round rather than only on runs a
    # person had authorized hosts for.
    application.grants.register(
        session_id, FetchGrant(run_id=uuid4(), hosts=frozenset(), budget=1)
    )

    await application.service.run_turn(session_id, TURN_PROMPT)

    fetch = model.last_tool("fetch")
    assert fetch is not None
    assert _free(fetch, "grant") is not None, "not the grant-bound fetch"
    assert _free(fetch, "keep") is not None
    # A whole `ToolCall` rather than an args dict: `fetch` takes an
    # `InjectedToolCallId`, and langchain refuses the short form outright.
    answered = await fetch.ainvoke(
        {
            "args": {"url": STORED_URL},
            "name": "fetch",
            "type": "tool_call",
            "id": "c1",
        }
    )
    assert STORED_TEXT in str(getattr(answered, "content", answered))

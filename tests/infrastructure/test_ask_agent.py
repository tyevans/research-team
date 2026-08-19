"""The agent behind the ask page: what it may touch, and what it may cite.

The two assertions that carry the design are here -- the exact tool set, and
that a citation can only name something a tool actually opened.
"""

from typing import Any, cast
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langchain_core.tools import BaseTool, tool

from research_team.application.ask import AskMessage, Citation
from research_team.infrastructure.agent.ask_agent import (
    CITED_BY_TOOL,
    READ_ONLY_TOOLS,
    DeepAgentAskExecutor,
    citations,
    readable,
)
from research_team.infrastructure.agent.corpus_tools import build_corpus_tools
from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools
from research_team.infrastructure.agent.topic_tools import build_topic_tools
from tests.conftest import ToolAwareFakeChatModel


def named(name: str):
    @tool(name)
    def _stub(argument: str = "") -> str:
        """A stand-in for a project tool."""
        return ""

    return _stub


def test_the_admitted_tools_are_exactly_the_four_readers():
    """This set is the security boundary; a change to it should be deliberate."""
    # Expected on the left because ruff's SIM300 reads an ALL_CAPS name as the
    # literal half of the comparison; the assertion is unchanged either way.
    assert (
        frozenset({"list_sources", "read_source", "graph_search", "list_topics"})
        == READ_ONLY_TOOLS
    )


def test_every_mutating_project_tool_is_filtered_out():
    """The ask page must not be a second way to edit a project's knowledge."""
    tools = [
        named(name)
        for name in (
            "remember",
            "remember_page",
            "unmerge",
            # `open_topic` executes an `OpenTopic` command and creates a Topic
            # aggregate. It sat in the allowlist because the spec called it a
            # reader; it belongs in this list with the rest of the writers.
            "open_topic",
            "record_finding",
            "record_gap",
            "link_source",
            "fetch",
            "web_search",
            "read_source",
        )
    ]

    assert [kept.name for kept in readable(tools)] == ["read_source"]


def test_a_tool_nobody_has_admitted_yet_is_excluded():
    """An allowlist so that a tool added to open_graph later cannot arrive here
    by default. This test is the one that fails when that happens."""
    assert readable([named("summarise_everything")]) == ()


def test_a_read_source_call_becomes_a_source_citation():
    """A citation records a read, and this is what reading a source looks like."""
    messages = [
        HumanMessage(content="what did we find?"),
        AIMessage(
            content="",
            tool_calls=[{"name": "read_source", "args": {"source_id": "s1"}, "id": "t1"}],
        ),
    ]

    assert citations(messages) == (Citation(kind="source", id="s1"),)


def test_a_search_is_not_a_citation():
    """Searching is not reading. graph_search returns candidates the agent may
    never open, and citing them would overstate what it looked at."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "graph_search", "args": {"query": "boundary layer"}, "id": "t1"},
                {"name": "list_sources", "args": {}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == ()


def test_the_same_source_read_twice_is_cited_once():
    """A citation list is a set of things read, not a tally of reads."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_source", "args": {"source_id": "s1"}, "id": "t1"},
                {"name": "read_source", "args": {"source_id": "s1"}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == (Citation(kind="source", id="s1"),)


def test_citation_order_follows_the_order_things_were_read():
    """Stable output; a set would reorder the list between identical runs."""
    messages = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "read_source", "args": {"source_id": "b"}, "id": "t1"},
                {"name": "read_source", "args": {"source_id": "a"}, "id": "t2"},
            ],
        )
    ]

    assert citations(messages) == (
        Citation(kind="source", id="b"),
        Citation(kind="source", id="a"),
    )


def test_a_tool_call_without_its_identifying_argument_is_skipped():
    """A malformed call should not produce a citation to nothing."""
    messages = [
        AIMessage(content="", tool_calls=[{"name": "read_source", "args": {}, "id": "t1"}])
    ]

    assert citations(messages) == ()


def _real_project_tools() -> dict[str, BaseTool]:
    """The real reader tools, built over ports that are never called.

    The builders only close over their port to build the callables; nothing
    below invokes a tool, so a bare object is enough and this needs no database
    and no model. That is the whole reason the guard below can exist.
    """
    port = cast(Any, object())
    built = (
        *build_corpus_tools(port),
        *build_knowledge_tools(port),
        *build_topic_tools(port, uuid4()),
    )
    return {tool.name: tool for tool in built}


def test_every_citation_argument_exists_on_the_tool_it_names():
    """`CITED_BY_TOOL` named an argument `open_topic` does not have, so that
    entry could never have fired -- and every fixture in this file passes the
    argument the mapping expects, so no fixture could have caught it. This
    reads the real tools' schemas instead."""
    tools = _real_project_tools()

    for name, (_kind, argument) in CITED_BY_TOOL.items():
        assert name in tools, f"{name} is not a real project tool"
        assert argument in tools[name].args_schema.model_fields, (
            f"{name} has no argument {argument!r}"
        )


def test_every_admitted_tool_name_is_a_real_project_tool():
    """The allowlist is imported from the application layer, which stops a
    typo but not a name that no builder ever produces."""
    # Written this way round because ruff's SIM300 reads the ALL_CAPS name as
    # the literal half of the comparison; the assertion is the same either way.
    assert set(_real_project_tools()) >= READ_ONLY_TOOLS


class RecordingModel(ToolAwareFakeChatModel):
    """The shared fake, remembering what it was offered and what it was asked."""

    offered: list[str] = []
    prompted: list[BaseMessage] = []

    def bind_tools(self, tools: Any, **kwargs: Any) -> "RecordingModel":
        RecordingModel.offered = [getattr(one, "name", str(one)) for one in tools]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        RecordingModel.prompted = list(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


async def _answer(history=(), question="what did we find?") -> tuple[Any, list[str]]:
    RecordingModel.offered = []
    RecordingModel.prompted = []
    project_tools = tuple(
        named(name) for name in ("read_source", "record_finding", "list_topics")
    )
    executor = DeepAgentAskExecutor(
        model=RecordingModel(responses=[AIMessage(content="an answer", id="a1")]),
        open_graph=lambda _project: _ready((None, project_tools)),
        project_files=lambda _project: _ready({"notes.md": "x"}),
        project_sources=lambda _project: _ready({}),
    )
    reported: list[str] = []
    answer = await executor.run(
        project_id=uuid4(),
        history=history,
        question=question,
        on_activity=lambda note: reported.append(type(note).__name__),
    )
    return answer, reported


async def _ready(value):
    return value


async def test_the_agent_is_offered_the_readers_and_no_writer():
    """The two filters meet here: project tools are cut to the allowlist, and
    the built-in file tools to `READ_ONLY_FILE_TOOLS`. A `permissions=deny`
    rule was tried first and left `write_file`, `edit_file` and `delete` on
    this list -- that is what this test would fail on."""
    await _answer()

    assert set(RecordingModel.offered) == {
        "read_source",
        "list_topics",
        "ls",
        "read_file",
        "glob",
        "grep",
        "task",
    }


async def test_the_question_is_asked_after_the_conversation_so_far():
    """History arrives as `AskMessage`s and has to reach the model as the
    alternating turns it describes, with the new question last -- not as one
    concatenated blob, which is what a naive join would produce."""
    history = (
        AskMessage(role="user", text="who wrote it?"),
        AskMessage(role="assistant", text="Hoyle"),
    )

    await _answer(history=history, question="when?")

    # The system prompt leads and deepagents may append its own; the shape that
    # matters is the tail.
    tail = [
        # `.text` as a property, not a call: it is a property in the pinned
        # langchain-core and calling it warns (and will stop working).
        (type(message).__name__, message.text)
        for message in RecordingModel.prompted
        if isinstance(message, HumanMessage | AIMessage)
    ]
    assert tail == [
        ("HumanMessage", "who wrote it?"),
        ("AIMessage", "Hoyle"),
        ("HumanMessage", "when?"),
    ]


async def test_the_answer_is_the_models_last_text():
    """`run`'s return value, end to end over the fake -- the piece Task 5's
    route hands to the reader."""
    answer, _reported = await _answer()

    assert answer.text == "an answer"
    assert answer.citations == ()


async def test_the_reference_syntax_reaches_the_model():
    """Not that a constant exists somewhere -- that it is in the system
    message `RecordingModel` actually receives, which is the point Task 5's
    brief names as the one that makes the previous four tasks used rather
    than inert."""
    from langchain_core.messages import SystemMessage

    from research_team.application.corpus_read import REFERENCE_SYNTAX_PROMPT

    await _answer()

    system_text = "\n".join(
        str(message.content)
        for message in RecordingModel.prompted
        if isinstance(message, SystemMessage)
    )
    assert REFERENCE_SYNTAX_PROMPT in system_text


def test_the_ask_prompt_carries_the_component_reference():
    """Without this the agent never authors one, and every other task in this
    feature renders nothing. Red against the prompt as it stood."""
    from research_team.infrastructure.agent.ask_agent import ASK_PROMPT

    assert "component:mcq" in ASK_PROMPT
    assert "component:checklist" not in ASK_PROMPT
    # Craft, not only syntax -- Task 1's notes reach this prompt through the
    # same generated reference the stage prompt uses.
    assert "distractor" in ASK_PROMPT


def test_the_hand_written_paragraph_names_exactly_the_resolved_types_on_offer():
    """The two halves of this prompt have to agree about what exists.

    `ASK_COMPONENT_PROMPT` is a hand-written paragraph followed by a
    registry-generated reference. The generated half cannot drift; the
    hand-written half is a copy of `{n for n in ASK_COMPONENT_TYPES if
    REGISTRY[n].resolved}` kept by hand, and it drifted the first time it was
    given the chance -- commit `0f2f9b5` registered `explorer` as the sixth
    resolved type while the paragraph went on saying "The other five" and
    listing five names. The generated reference below it carried six examples.
    Nothing caught it: not the four gates, not a full review. A model reading
    that prompt was handed a false inventory of what it may write, which is the
    exact failure the generated reference exists to prevent, arriving through
    the one half the registry does not generate.

    Would have gone red at `0f2f9b5`, which is the only reason it is worth its
    runtime.

    **It pins the inventory and not the prose.** A paragraph that names every
    right type and describes all of them wrongly still passes here, and no test
    can replace reading it. What this refuses is a name that is missing or a
    name that should not be there.
    """
    from research_team.application.ask_components import ASK_COMPONENT_TYPES
    from research_team.application.components import REGISTRY
    from research_team.infrastructure.agent.ask_agent import ASK_COMPONENT_PROMPT

    # Split at the first fenced example: everything before it is hand-written,
    # everything after is `component_reference` output. Naming a type only in
    # the generated half is exactly the drift this is about, so the halves are
    # compared rather than the whole string searched.
    hand_written = ASK_COMPONENT_PROMPT.split("```component:")[0]
    named = {name for name in REGISTRY if f"`{name}`" in hand_written}
    resolved = {name for name in ASK_COMPONENT_TYPES if REGISTRY[name].resolved}

    assert named >= resolved, f"offered but unnamed: {sorted(resolved - named)}"
    unoffered = named - set(ASK_COMPONENT_TYPES)
    assert not unoffered, f"named but not on offer: {sorted(unoffered)}"

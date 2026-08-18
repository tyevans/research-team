"""The socratic agent: what it is told, and what it does with what comes back.

The prompt assertions are structural rather than about wording -- a test that
pinned sentences would fail on every improvement to the prompt and teach people
to delete it. What is pinned is what the design's §4 says must not drift: that
the prompt is composed rather than appended, that the component reference is
the two-type one, and that the two calls get different instructions.
"""

from uuid import uuid4

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
)
from langchain_core.tools import tool

from research_team.application.socratic import (
    DialogueMessage,
    SocraticFraming,
    SocraticPrompt,
)
from research_team.application.socratic_components import SOCRATIC_COMPONENT_TYPES
from research_team.infrastructure.agent import socratic_agent
from research_team.infrastructure.agent.ask_agent import READ_ONLY_FILE_TOOLS
from research_team.infrastructure.agent.socratic_agent import (
    _FRAMING_FIELDS,
    _JUDGEMENT_FIELDS,
    SOCRATIC_COMPONENT_PROMPT,
    SOCRATIC_FRAMING_SYSTEM,
    SOCRATIC_JUDGEMENT_PROMPT,
    SOCRATIC_PROMPT,
    SOCRATIC_TOOLS_PROMPT,
    DeepAgentSocraticExecutor,
    parse_framing,
    parse_judgement,
)
from tests.conftest import ToolAwareFakeChatModel


def test_the_reply_prompt_is_built_from_the_pieces_and_not_from_the_ask_s():
    """The design's §4 trap, asserted on identity rather than on wording.

    `ASK_PROMPT` is rebound at `ask_agent.py:147` to carry the whole nine-type
    component reference -- 9,600 characters -- so a socratic prompt built by
    appending to it inherits six resolved types silently and still works.

    Red against `SOCRATIC_PROMPT = ASK_PROMPT + SOCRATIC_METHOD_PROMPT`: the
    ask's own opening sentence arrives with it.
    """
    from research_team.infrastructure.agent.ask_agent import ASK_PROMPT

    assert SOCRATIC_TOOLS_PROMPT in SOCRATIC_PROMPT
    assert SOCRATIC_COMPONENT_PROMPT in SOCRATIC_PROMPT
    assert ASK_PROMPT not in SOCRATIC_PROMPT
    # The ask's first line, which no composed prompt would contain.
    assert "You are answering questions about" not in SOCRATIC_PROMPT


def test_the_component_reference_carries_exactly_the_two_offered_types():
    for name in SOCRATIC_COMPONENT_TYPES:
        assert f"component:{name}" in SOCRATIC_COMPONENT_PROMPT
    for unwanted in ("flashcards", "checklist", "definition", "graph", "explorer"):
        assert f"component:{unwanted}" not in SOCRATIC_COMPONENT_PROMPT


def test_the_framing_call_and_the_reply_call_are_told_different_things():
    """Two prompts because they are two jobs. The framing call turns a topic
    into a goal, a stopping condition and an opening question, once; the reply
    call is handed that framing and continues toward it.

    Red against a single prompt used for both, which would ask the model to
    re-decide the goal on every exchange -- and a goal the model can re-decide
    is not a stopping condition anything can test.
    """
    assert SOCRATIC_FRAMING_SYSTEM != SOCRATIC_PROMPT
    # The framing call must not be offered components: it produces three
    # strings, not an utterance to the reader.
    assert "component:mcq" not in SOCRATIC_FRAMING_SYSTEM
    # And both share the tools half, because both may read the corpus.
    assert SOCRATIC_TOOLS_PROMPT in SOCRATIC_FRAMING_SYSTEM


def test_the_reply_prompt_says_the_reader_cannot_be_told_the_answer():
    """The one instruction that makes this surface different from an ask, and
    the one a model will drift from first. Structural: the prompt has to say
    something about not answering, because a socratic agent that answers is an
    ask agent with extra steps."""
    lowered = SOCRATIC_PROMPT.lower()

    assert "question" in lowered
    assert any(
        word in lowered for word in ("do not answer", "rather than answering", "not to answer")
    )


def test_the_reply_prompt_tells_the_model_the_stopping_condition_is_not_its_to_move():
    """The stopping condition is decided once, at framing, and lives in the
    aggregate. A model invited to revise it mid-dialogue produces a dialogue
    that stops when the model gets bored, which is what having a testable
    stopping condition was for."""
    lowered = SOCRATIC_PROMPT.lower()

    assert "stopping condition" in lowered


def test_the_parser_asks_for_exactly_the_keys_the_framing_prompt_asks_for():
    """The one contract that had existed only as prose.

    `SOCRATIC_FRAMING_PROMPT` shows the model a three-key YAML block; nothing
    connected that block to the parser that reads its answer, so renaming a key
    in the prompt would have left `parse_framing` refusing every well-formed
    framing -- or, worse, a key added to the prompt and not to the parser would
    have been silently dropped.

    `_FRAMING_FIELDS` is now *derived* from the prompt at import, so the two
    cannot disagree. This test pins the derivation's result rather than
    re-deriving it: a prompt edit that dropped `stopping_condition` would make
    the derivation agree with itself and fail here, which is the point.

    Would pass with the derivation replaced by a hand-written tuple *today* --
    it is the drift a year from now that it catches, so it is deliberately an
    equality against the three literal names.
    """
    assert _FRAMING_FIELDS == ("goal", "stopping_condition", "opening_prompt")


def test_a_framing_block_becomes_the_three_strings():
    text = (
        "```yaml\n"
        "goal: |\n"
        "  why the creed's wording mattered politically\n"
        "stopping_condition: |\n"
        "  the reader distinguishes the settlement from the politics around it\n"
        "opening_prompt: |\n"
        "  What do you already believe the creed settled?\n"
        "```\n"
    )

    framing = parse_framing(text)

    assert isinstance(framing, SocraticFraming)
    assert framing.goal == "why the creed's wording mattered politically"
    assert (
        framing.stopping_condition
        == "the reader distinguishes the settlement from the politics around it"
    )
    assert framing.opening_prompt == "What do you already believe the creed settled?"


def test_a_framing_without_a_fence_is_still_read():
    """Models drop the fence roughly as often as they include it, and a framing
    that failed for want of three backticks would fail the whole dialogue at
    its first call. Red against a parser that requires the fence."""
    text = (
        "goal: understand the settlement\n"
        "stopping_condition: the reader explains it unaided\n"
        "opening_prompt: Where would you start?\n"
    )

    framing = parse_framing(text)

    assert framing.goal == "understand the settlement"
    assert framing.opening_prompt == "Where would you start?"


@pytest.mark.parametrize(
    "text",
    [
        "",
        "I would be happy to help you explore this topic!",
        "```yaml\ngoal: only a goal\n```\n",
        "```yaml\ngoal: g\nstopping_condition: s\n```\n",
    ],
)
def test_a_framing_that_is_missing_a_field_is_refused_rather_than_defaulted(text):
    """A dialogue framed with an empty stopping condition is one that can never
    stop, and it would look completely normal until the reader gave up.

    Refused loudly here, at `begin`, where the reader has invested one click --
    rather than defaulted to "" and discovered twenty exchanges later. Red
    against a parser that fills missing keys with empty strings, which is what
    a `.get(key, "")` implementation does.
    """
    with pytest.raises(ValueError, match="framing"):
        parse_framing(text)


def test_a_reply_carries_the_sources_the_agent_actually_opened():
    """`CITED_BY_TOOL` is reused rather than re-derived: `read_source` is still
    the only admitted tool that opens one identified thing, and a second table
    would be a second thing to keep in step with the allowlist."""
    from research_team.infrastructure.agent.ask_agent import CITED_BY_TOOL, READ_SOURCE_TOOL

    assert CITED_BY_TOOL[READ_SOURCE_TOOL] == ("source", "source_id")


def test_the_tools_prompt_describes_every_file_tool_the_executor_actually_admits():
    """Half of a drift this task created, and only half -- say so.

    `DeepAgentSocraticExecutor` imports `READ_ONLY_FILE_TOOLS` from
    `ask_agent`, so the *behaviour* is shared, while `SOCRATIC_TOOLS_PROMPT`
    describes those tools in prose copied by hand. A file tool added to the
    ask's list would be handed to a dialogue and described to it by nothing.

    **Covers the file tools only.** The other half -- the project tools that
    survive `readable(project_tools)` -- needs a built project to enumerate and
    is not asserted here. Do not read this test as covering the allowlist.
    """
    for name in READ_ONLY_FILE_TOOLS:
        assert name in SOCRATIC_TOOLS_PROMPT, f"{name} is admitted but never described"


def test_a_framing_whose_keys_the_prompt_no_longer_declares_is_a_ValueError(monkeypatch):
    """`_framing_fields` fails open by design -- an unreadable prompt block
    yields `()` rather than raising at import, so a build that never opens a
    dialogue still starts. But with `()` nothing is 'missing', and the three
    literal lookups below it would raise **KeyError**, which no caller and no
    other test here expects.

    Red against the version that let the `KeyError` out: `pytest.raises`
    demands `ValueError` and a `KeyError` is not one.
    """
    monkeypatch.setattr(socratic_agent, "_FRAMING_FIELDS", ())

    with pytest.raises(ValueError, match="framing"):
        parse_framing("goal: only a goal\n")


class RecordingModel(ToolAwareFakeChatModel):
    """The shared fake, remembering what it was asked. `test_ask_agent.py`'s,
    duplicated rather than imported: importing a private helper out of a
    sibling test module couples two suites that are free to diverge."""

    prompted: list[BaseMessage] = []

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        RecordingModel.prompted = list(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _named(name: str):
    @tool(name)
    def _stub(argument: str = "") -> str:
        """A stand-in for a project tool."""
        return ""

    return _stub


async def _ready(value):
    return value


async def _respond(history=(), reply="It settled Arianism."):
    """One `respond` call over the tool-aware fake, mirroring
    `test_ask_agent.py::_answer` because the executor mirrors that one."""
    RecordingModel.prompted = []
    project_tools = tuple(_named(name) for name in ("read_source", "record_finding"))
    executor = DeepAgentSocraticExecutor(
        model=RecordingModel(responses=[AIMessage(content="Why do you say that?", id="a1")]),
        open_graph=lambda _project: _ready((None, project_tools)),
        project_files=lambda _project: _ready({"notes.md": "x"}),
        project_sources=lambda _project: _ready({}),
    )
    reported: list[str] = []
    result = await executor.respond(
        project_id=uuid4(),
        history=history,
        goal="why the creed's wording mattered politically",
        stopping_condition="the reader separates the settlement from the politics",
        reply=reply,
        on_activity=lambda note: reported.append(type(note).__name__),
    )
    return result, reported


async def test_a_reply_comes_back_as_the_models_next_question():
    """`respond`'s return value end to end over the fake -- the half of the
    executor the composed test does not reach, because that one calls `frame`
    only and `begin` never calls `respond`.

    Red against an executor whose `respond` was never written, and red against
    one returning `SocraticPrompt(prompt=...)` built from the tail message
    rather than `last_text` -- the final state can end on a `ToolMessage`.

    `citations` is empty because the fake calls no tool; that the mapping from
    tool calls to citations is right is `test_ask_agent.py`'s, since this
    executor imports the same `citations` function rather than re-deriving it.
    """
    result, _reported = await _respond()

    assert isinstance(result, SocraticPrompt)
    assert result.prompt == "Why do you say that?"
    assert result.citations == ()
    # Left at their defaults until Plan 4; see the comment at the return site.
    assert result.observation is None
    assert result.concluded is False


async def test_the_goal_and_the_stopping_condition_reach_the_model_ahead_of_the_history():
    """The framing is a `SystemMessage`, not a prefix on the reader's words --
    a model shown it as something the reader said will sometimes answer it.

    And the history has to arrive as the alternating turns it describes with
    the new reply last, not as one concatenated blob, which is what a naive
    join would produce. Red against `_framed_history` dropping the framing, or
    appending the reply anywhere but the end.
    """
    history = (
        DialogueMessage(role="assistant", text="What do you already believe it settled?"),
        DialogueMessage(role="user", text="Something about Arius."),
    )

    await _respond(history=history, reply="It settled his christology.")

    framings = [
        message
        for message in RecordingModel.prompted
        if isinstance(message, SystemMessage)
        and "why the creed's wording mattered politically" in message.text
    ]
    assert len(framings) == 1, "the goal reached the model zero times or twice"
    assert "the reader separates the settlement from the politics" in framings[0].text

    tail = [
        # `.text` as a property, not a call: it is a property in the pinned
        # langchain-core and calling it warns.
        (type(message).__name__, message.text)
        for message in RecordingModel.prompted
        if isinstance(message, HumanMessage | AIMessage)
    ]
    assert tail == [
        ("AIMessage", "What do you already believe it settled?"),
        ("HumanMessage", "Something about Arius."),
        ("HumanMessage", "It settled his christology."),
    ]


async def test_every_message_of_the_exchange_is_reported_before_respond_returns():
    """The `astream` loop and its `reported` index, copied from
    `DeepAgentAskExecutor.run` and adapted -- `messages` here is longer than
    the ask's by one, because `_framed_history` prepends a `SystemMessage`.

    **Measured, not reasoned, on 2026-08-18:** with `reported = 0` this fails
    *loudly* rather than by reporting too much. `to_activity_message` refuses a
    `SystemMessage` with `TurnAccountingError` (`messages.py:60`, which exists
    to stop a user turn being recorded twice), so the framing turn aborts
    `respond` outright before a single note is reported -- all three `respond`
    tests here go red together, this one on the raise rather than on its count.

    That is a better failure than the one expected when this test was written,
    and it is luck rather than design: the guard belongs to the turn-recording
    path and nothing makes it the activity path's business. If the framing ever
    stops being a `SystemMessage`, an off-by-one here goes back to being silent
    and this test's count assertion is what would catch it. Both halves are
    asserted for that reason.
    """
    result, reported = await _respond()

    assert reported, "nothing was reported: the activity loop yielded nothing at all"
    # The model's one message, and no note for anything that went *in*.
    assert reported.count("ActivityMessage") == 1, reported
    assert result.prompt == "Why do you say that?"


def test_a_judgement_block_becomes_a_verdict_and_a_question():
    """The ordinary turn: not finished, here is the next question.

    The judgement comes FIRST in the block and the question second, which is
    the ordering ruling -- a model that has already written `concluded: false`
    has committed to continuing before it writes what to ask. Asked the other
    way round it writes a question and then rationalises a verdict that keeps
    it.
    """
    text = (
        "```yaml\n"
        "concluded: false\n"
        "observation: |\n"
        "  named both parties but not what divided them\n"
        "prompt: |\n"
        "  What did Arius actually claim about the Son?\n"
        "```\n"
    )

    judged = parse_judgement(text)

    assert judged.concluded is False
    assert judged.prompt == "What did Arius actually claim about the Son?"
    assert judged.observation is not None
    assert judged.observation.observation == "named both parties but not what divided them"
    # The model's own reading, never a graded fact. A stopping condition met
    # entirely by these is a dialogue that graded its own homework, and the kind
    # is the only thing that keeps that visible.
    assert judged.observation.evidence == "assessment"


def test_a_concluding_judgement_may_carry_no_question():
    """A finished dialogue has nothing further to ask.

    Forcing a closing question is how a dialogue asks one more "to be sure",
    which `SOCRATIC_METHOD_PROMPT` already tells the model not to do. Red
    against a parser that requires `prompt` unconditionally -- every genuine
    conclusion would then be refused, and a dialogue that can never conclude is
    exactly what this plan exists to end.
    """
    text = (
        "```yaml\n"
        "concluded: true\n"
        "observation: |\n"
        "  distinguished the settlement from the politics, unaided\n"
        'prompt: ""\n'
        "```\n"
    )

    judged = parse_judgement(text)

    assert judged.concluded is True
    assert judged.prompt == ""
    assert judged.observation is not None


def test_a_turn_that_concludes_nothing_and_asks_nothing_is_refused():
    """The silent failure this plan is shaped around, in its purest form.

    An empty prompt on a non-concluding turn is a model that produced no
    question. Defaulted, the reader sees a blank utterance and a dialogue that
    is somehow still going; refused, the turn fails and says why.

    Red against a parser that only requires `prompt` when `concluded` is false
    *and* treats a missing key as empty -- the common shape.
    """
    text = '```yaml\nconcluded: false\nprompt: ""\n```\n'

    with pytest.raises(ValueError, match="question"):
        parse_judgement(text)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "That's exactly right, well done!",
        "```yaml\nprompt: What next?\n```\n",
        "```yaml\nconcluded: maybe\nprompt: What next?\n```\n",
        "```yaml\n- concluded\n- prompt\n```\n",
    ],
)
def test_a_judgement_that_cannot_be_read_is_refused_rather_than_defaulted(text):
    """**The whole reason this is its own plan.**

    Every case here would come back as a `SocraticJudgement` under an
    implementation that defaults -- `concluded: False`, which is
    indistinguishable from a dialogue that is simply still going. A broken
    judgement path would then look like working software forever: the reader
    keeps answering, the model keeps asking, and nothing ever stops. Refusing
    makes the turn fail loudly on the first malformed answer.

    The prose case is the one that matters most: a model that ignored the
    format entirely and just replied warmly is the likeliest real failure, and
    it is the one a truthy-`.get` reads as "not finished, no question".

    `concluded: maybe` is here because YAML will happily give back the string
    `"maybe"`, which is truthy -- a parser doing `bool(loaded.get("concluded"))`
    concludes the dialogue on a value the model never meant as a yes.

    Proved red on 2026-08-18 by writing the defaulting version, and the count
    is measured rather than asserted: `bool(loaded.get("concluded", False))`
    alone turns two of these five red -- the two that are already mappings.
    The other three ("", the prose, the list) still raise, from the mapping
    guard. Dropping *all three* guards (mapping, bool, and the no-question one)
    is the fully-defaulting parser, and under it all five come back as a
    `SocraticJudgement` with `concluded=False` -- the prose case with an empty
    prompt besides, which is the exact shape a dialogue that never ends is made
    of.
    """
    with pytest.raises(ValueError, match="judgement"):
        parse_judgement(text)


def test_the_parser_asks_for_exactly_the_keys_the_judgement_prompt_asks_for():
    """Derived, not written twice -- the same guard `_framing_fields` gives the
    framing parse. Two independent literals produce either a parser that
    refuses every well-formed judgement (a renamed key it still demands) or one
    that reads a key nothing sends, and neither has a symptom a caller could
    act on.
    """
    assert set(_JUDGEMENT_FIELDS) == {"concluded", "observation", "prompt"}
    for name in _JUDGEMENT_FIELDS:
        assert f"{name}:" in SOCRATIC_JUDGEMENT_PROMPT


def test_an_observation_is_optional_and_absent_means_nothing_was_demonstrated():
    """The one key that may be absent, and the asymmetry is deliberate: a turn
    where the reader demonstrated nothing worth recording is ordinary, where a
    turn with no verdict and no question is broken.

    Red against a parser that manufactures an empty observation, which would
    write a `SocraticProgressObserved` carrying no observation on every turn and
    bury the real ones.
    """
    judged = parse_judgement("```yaml\nconcluded: false\nprompt: Why?\n```\n")

    assert judged.observation is None
    assert judged.prompt == "Why?"


def test_the_reply_prompt_carries_the_judgement_block_verdict_first():
    """The ordering ruling, pinned where it is actually paid: `SOCRATIC_PROMPT`
    is what the reply call is handed, and a judgement block that exists but was
    never folded into it would leave every turn's answer unparseable while every
    test above still passed.

    Structural rather than about wording -- what is asserted is that the block
    is in the assembled prompt and that `concluded:` precedes `prompt:` within
    it. Would pass with the change reverted only if `SOCRATIC_PROMPT` already
    contained the block; it did not, and this was red before the fold-in.
    """
    assert SOCRATIC_JUDGEMENT_PROMPT in SOCRATIC_PROMPT
    verdict = SOCRATIC_JUDGEMENT_PROMPT.index("concluded:")
    question = SOCRATIC_JUDGEMENT_PROMPT.index("prompt:")
    assert verdict < question

"""The socratic agent: what it is told, and what it does with what comes back.

The prompt assertions are structural rather than about wording -- a test that
pinned sentences would fail on every improvement to the prompt and teach people
to delete it. What is pinned is what the design's §4 says must not drift: that
the prompt is composed rather than appended, that the component reference is
the two-type one, and that the two calls get different instructions.
"""

import pytest

from research_team.application.socratic import SocraticFraming
from research_team.application.socratic_components import SOCRATIC_COMPONENT_TYPES
from research_team.infrastructure.agent.socratic_agent import (
    _FRAMING_FIELDS,
    SOCRATIC_COMPONENT_PROMPT,
    SOCRATIC_FRAMING_SYSTEM,
    SOCRATIC_PROMPT,
    SOCRATIC_TOOLS_PROMPT,
    parse_framing,
)


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

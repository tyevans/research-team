"""The socratic agent: what it is told, and what it does with what comes back.

The prompt assertions are structural rather than about wording -- a test that
pinned sentences would fail on every improvement to the prompt and teach people
to delete it. What is pinned is what the design's §4 says must not drift: that
the prompt is composed rather than appended, that the component reference is
the two-type one, and that the two calls get different instructions.
"""

from research_team.application.socratic_components import SOCRATIC_COMPONENT_TYPES
from research_team.infrastructure.agent.socratic_agent import (
    SOCRATIC_COMPONENT_PROMPT,
    SOCRATIC_FRAMING_SYSTEM,
    SOCRATIC_PROMPT,
    SOCRATIC_TOOLS_PROMPT,
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

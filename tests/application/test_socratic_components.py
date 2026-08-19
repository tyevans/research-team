"""What a dialogue may author, and the one projection of it.

The tuple is written out rather than derived, for `ASK_COMPONENT_TYPES`'
reason: a derived list is how `COMPONENTS_FOR[BUILD]` came to advertise five
widgets that cannot work where its prompt is used -- a registry entry joined a
prompt by existing. A third type here should be a decision somebody made.

**The last two tests still import `socratic_agent` inside the function body.**
They were written before that module existed and carried `xfail(strict=True)`
until Task 2 landed it; the strict marker is what forced this deletion to be
deliberate rather than leaving a working feature behind a permanently-excused
test. The deferred import is kept because it costs nothing and states which
direction the dependency runs -- an `application/` test reaching into
`infrastructure/` for the one assertion that touches a real prompt.
"""

from research_team.application.socratic_components import (
    SOCRATIC_COMPONENT_TYPES,
    dialogue_document,
)


def test_only_gradeable_components_are_offered():
    """`mcq` and `cloze`, and the reason is the stopping condition.

    Grading is what feeds it (design §3): a dialogue that asks an item and
    marks the answer has *evidence* the reader demonstrated something, where a
    dialogue that asks for prose has only the model's opinion of it.
    `flashcards` is out and the registry agrees for once: measured on
    2026-08-17, `REGISTRY["flashcards"].gradeable` is False. Nothing is right
    about a card, so there is no verdict to feed anything.

    The six resolved types are absent for a second reason, and it is not the
    ask's: they would resolve here, because a dialogue *has* a project in
    scope. They are out because nothing in a dialogue yet uses what they draw,
    and offering a model six ways to answer with a picture when the surface is
    about questioning is how a socratic dialogue becomes a slideshow. This is
    the entry to revisit first when the surface grows.
    """
    assert SOCRATIC_COMPONENT_TYPES == ("mcq", "cloze")


def test_a_component_in_a_prompt_is_parsed_out_of_the_prose():
    text = (
        "Before we go on, try this:\n\n"
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which council?\n"
        "options:\n"
        '  - text: "Nicaea"\n'
        "    correct: true\n"
        '  - text: "Chalcedon"\n'
        "    correct: false\n"
        "```\n"
    )

    blocks = dialogue_document(text)["blocks"]

    assert [block["kind"] for block in blocks] == ["markdown", "component"]
    assert blocks[1]["type"] == "mcq"


def test_the_learner_view_is_the_default_and_keeps_no_answer():
    """The one assertion that matters on this module, and it matters more here
    than on the ask: a dialogue's whole method is asking rather than telling,
    so a default of `author` would hand the reader the key on the exact frame
    that was meant to make them think.

    Red against `view: View = "author"`.
    """
    text = (
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which council?\n"
        "options:\n"
        '  - text: "Nicaea"\n'
        "    correct: true\n"
        '  - text: "Chalcedon"\n'
        "    correct: false\n"
        "```\n"
    )

    block = dialogue_document(text)["blocks"][0]

    assert "correct" not in str(block["data"])
    assert block["withheld"]


def test_a_dialogue_offers_no_component_the_ask_withholds_nothing_for():
    """The tuple's two claims, asserted against the registry rather than
    restated: every offered type can be marked, and none of them is a
    reference. Withholding is what makes asking a component worth more than
    asking in prose, and only a gradeable type has anything to withhold.

    Red against adding `flashcards` (gradeable is False) or any of the six
    resolved types (resolved is True) to the tuple. It is deliberately NOT the
    `withheld` flag being asserted -- that is the third test's job, and this
    one is about what may enter the tuple at all, which is the check that has
    to bite when a registry entry joins by existing.
    """
    from research_team.application.components import REGISTRY

    for name in SOCRATIC_COMPONENT_TYPES:
        component = REGISTRY[name]
        assert component.gradeable, f"{name} is offered but cannot be marked"
        assert not component.resolved, f"{name} is a reference, not a question"


def test_the_prompt_a_socratic_agent_receives_carries_every_offered_type():
    """The end of the wiring, and the only assertion here that touches what a
    real dialogue turn is handed.

    Widening the tuple buys nothing if the call site renders a hardcoded list
    instead -- the drift `only=` exists to prevent, and which no other test in
    this file would catch because every one of them reads the tuple rather than
    the prompt built from it.
    """
    from research_team.infrastructure.agent.socratic_agent import SOCRATIC_PROMPT

    for name in SOCRATIC_COMPONENT_TYPES:
        assert f"component:{name}" in SOCRATIC_PROMPT, f"{name} never reaches the model"


def test_the_socratic_prompt_inherits_nothing_from_the_ask_s_component_reference():
    """The trap the design names by measurement.

    `ask_agent.py:147` rebinds `ASK_PROMPT = ASK_PROMPT + ASK_COMPONENT_PROMPT`,
    and that reference now covers nine types at 9,600 characters. A socratic
    prompt built by appending to `ASK_PROMPT` inherits all six resolved types
    silently -- it still *works*, which is why nothing else would catch it, and
    it teaches the model to answer with pictures on a surface whose method is
    questioning.

    Red against `SOCRATIC_PROMPT = ASK_PROMPT + "..."`.
    """
    from research_team.infrastructure.agent.socratic_agent import SOCRATIC_PROMPT

    for unwanted in ("definition", "evidence", "graph", "timeline", "compare", "explorer"):
        assert f"component:{unwanted}" not in SOCRATIC_PROMPT, (
            f"{unwanted} reached the socratic prompt, which means it was built by "
            f"appending to ASK_PROMPT rather than composed from pieces"
        )

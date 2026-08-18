from research_team.application.ask_components import ASK_COMPONENT_TYPES, answer_document


def test_an_answer_with_no_components_is_one_markdown_block():
    doc = answer_document("Two papers cover this, both from 1974.")

    assert [block["kind"] for block in doc["blocks"]] == ["markdown"]


def test_a_component_in_an_answer_is_parsed_out_of_the_prose():
    answer = (
        "Here is one to try:\n\n"
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which year?\n"
        "options:\n"
        '  - text: "1974"\n'
        "    correct: true\n"
        '  - text: "1975"\n'
        "    correct: false\n"
        "```\n"
    )

    blocks = answer_document(answer)["blocks"]

    assert [block["kind"] for block in blocks] == ["markdown", "component"]
    assert blocks[1]["type"] == "mcq"


def test_the_learner_view_is_the_default_and_keeps_no_answer():
    """The one assertion that matters on this module. A default of `author`
    would ship the key to the page that is meant not to show it, on every ask.

    Red against `view: View = "author"`."""
    answer = (
        "```component:mcq\n"
        "id: q1\n"
        "prompt: Which year?\n"
        "options:\n"
        '  - text: "1974"\n'
        "    correct: true\n"
        '  - text: "1975"\n'
        "    correct: false\n"
        "```\n"
    )

    block = answer_document(answer)["blocks"][0]

    assert "correct" not in str(block["data"])
    assert block["withheld"]


def test_checklist_is_not_offered_to_the_ask_agent():
    """Its only interesting mode is `persist: true`, and the ask path has no
    identity to persist against -- see the design's section 4."""
    assert "checklist" not in ASK_COMPONENT_TYPES


def test_every_resolved_type_is_offered_to_the_ask_agent():
    """An ask is precisely where a reader asks about the corpus, so a widget
    that shows the corpus belongs there. `checklist` stays out for its own
    stated reason -- it needs a learner identity the ask path does not have --
    and that ruling is unaffected by these five."""
    assert set(ASK_COMPONENT_TYPES) >= {
        "definition",
        "evidence",
        "graph",
        "timeline",
        "compare",
    }
    assert "checklist" not in ASK_COMPONENT_TYPES


def test_a_resolved_component_in_an_answer_keeps_its_reference():
    """The learner default must not strip a reference. A resolved component
    has no answer key, so `project()` is identity for it -- and if that ever
    stopped holding, the ask surface is where it would show first, as a widget
    that renders nothing with no error anywhere."""
    answer = "```component:definition\nid: d1\nentity: Nicene Christianity\n```\n"

    block = answer_document(answer)["blocks"][0]

    assert block["data"]["entity"] == "Nicene Christianity"
    assert block["resolved"] is True
    assert block["withheld"] == []


def test_the_prompt_an_ask_agent_receives_carries_every_offered_type():
    """The end of the wiring, and the only assertion here that touches what a
    real ask turn is handed.

    Widening `ASK_COMPONENT_TYPES` buys nothing if the call site renders a
    hardcoded list instead -- which is the drift `only=` exists to prevent, and
    which no other test in this file would catch, because every one of them
    reads the tuple rather than the prompt built from it.

    Red against `component_reference(only=("mcq", "cloze", "flashcards"))` at
    `ask_agent.py`'s call site, with the tuple widened as it is now.
    """
    from research_team.infrastructure.agent.ask_agent import ASK_PROMPT

    for name in ASK_COMPONENT_TYPES:
        assert f"component:{name}" in ASK_PROMPT, f"{name} never reaches the model"
    assert "component:checklist" not in ASK_PROMPT

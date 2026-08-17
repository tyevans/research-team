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

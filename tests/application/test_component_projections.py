"""Tests for consolidated dialogue component projections and extraction."""

from research_team.dialogue.application.component_projections import (
    extract_component_ids_from_doc,
    extract_component_types_from_doc,
    extract_components_from_doc,
    extract_prose_from_doc,
    has_components_in_doc,
    has_gradeable_components_in_doc,
    parse_and_project,
    validate_components_in_doc,
)


def test_empty_and_prose_only_projections():
    doc = parse_and_project("Just a plain paragraph.\n\nAnother paragraph.")
    assert not has_components_in_doc(doc)
    assert not has_gradeable_components_in_doc(doc)
    assert extract_components_from_doc(doc) == []
    assert extract_component_ids_from_doc(doc) == []
    assert extract_component_types_from_doc(doc) == []
    assert extract_prose_from_doc(doc) == "Just a plain paragraph.\n\nAnother paragraph."
    assert validate_components_in_doc(doc, allowed_types=("mcq", "cloze")) == []


def test_mixed_projections_and_validation():
    text = (
        "Opening text.\n\n"
        "```component:mcq\n"
        "id: q1\n"
        "prompt: What is 2 + 2?\n"
        "options:\n"
        "  - text: 4\n"
        "    correct: true\n"
        "  - text: 5\n"
        "    correct: false\n"
        "```\n\n"
        "Closing text."
    )
    doc = parse_and_project(text, view="learner")
    assert has_components_in_doc(doc)
    assert has_gradeable_components_in_doc(doc)
    assert extract_component_ids_from_doc(doc) == ["q1"]
    assert extract_component_types_from_doc(doc) == ["mcq"]
    prose = extract_prose_from_doc(doc)
    assert "Opening text." in prose
    assert "Closing text." in prose
    assert "component:mcq" not in prose
    assert validate_components_in_doc(doc, allowed_types=("mcq",)) == []

    # Disallowed type without context
    errs = validate_components_in_doc(doc, allowed_types=("cloze",))
    assert len(errs) == 1
    assert "component type 'mcq' is not allowed" in errs[0]

    # Disallowed type with context
    errs_ctx = validate_components_in_doc(
        doc, allowed_types=("cloze",), context_name="CustomCtx"
    )
    assert len(errs_ctx) == 1
    assert "component type 'mcq' is not allowed in CustomCtx" in errs_ctx[0]

"""Tests for the extracted course_html_widgets module."""

from research_team.application.components import ComponentBlock
from research_team.interfaces.web import course_html
from research_team.interfaces.web.course_html import CourseBook, Passage, Resolution
from research_team.interfaces.web.course_html_widgets import (
    _checklist,
    _cloze,
    _compare,
    _definition,
    _evidence,
    _explorer,
    _flashcards,
    _mcq,
    _passages,
    render_checklist,
    render_cloze,
    render_compare,
    render_definition,
    render_evidence,
    render_explorer,
    render_flashcards,
    render_mcq,
    render_passages,
)


def _empty_book() -> CourseBook:
    from uuid import uuid4

    return CourseBook(
        name="Test Book",
        project_id=uuid4(),
        origin="http://test.local",
        exported_at="2026-09-20T00:00:00Z",
        run={},
    )


def test_widget_exports_match_between_modules():
    """Verify that course_html re-exports the exact functions from course_html_widgets."""
    assert course_html._mcq is _mcq is render_mcq
    assert course_html._cloze is _cloze is render_cloze
    assert course_html._flashcards is _flashcards is render_flashcards
    assert course_html._checklist is _checklist is render_checklist
    assert course_html._compare is _compare is render_compare
    assert course_html._definition is _definition is render_definition
    assert course_html._evidence is _evidence is render_evidence
    assert course_html._passages is _passages is render_passages
    assert course_html._explorer is _explorer is render_explorer


def test_direct_widget_rendering():
    book = _empty_book()

    # MCQ
    mcq_block = ComponentBlock(
        type="mcq",
        id="q1",
        raw="",
        lang="yaml",
        data={
            "prompt": "Test prompt?",
            "options": [{"text": "Option A", "correct": True}],
        },
    )
    mcq_html = render_mcq(mcq_block, Resolution(), book)
    assert "data-key='[0]'" in mcq_html
    assert "Option A" in mcq_html

    # Cloze
    cloze_block = ComponentBlock(
        type="cloze",
        id="c1",
        raw="",
        lang="yaml",
        data={"segments": [{"blank": 0, "answer": "cat", "hint": "feline"}]},
    )
    cloze_html = render_cloze(cloze_block, Resolution(), book)
    assert 'data-answer="cat"' in cloze_html
    assert 'placeholder="feline"' in cloze_html

    # Passages
    passage = Passage(source_id="s1", title="Doc 1", text="some quoted text")
    passages_html = render_passages([passage], book)
    assert "some quoted text" in passages_html
    assert "Doc 1" in passages_html

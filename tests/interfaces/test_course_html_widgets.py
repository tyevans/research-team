"""Tests for course HTML widgets and offline rendering."""

import re
from uuid import UUID, uuid4

from research_team.application.components import ComponentBlock
from research_team.application.knowledge.graph_export import build_export
from research_team.application.knowledge.graph_read import (
    GraphEntity,
    GraphRelationship,
)
from research_team.application.knowledge.timeline_read import TimelineBand
from research_team.interfaces.web import course_html
from research_team.interfaces.web.course_html import (
    CourseArea,
    CourseBook,
    Passage,
    Resolution,
    read_course_file,
    render_course_html,
    resolution_key,
)
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
from research_team.interfaces.web.graph_html import color_for_type


def _empty_book() -> CourseBook:
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


PROJECT = UUID("11111111-2222-3333-4444-555555555555")


def _book(source: str, *, resolutions=None, sources=None, path="/course/areas/a/lesson-01.md"):
    """One lesson's markdown as a whole course, ready to render.

    Goes through `parse_document` rather than constructing `ComponentBlock`s,
    so a change to the component grammar that stopped a fence being
    recognised would fail here rather than being papered over by a fixture
    that built the parsed shape by hand.
    """
    lesson = read_course_file(path, source)
    return CourseBook(
        name="Ancient Rome",
        project_id=PROJECT,
        origin="https://research.example",
        exported_at="2026-08-22T00:00:00+00:00",
        run={"run_id": "r-1", "kind": "path", "status": "done"},
        areas=(CourseArea(slug="a", title="Area A", unit=None, lessons=(lesson,)),),
        resolutions=resolutions or {},
        sources=sources or {},
    )


def _rendered(source: str, **kwargs) -> str:
    return render_course_html(_book(source, **kwargs))


# ---- B. the answerable ones ------------------------------------------------


MCQ = """\
Some prose first.

```component:mcq
id: sev-1
prompt: Which severity?
options:
  - text: "SEV-1"
    correct: false
    feedback: "Over-declaring costs trust."
  - text: "SEV-2"
    correct: true
    feedback: "Textbook SEV-2."
rationale: Severity is a communication decision.
```
"""


def test_an_mcq_carries_its_key_so_it_can_be_answered_offline():
    """The key, the options and the per-option feedback, all in the file.

    A rendered question with no key is a printed exam paper, which is the
    thing this export is deliberately not. `data-key` is the one attribute
    the in-page grader reads, so its *value* is asserted rather than its
    presence -- an empty key would score every answer wrong and the widget
    would look entirely normal.
    """
    page = _rendered(MCQ)

    assert "data-key='[1]'" in page
    assert "SEV-2" in page and "SEV-1" in page
    assert "Over-declaring costs trust." in page
    assert "Textbook SEV-2." in page
    assert "Severity is a communication decision." in page
    # The button the reader presses. Without it every assertion above still
    # holds and the question is unanswerable.
    assert 'class="check"' in page


def test_an_mcq_s_feedback_and_rationale_start_hidden():
    """Shown after checking, not before. A page that printed the feedback
    beside the options would give the answer away by which option had the
    approving sentence under it."""
    page = _rendered(MCQ)

    # A `<div>`, not a `<p>`: `_markdown` returns block markup, and a `<p>`
    # around another `<p>` is closed at the inner one's start tag, which puts
    # the feedback outside the hidden element. The attribute was in the markup
    # and the answer was on screen -- found by opening the file, and this is
    # the assertion that would have caught it.
    assert re.search(r'<div class="fb" hidden><p>', page)
    assert re.search(r'<div class="rationale" hidden>', page)


CLOZE = """\
```component:cloze
id: cadence
text: |
  A {{SEV-1}} needs an update every {{15 minutes::how often?}}.
```
"""


def test_a_cloze_carries_every_answer_and_its_hint():
    """`_cloze_segments` splits the text at parse time and `_cloze_strip`
    exists to drop the answers for a learner; this export deliberately keeps
    them, because there is no server to grade against.

    The hint becomes the input's placeholder, which is where the console puts
    it too -- an answer with a hint the reader cannot see is an answer with
    no hint.
    """
    page = _rendered(CLOZE)

    assert 'data-answer="SEV-1"' in page
    assert 'data-answer="15 minutes"' in page
    assert 'placeholder="how often?"' in page


def test_flashcards_keep_their_backs_hidden_until_flipped():
    """A deck whose backs render beside the fronts is a glossary. The back
    has to be *present* (offline) and *hidden* (a card), which is the pair
    this asserts -- either alone passes against a broken widget."""
    page = _rendered(
        """\
```component:flashcards
id: vocab
title: Severity Vocabulary
cards:
  - front: "SEV-1"
    back: Complete loss of a customer-facing service.
```
"""
    )

    assert "Severity Vocabulary" in page
    assert "Complete loss of a customer-facing service." in page
    assert re.search(r'<div class="back" hidden>', page)
    assert 'aria-expanded="false"' in page


def test_a_checklist_renders_tickable_boxes_and_says_it_forgets_them():
    """The second half is the honest part. A box that ticks and silently
    forgets is worse than one that never claimed to remember, so the page
    says so where the reader will see it."""
    page = _rendered(
        """\
```component:checklist
id: first-five
title: "IC: First Five Minutes"
items:
  - text: Assume the IC role out loud
    required: true
    note: Mandatory for SEV-1.
```
"""
    )

    assert 'type="checkbox"' in page
    assert "Assume the IC role out loud" in page
    assert "Mandatory for SEV-1." in page
    assert "Ticks are not saved" in page


# ---- C. the static ones carry their content --------------------------------


def test_a_compare_table_carries_its_rows_and_links_the_heads_that_resolved():
    """Both halves. The rows are the author's own text and were never a
    query, so they must be there whatever the graph said; the heads are the
    only part that was looked up, and one that resolved becomes a link while
    one that did not stays plain text with the table intact -- the registry's
    craft note promises an author exactly that.
    """
    entity_id = str(uuid4())
    page = _rendered(
        """\
```component:compare
id: two-emperors
entities: [Diocletian, Constantine]
rows:
  - label: Reign
    cells: ["284-305", "306-337"]
```
""",
        resolutions={
            resolution_key("/course/areas/a/lesson-01.md", "two-emperors"): Resolution(
                columns=(("Diocletian", entity_id), ("Constantine", None))
            )
        },
    )

    assert "284-305" in page and "306-337" in page
    assert f"/entity/{entity_id}" in page
    # The unresolved head is present and is not a link.
    assert "Constantine" in page
    assert re.search(r"<th>Constantine</th>", page)


def test_a_definition_inlines_its_grounded_text_and_the_passage_behind_it():
    """The whole of provenance offline: the reader compares the account
    against the bytes without leaving the file.

    Asserts the quoted *passage text*, not that a citation element exists. A
    citation that degraded to a bare id would satisfy every structural
    assertion and would be the failure this export exists to avoid.
    """
    key = resolution_key("/course/areas/a/lesson-01.md", "nicene")
    page = _rendered(
        """\
```component:definition
id: nicene
entity: Nicene Christianity
```
""",
        resolutions={
            key: Resolution(
                entity_id="e-1",
                definition="The form of Christianity affirmed at Nicaea.",
                passages=(
                    Passage(
                        source_id="wiki-theodosius",
                        title="Theodosius I",
                        text="made Nicene Christianity the state religion in AD 380",
                    ),
                ),
            )
        },
    )

    assert "The form of Christianity affirmed at Nicaea." in page
    assert "made Nicene Christianity the state religion in AD 380" in page
    # Attributed by title, and linked back to the instance.
    assert "Theodosius I" in page
    assert "https://research.example/#/p/" in page
    assert "wiki-theodosius" in page


def test_evidence_quotes_the_range_rather_than_naming_it():
    page = _rendered(
        """\
```component:evidence
id: state-religion
claim: Theodosius made Nicene Christianity the state religion in AD 380.
sources:
  - source: doc-4f2a
    start: 10
    end: 40
```
""",
        resolutions={
            resolution_key("/course/areas/a/lesson-01.md", "state-religion"): Resolution(
                passages=(
                    Passage(
                        source_id="doc-4f2a",
                        title="Edict of Thessalonica",
                        text="the quoted bytes",
                    ),
                )
            )
        },
    )

    assert "the quoted bytes" in page
    assert "Edict of Thessalonica" in page
    assert "Theodosius made Nicene Christianity" in page


def test_an_unresolvable_citation_is_named_rather_than_left_empty():
    """An `evidence` block whose source could not be read renders a sentence
    saying so. An empty widget here is indistinguishable from an authoring
    mistake, and the reader has no way to ask which it was."""
    page = _rendered(
        """\
```component:evidence
id: state-religion
claim: A claim.
sources:
  - source: doc-missing
```
""",
        resolutions={
            resolution_key("/course/areas/a/lesson-01.md", "state-religion"): Resolution(
                absent="no readable passage was found behind doc-missing."
            )
        },
    )

    assert "no readable passage was found behind doc-missing." in page
    assert "A claim." in page


# ---- D. the drawings -------------------------------------------------------


def _entity(name: str, entity_type: str = "concept", inferred: bool = False) -> GraphEntity:
    return GraphEntity(
        entity_id=str(uuid4()), name=name, entity_type=entity_type, inferred=inferred
    )


def test_a_lesson_graph_draws_as_inline_svg_with_its_labels_as_text():
    """No canvas, no script, and the names selectable.

    The label assertion is the load-bearing one: a figure that draws its
    circles and drops its text is a picture of grey dots, and it looks like a
    graph until you try to read it.
    """
    root = _entity("Constantine")
    other = _entity("Diocletian")
    graph = build_export(
        (root, other),
        (
            GraphRelationship(
                source_id=root.entity_id,
                target_id=other.entity_id,
                relationship_type="succeeded",
            ),
        ),
        title="Constantine",
        scope="lesson",
        limit=60,
        truncated=False,
    )
    page = _rendered(
        """\
```component:graph
id: around
entity: Constantine
depth: 1
```
""",
        resolutions={
            resolution_key("/course/areas/a/lesson-01.md", "around"): Resolution(
                entity_id=root.entity_id, graph=graph
            )
        },
    )

    assert "<svg" in page and "<canvas" not in page
    assert ">Constantine</text>" in page
    assert ">Diocletian</text>" in page
    assert "<line" in page
    # `entity-colors.ts`'s hash, against a literal rather than against a
    # second call to the function under test. The console and the export must
    # colour a `concept` the same or the two drawings of one graph look like
    # drawings of two.
    assert color_for_type("concept") == "#5f7d8c"
    assert "#5f7d8c" in page


def test_a_timeline_draws_a_bar_per_band_and_reports_what_is_missing():
    """`undated_count` is not decoration. A timeline showing three bars with
    no denominator reads as "this project contains three things"."""
    page = _rendered(
        """\
```component:timeline
id: fourth-century
entity_type: Person
```
""",
        resolutions={
            resolution_key("/course/areas/a/lesson-01.md", "fourth-century"): Resolution(
                bands=(
                    TimelineBand(
                        entity_id="e-1",
                        name="Constantine",
                        entity_type="Person",
                        extent="AD 306-337",
                        start="0306-01-01T00:00:00+00:00",
                        end="0337-01-01T00:00:00+00:00",
                        precision="YEAR",
                        uncertainty="EXACT",
                    ),
                ),
                undated=41,
            )
        },
    )

    assert "<svg" in page
    assert "<rect" in page
    assert "AD 306-337" in page
    assert "41 dated nothing" in page


def test_an_explorer_names_what_it_was_and_never_renders_an_empty_box():
    """The one type that cannot be frozen.

    Its prompt survives -- the registry's craft note says the prompt is the
    whole difference between an explorer and a timeline -- and the controls
    are reported absent by name, with the axes the reader was invited to
    move. Rendering the last result instead would be a figure the author
    never chose, under a prompt asking the reader to change controls that are
    not there.
    """
    page = _rendered(
        """\
```component:explorer
id: fourth-century-explorer
over: timeline
entity_type: Person
vary: [entity_type, window]
prompt: Narrow to Emperors and pull the window back.
```
"""
    )

    assert "Narrow to Emperors and pull the window back." in page
    assert "The controls" in page
    assert "entity_type, window" in page
    assert "/timeline" in page

"""What a course looks like once it has left the building.

Two halves, matching the module's own split. Most of this file drives
`render_course_html` directly over a hand-built `CourseBook`, because the part
worth pinning is the *per-widget freeze decision* -- whether an mcq is still
answerable, whether a citation still carries its passage -- and none of that
needs a graph store. The last section drives the route, where the only thing
that can break is the wiring.

Every assertion here is about content rather than about the response being
well-formed. `CLAUDE.md`'s *Events* section names the shape to avoid: a
"the export succeeded" assertion passes against an export that produced an
empty page, and the whole risk in this feature is a widget that renders as a
box with nothing in it.

What is deliberately not here: whether the page *works* in a browser. Every
interactive widget in this file is a few lines of vanilla JavaScript, and
nothing below runs any of it -- these tests assert that the key, the answers
and the handlers are present in the markup. The handlers were verified by
opening a real export in Chromium (see the commit message); jsdom would not
have added to that, and asserting on a `<script>` body's text would pin the
implementation rather than the behaviour.
"""

import re
from uuid import UUID, uuid4

import pytest

from research_team.application.components import REGISTRY, parse_document
from research_team.application.graph_export import build_export
from research_team.application.graph_read import GraphEntity, GraphRelationship
from research_team.application.timeline_read import TimelineBand
from research_team.interfaces.web.course_html import (
    _RENDERERS,
    MAX_QUOTE_CHARS,
    CourseArea,
    CourseBook,
    Passage,
    Resolution,
    quote_passage,
    read_course_file,
    render_course_html,
    resolution_key,
    title_of,
)
from research_team.interfaces.web.graph_html import color_for_type

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


# ---- A. every type has a decision -----------------------------------------


def test_every_registered_component_type_has_a_freeze_decision():
    """The import-time assertion in `course_html`, restated as a test.

    Would pass with the module's own `assert` deleted -- it is the same
    comparison -- and it is here anyway because the failure mode is worth
    naming twice: an eleventh component type added to `REGISTRY` with no
    renderer exports as a `<pre>` of its own YAML, which is legible enough
    that nobody reading one export would notice a widget had stopped being a
    widget.
    """
    assert set(_RENDERERS) == set(REGISTRY)


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


# ---- E. prose, provenance and the page -------------------------------------


def test_a_source_reference_in_prose_becomes_a_titled_link_not_a_bare_id():
    """`[[src:...]]` is the citation grammar the model is told to write.

    Its id resolves to nothing outside this system, so a reference that came
    out as `wiki-trajan` would be a citation the reader cannot read. The
    title is the assertion; the link is the other half.
    """
    page = _rendered(
        "Theodosius acted in 380 [[src:wiki-theodosius@252]].",
        sources={"wiki-theodosius": "Theodosius I — Wikipedia"},
    )

    assert "Theodosius I — Wikipedia" in page
    assert "?t=252" in page
    assert "4:12" in page
    assert "[[src:" not in page


def test_a_reference_to_a_source_the_export_could_not_name_still_links():
    """Degrades to the id as its own label rather than to nothing. The
    console does the same for a source it cannot name, and a reference that
    vanished would be worse than one a reader can report."""
    page = _rendered("See [[src:wiki-trajan]].")

    assert "wiki-trajan" in page
    assert "/doc/wiki-trajan" in page


def test_markdown_in_a_lesson_renders_server_side():
    """No markdown library in the file. The subset is `_markdown`'s and the
    gap is stated there; what is asserted is that the common shapes an
    authoring prompt produces come out as markup rather than as asterisks."""
    page = _rendered(
        "# Lesson one\n\n## Desired results\n\n"
        "Learners will **understand** the shift.\n\n- one\n- two\n"
    )

    assert "Desired results</h4>" in page  # `##` demoted below the lesson's `<h3>`
    assert "<strong>understand</strong>" in page
    assert "<li>one</li><li>two</li>" in page


def test_a_file_s_own_title_heading_is_not_printed_twice():
    """The section already carries the title, and every authored unit and
    lesson opens with `# <title>` because the prompts ask for it.

    Found by opening a real export -- and invisible to a test asserting the
    title is present, because it is present, twice. The second half of this
    assertion is what stops the fix over-reaching: a heading that says
    something else is the author's and stays.
    """
    page = _rendered("# Lesson eight\n\nProse.\n\n## A second heading\n")

    # Once in the contents, once as the lesson's own `<h3>`, and not a third
    # time as the `<h4>` the body's `# Lesson eight` would otherwise produce.
    assert page.count("Lesson eight") == 2
    assert "A second heading" in page


def test_html_written_into_a_lesson_is_escaped_rather_than_passed_through():
    """Lesson prose is model output and this file opens from `file://`.
    Would pass with the escaping removed if the fixture used a tag a browser
    ignores, which is why it uses a script tag."""
    page = _rendered("A tag: <script>alert(1)</script> in prose.")

    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_a_broken_component_is_shown_rather_than_dropped():
    """An export of a lesson with a broken block must not look like an export
    of a lesson without one."""
    page = _rendered(
        """\
```component:mcq
id: broken
prompt: Only one option.
options:
  - text: "Alone"
    correct: true
```
"""
    )

    assert "did not parse" in page
    assert "Only one option." in page  # the raw body, shown


def test_an_unknown_component_type_shows_its_source():
    page = _rendered("```component:hologram\nid: x\nfoo: bar\n```\n")

    assert "is not a component this build knows" in page
    assert "foo: bar" in page


def test_the_page_pulls_in_nothing_from_outside_itself():
    """The constraint the whole feature rests on. Asserted by absence of the
    four ways a page fetches: a script `src`, a stylesheet `link`, an `img`,
    and an `@import`. A `<link rel=icon>` would trip this too, which is
    correct -- it is a request."""
    page = render_course_html(_book(MCQ + CLOZE))

    assert "<script src" not in page
    assert "<link" not in page
    assert "<img" not in page
    assert "@import" not in page
    assert "fonts.googleapis" not in page


def test_the_header_says_the_answers_are_in_the_file():
    """A property of the artifact that cannot be fixed in code, so it is
    stated to the person holding it."""
    page = _rendered(MCQ)

    assert "teaching copy" in page
    assert "exam paper" in page


def test_the_contents_list_every_area_and_lesson_in_teaching_order():
    lessons = tuple(
        read_course_file(f"/course/areas/a/lesson-0{n}.md", f"# Lesson {n}\n")
        for n in (1, 2, 3)
    )
    book = CourseBook(
        name="Rome",
        project_id=PROJECT,
        origin="https://research.example",
        exported_at="2026-08-22T00:00:00+00:00",
        run={"run_id": "r-1"},
        areas=(CourseArea(slug="roman-law", title="Roman law", unit=None, lessons=lessons),),
    )

    page = render_course_html(book)

    assert page.index("Lesson 1") < page.index("Lesson 2") < page.index("Lesson 3")
    assert 'href="#roman-law-l2"' in page
    assert 'id="roman-law-l2"' in page


def test_two_lessons_may_hold_a_component_with_the_same_id():
    """The reason `resolutions` is keyed by path *and* id.

    Ids are unique within a document and nothing enforces it across a course,
    so two lessons that both define `nicene-christianity` are ordinary. Keyed
    by id alone they would share one resolution, which is a wrong definition
    under the second heading rather than a missing one -- and nothing about
    the page would look wrong.
    """
    source = "```component:definition\nid: shared\nentity: Nicaea\n```\n"
    first = read_course_file("/course/areas/a/lesson-01.md", source)
    second = read_course_file("/course/areas/a/lesson-02.md", source)
    book = CourseBook(
        name="Rome",
        project_id=PROJECT,
        origin="https://research.example",
        exported_at="2026-08-22T00:00:00+00:00",
        run={},
        areas=(CourseArea(slug="a", title="A", unit=None, lessons=(first, second)),),
        resolutions={
            resolution_key(first.path, "shared"): Resolution(definition="The first account."),
            resolution_key(second.path, "shared"): Resolution(
                definition="The second account."
            ),
        },
    )

    page = render_course_html(book)

    assert "The first account." in page
    assert "The second account." in page


# ---- F. the small pure pieces ---------------------------------------------


def test_a_quote_is_clamped_to_the_document_and_to_the_ceiling():
    """`evidence` accepts offsets up to 100,000,000, so a mistyped `end`
    would otherwise inline a whole document into a lesson."""
    text = "x" * (MAX_QUOTE_CHARS + 500)

    span, truncated = quote_passage(text, 0, 100_000_000)

    assert len(span) == MAX_QUOTE_CHARS
    assert truncated is True


def test_a_quote_entirely_past_the_end_is_empty_rather_than_an_error():
    span, truncated = quote_passage("short", 900, 1000)

    assert span == ""
    assert truncated is False


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("---\ntitle: From frontmatter\n---\n\n# From heading\n", "From frontmatter"),
        ("Some prose.\n\n## From heading\n", "From heading"),
        ("Nothing but prose.\n", "lesson-01"),
    ],
)
def test_a_file_s_title_falls_back_through_frontmatter_heading_filename(source, expected):
    """Parametrised over the three cases that pick different branches, not
    over three lessons that all have a `# heading` -- `CLAUDE.md`'s rule
    about tests whose inputs and branches were chosen in the same hour."""
    path = "/course/areas/a/lesson-01.md"

    assert title_of(path, parse_document(source, path=path)) == expected

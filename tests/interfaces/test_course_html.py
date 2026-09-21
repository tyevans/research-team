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

from uuid import UUID

import pytest

from research_team.interfaces.web.course_html import (
    _RENDERERS,
    MAX_QUOTE_CHARS,
    CourseArea,
    CourseBook,
    Resolution,
    quote_passage,
    read_course_file,
    render_course_html,
    resolution_key,
    title_of,
)
from research_team.platform.components import REGISTRY, parse_document

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

CLOZE = """\
```component:cloze
id: cadence
text: |
  A {{SEV-1}} needs an update every {{15 minutes::how often?}}.
```
"""


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

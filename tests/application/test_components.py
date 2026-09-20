"""Reading a lesson: what a component block is, and what happens when it is wrong.

The parser's contract is stated once, in three parts, and nearly every test
here is an instance of one of them.

**Totality.** A document is authored by a model, so malformed input is the
expected case rather than the exceptional one. `parse_document` never raises.
The property test at the bottom is the real statement of this; the examples
above it pin the specific shapes we know a model produces.

**Degradation is per-block, never per-document.** One bad component must cost
exactly one component. A lesson that renders eleven widgets and one error panel
is enormously more useful than a stack trace, and the difference between those
two outcomes is entirely a matter of where the `try` sits. Hence
`test_one_malformed_component_does_not_cost_the_others`.

**Unknown is not an error.** An unrecognised type renders as a labelled code
block -- exactly what the client does with it today, and exactly what the
mermaid pattern promises. This is what keeps the registry free to grow without
every older reader treating a newer lesson as broken.
"""

import pytest
from hypothesis import assume, given
from hypothesis import strategies as st

from research_team.application.components import (
    ComponentBlock,
    MarkdownBlock,
    component_reference,
    derive_id,
    parse_document,
    validation_report,
)

MCQ = """\
```component:mcq
id: sev-classification-1
prompt: |
  What severity?
options:
  - text: "SEV-1"
    correct: false
    feedback: "No data loss."
  - text: "SEV-2"
    correct: true
    feedback: "Textbook SEV-2."
rationale: |
  Severity is a communication decision.
```
"""


def _components(doc):
    return [b for b in doc.blocks if isinstance(b, ComponentBlock)]


def test_a_document_with_no_components_is_one_markdown_block():
    doc = parse_document("# Heading\n\nSome prose.\n")
    assert [type(b) for b in doc.blocks] == [MarkdownBlock]
    assert doc.blocks[0].text == "# Heading\n\nSome prose.\n"


def test_a_component_fence_becomes_a_component_block():
    doc = parse_document(MCQ)
    (component,) = _components(doc)
    assert component.type == "mcq"
    assert component.id == "sev-classification-1"
    assert component.errors == ()
    assert component.data["options"][1]["correct"] is True


def test_prose_around_a_component_is_preserved_in_order():
    doc = parse_document(f"Before.\n\n{MCQ}\nAfter.\n")
    kinds = [b.kind for b in doc.blocks]
    assert kinds == ["markdown", "component", "markdown"]
    assert doc.blocks[0].text.strip() == "Before."
    assert doc.blocks[2].text.strip() == "After."


def test_a_bare_type_name_is_still_a_code_block():
    """`component:` is the namespace, and it is the whole point of the prefix.

    An info string of `mcq` could plausibly become a language tag someone adds
    to a highlighter later. Claiming it here would mean a lesson's meaning
    depended on which of the two shipped first.
    """
    doc = parse_document("```mcq\nid: x\n```\n")
    assert _components(doc) == []


def test_an_unknown_type_degrades_to_a_labelled_block_without_error():
    doc = parse_document("```component:widget-from-the-future\nwhatever: 1\n```\n")
    (component,) = _components(doc)
    assert component.unknown is True
    assert component.errors == ()
    assert component.raw == "whatever: 1"
    assert component.lang == "component:widget-from-the-future"


def test_a_known_type_with_unparseable_yaml_keeps_its_raw_body():
    doc = parse_document("```component:mcq\nprompt: : :\n```\n")
    (component,) = _components(doc)
    assert component.unknown is False
    assert component.errors != ()
    assert component.raw == "prompt: : :"


def test_a_known_type_missing_a_required_field_reports_the_field():
    doc = parse_document("```component:mcq\nid: no-options\nprompt: Hi\n```\n")
    (component,) = _components(doc)
    assert [e.path for e in component.errors] == ["options"]
    assert "required" in component.errors[0].message


def test_a_body_that_is_not_a_mapping_is_an_error_not_a_crash():
    doc = parse_document("```component:mcq\n- just\n- a list\n```\n")
    (component,) = _components(doc)
    assert component.errors != ()


def test_one_malformed_component_does_not_cost_the_others():
    """The whole degradation contract, in one assertion."""
    doc = parse_document(f"{MCQ}\n```component:mcq\nbroken: [\n```\n\n{MCQ}")
    good, bad, also_good = _components(doc)
    assert good.errors == () and also_good.errors == ()
    assert bad.errors != ()


def test_frontmatter_is_lifted_off_the_document():
    doc = parse_document("---\ntype: lesson\nstage: 3\n---\n\n# Body\n")
    assert doc.frontmatter == {"type": "lesson", "stage": 3}
    assert "type: lesson" not in doc.blocks[0].text


def test_a_document_with_no_frontmatter_has_none_rather_than_empty():
    """`None` and `{}` mean different things: absent versus present-and-bare."""
    doc = parse_document("# Body\n")
    assert doc.frontmatter is None


def test_tilde_fences_open_components_too():
    doc = parse_document("~~~component:checklist\nid: c\nitems:\n  - text: Go\n~~~\n")
    (component,) = _components(doc)
    assert component.type == "checklist"
    assert component.errors == ()


def test_a_longer_fence_contains_a_shorter_one():
    """A component example inside a documentation block is not a component."""
    doc = parse_document("````markdown\n```component:mcq\nid: x\n```\n````\n")
    assert _components(doc) == []


def test_an_info_string_with_extra_words_still_opens_a_fence():
    """The scanner and the client must agree on where a code block starts.

    `app.js` does not anchor its fence pattern, so ```` ```js {1,3} ```` opens a
    block in the browser. If this scanner disagreed and read that line as prose,
    it would keep scanning *inside* the code sample -- and a `component:` fence
    shown as an example within it would be extracted as a real component.
    """
    doc = parse_document("```js {1,3}\n```component:mcq\nid: x\n```\n")
    assert _components(doc) == []


def test_a_code_fence_survives_the_round_trip_unaltered():
    """Non-component fences are handed back verbatim, attributes and all."""
    source = "```js {1,3} title=demo\nconst a = 1;\n```\n"
    doc = parse_document(source)
    assert doc.blocks[0].text == source


def test_an_unclosed_component_fence_still_parses_what_it_has():
    doc = parse_document("```component:checklist\nid: c\nitems:\n  - text: Go\n")
    (component,) = _components(doc)
    assert component.errors == ()


def test_a_missing_id_is_derived_and_warned_about():
    """A derived id is stable across re-renders, and only across re-renders.

    It is `sha256(path + index)`, so an edit *above* the component does not
    move it but an insert does. That is worth a warning rather than an error:
    the lesson renders, and the author is told the one thing that will bite
    them later.
    """
    source = "```component:checklist\nitems:\n  - text: Go\n```\n"
    doc = parse_document(source, path="/course/03.md")
    (component,) = _components(doc)
    assert component.id == derive_id("/course/03.md", 0)
    assert component.errors == ()
    assert any("id" in w.path for w in component.warnings)


def test_derived_ids_differ_by_position_and_by_path():
    assert derive_id("/a.md", 0) != derive_id("/a.md", 1)
    assert derive_id("/a.md", 0) != derive_id("/b.md", 0)


def test_a_duplicate_id_is_reported_because_learner_state_keys_on_it():
    doc = parse_document(f"{MCQ}\n{MCQ}")
    first, second = _components(doc)
    assert first.warnings == ()
    assert any("duplicate" in w.message for w in second.warnings)


# --- properties -----------------------------------------------------------
#
# Built from fragments rather than an alphabet so fences, colons and frontmatter
# markers are generated as units. Free text alone essentially never produces a
# well-formed fence, and it is the fence handling that has the sharp edges.
DOCUMENT = st.lists(
    st.sampled_from(
        [
            "# Heading\n",
            "prose\n",
            "\n",
            "---\n",
            "```\n",
            "````\n",
            "~~~\n",
            "```component:mcq\n",
            "```component:unknown-type\n",
            "~~~component:checklist\n",
            "id: x\n",
            "prompt: |\n",
            "  text\n",
            "- item\n",
            ": : :\n",
            "\t\n",
        ]
    ),
    max_size=25,
).map("".join)


@given(DOCUMENT)
def test_parsing_is_total(text):
    """No input raises. The corpus is model-authored; this is not optional."""
    doc = parse_document(text, path="/course/01.md")
    assert doc.blocks is not None


@given(DOCUMENT)
def test_every_component_block_is_identifiable_and_degradable(text):
    """Whatever comes out, the renderer can dispatch on it.

    Three invariants the client relies on and cannot defend itself against: a
    type is always present, an id is always present (derived if absent) because
    it is the key learner state will hang off, and the raw body survives so an
    error panel has something to show.
    """
    for block in parse_document(text, path="/course/01.md").blocks:
        if isinstance(block, ComponentBlock):
            assert block.type
            assert block.id
            assert block.raw is not None


@given(DOCUMENT)
def test_no_content_is_silently_dropped(text):
    """Every line of the source lands in some block.

    A viewer that quietly eats a line is worse than one that renders it wrong,
    because nothing on the page says anything is missing.

    Frontmatter is excluded rather than asserted over: it is lifted off the
    document by design, so its lines legitimately do not appear in any block.
    """
    assume(not text.startswith("---"))
    doc = parse_document(text, path="/course/01.md")
    seen = "".join(b.text if isinstance(b, MarkdownBlock) else b.raw for b in doc.blocks)
    for line in text.splitlines():
        if line.strip() and not line.lstrip().startswith(("```", "~~~", "---")):
            assert line.strip() in seen


# --- authoring feedback ---------------------------------------------------


def test_a_clean_document_reports_nothing():
    assert validation_report(parse_document(MCQ)) == ""


def test_the_report_names_the_component_the_field_and_the_problem():
    report = validation_report(parse_document("```component:mcq\nid: q\nprompt: Hi\n```\n"))
    assert "'q'" in report and "options" in report and "required" in report


def test_an_unknown_type_is_not_reported_as_a_problem():
    """Registering a type later must not retroactively make old lessons wrong."""
    assert validation_report(parse_document("```component:from-the-future\nx: 1\n```\n")) == ""


def test_the_generated_reference_covers_every_registered_type():
    """The reference is generated so it cannot drift from the schemas.

    Each example is parsed back through the parser, which makes this a real
    check on the registry rather than a check that some strings exist: an
    example that stopped satisfying its own schema fails here.
    """
    from research_team.application.components import REGISTRY

    reference = component_reference()
    for name, component in REGISTRY.items():
        assert name in reference
        parsed = parse_document(component.example)
        assert parsed.components, f"{name}'s example does not parse as a component"
        assert parsed.components[0].errors == (), f"{name}'s own example is invalid"
        assert parsed.components[0].type == name


def test_the_reference_carries_each_type_s_craft_notes():
    """The generated reference is the only place either agent learns to write
    a good item, so craft travels with syntax or not at all.

    Reverting `craft` to a field nothing renders leaves this red: the strings
    are in the registry either way, and `component_reference` is what has to
    put them in front of a model.
    """
    reference = component_reference(only=["mcq"])

    assert "distractor" in reference
    # "feedback" alone doesn't discriminate: mcq's summary and example both
    # already said it before craft existed, so it passes with craft rendered
    # or reverted. This phrase is only in the craft note itself.
    assert "misunderstanding that makes it attractive" in reference


def test_craft_notes_are_scoped_to_the_types_asked_for():
    """`only` narrows craft the same way it narrows examples -- showing a stage
    how to write a good cloze it was told not to use is the same mistake the
    `only` parameter exists to prevent."""
    reference = component_reference(only=["flashcards"])

    assert "one fact per card" in reference.lower()
    assert "distractor" not in reference


# --- B29: the parse was nine times slower than it needed to be -------------
#
# B29 recorded "the parse is not cached, though the cache key is exact", and
# deferred the cache because nothing had measured it. Measuring it found
# something better than a cache: `yaml.safe_load` binds PyYAML's *pure-Python*
# scanner even when the libyaml extension is installed, and on this machine the
# C loader parses the same component body ~9x faster. A cache over the slow
# loader would have bought less and cost an invalidation story.
#
# So these pin the substitution rather than a speed: that we take the C loader
# when it exists, that it is still a *safe* loader, and that a malformed body
# still degrades into a Note rather than an exception.


def test_the_c_yaml_loader_is_used_when_the_extension_is_available():
    """Not a benchmark -- benchmarks are flaky on a loaded machine. This pins
    the decision that produced the speedup, which is the durable part."""
    import yaml

    from research_team.application.components import _YAML_LOADER

    if hasattr(yaml, "CSafeLoader"):
        assert _YAML_LOADER is yaml.CSafeLoader
    else:
        assert _YAML_LOADER is yaml.SafeLoader


def test_the_loader_is_still_a_safe_one():
    """The whole point of `safe_load` is that a lesson written by a model cannot
    construct arbitrary Python. Swapping the loader for speed must not swap that
    away -- `yaml.CLoader` is also faster and would."""
    doc = parse_document(
        "```component:mcq\n!!python/object/apply:os.system ['echo pwned']\n```\n"
    )
    block = doc.blocks[0]
    assert block.kind == "component"
    assert block.errors, "an unsafe tag must be refused, not constructed"


@pytest.mark.parametrize(
    "body",
    [
        "options: [1, 2",
        "a:\n- b\n  c: 1",
        "*undefined",
        "a: |\n\ttab",
    ],
)
def test_a_malformed_body_still_degrades_rather_than_raising(body):
    """The C loader words its complaints differently from the pure-Python one.
    What must not change is that every one of them arrives as a Note on the
    block -- the authoring feedback loop reads these."""
    doc = parse_document(f"```component:mcq\n{body}\n```\n")
    block = doc.blocks[0]
    assert block.kind == "component"
    assert block.errors
    message = str(block.errors[0])
    assert "could not parse the YAML body" in message
    # Non-empty detail: an error that says only "could not parse" tells the
    # model nothing it can act on.
    assert message.split("--", 1)[1].strip()


def test_a_required_text_field_that_is_present_but_empty_is_warned_about():
    """`required=True` asks whether the key is there, not whether it says anything.

    `text()` accepts `""` on purpose -- it rejects structure, not emptiness --
    so `prompt: ""` validated as present and nothing anywhere complained. It
    mattered less while the browser drew a padded grey "(empty file)" in its
    place; now that `Prose` renders blank text as nothing, this warning is the
    only thing that says a required field was left empty.

    Red against the build before this hook: zero warnings.
    """
    source = (
        "```component:mcq\n"
        'id: m\nprompt: ""\n'
        "options:\n"
        '  - text: ""\n'
        "    correct: true\n"
        '  - text: "The Rhine frontier"\n'
        "    correct: false\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert [str(note) for note in block.warnings] == [
        "prompt: required, and present but empty; it renders as nothing",
        "options[0].text: required, and present but empty; it renders as nothing",
    ]

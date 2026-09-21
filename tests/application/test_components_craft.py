"""Craft notes, reference generation, YAML loader safety, and validation reports."""

import pytest

from research_team.application.components import (
    component_reference,
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

    from research_team.application.components.components import _YAML_LOADER

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

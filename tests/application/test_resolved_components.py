"""What holds for every resolved component, stated over the class.

A resolved component carries a *reference* and fetches its data in the
browser. Structurally it is the inverse of `gradeable`: nothing is withheld,
nothing is graded, and the YAML body is a query rather than content.

These tests register a throwaway type rather than asserting against
`definition` or `graph`, because the claim is about the class. A test written
against one member passes for a build where a second member quietly grew a
`strip`, which is exactly the regression worth catching -- see the module
docstring on `components.py` for why "the learner projection is identity" is
the kind of property that stops holding silently.
"""

import pytest

from research_team.application.components import (
    REGISTRY,
    ComponentType,
    Spec,
    integer_between,
    parse_document,
    project,
    string_list,
    string_subset,
    text,
    validation_report,
)

PROBE = """\
```component:probe
id: p1
entity: An Entity No Extraction Has Ever Seen
```
"""


@pytest.fixture
def probe(monkeypatch):
    """A resolved type that exists only for the duration of one test.

    `monkeypatch.setitem` restores the registry afterwards, so a failure here
    cannot leak a fake type into another test's `component_reference()`.
    """
    monkeypatch.setitem(
        REGISTRY,
        "probe",
        ComponentType(
            name="probe",
            version=1,
            summary="A probe.",
            example="```component:probe\nid: p1\nentity: Something\n```",
            fields={"entity": Spec(text, required=True)},
            resolved=True,
        ),
    )
    return REGISTRY["probe"]


def test_a_resolved_type_withholds_nothing_and_grades_nothing(probe):
    """Both are defaults on `ComponentType`, so this is red only against a
    build where someone gave a resolved type an answer key -- which is the
    point: there is no answer to withhold, the data is the project's own."""
    assert probe.withheld == ()
    assert probe.gradeable is False
    assert probe.strip is None


def test_the_learner_projection_of_a_resolved_component_is_identity(probe):
    """The property `components.py`'s docstring warns stops holding silently.

    Red against a build that gives a resolved type a `strip`, and red against
    one that projects `withheld` non-empty for it.
    """
    document = parse_document(PROBE, path="probe.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert author["data"] == learner["data"]
    assert learner["withheld"] == []
    assert learner["gradeable"] is False


def test_a_resolved_component_says_so_on_the_wire(probe):
    """The client decides whether to thread `projectId` into a renderer on
    this flag rather than on a name list. Red against a `_component_json`
    that does not carry it."""
    block = project(parse_document(PROBE, path="probe.md"))["blocks"][0]

    assert block["resolved"] is True


def test_a_self_contained_component_is_not_resolved():
    """The other half of the flag, so a build that hardcodes `True` fails."""
    source = "```component:flashcards\nid: deck\ncards:\n  - front: a\n    back: b\n```\n"

    block = project(parse_document(source))["blocks"][0]

    assert block["resolved"] is False


def test_validation_accepts_a_reference_that_cannot_possibly_exist(probe):
    """The honest assertion, and the one the spec's section 2 asks for by name.

    `validation_report` runs on the server at parse time with no graph handle,
    so a name matching nothing is a *render* state and not a parse error. The
    natural instinct is to add an existence check to the validator; it cannot
    be written honestly, and this test is what makes adding one fail.
    """
    document = parse_document(PROBE, path="probe.md")

    assert validation_report(document) == ""
    assert document.components[0].ok is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, []),
        (2, []),
        (3, ["depth: expected a whole number from 1 to 2, got 3"]),
        (0, ["depth: expected a whole number from 1 to 2, got 0"]),
        ("two", ["depth: expected a whole number from 1 to 2, got 'two'"]),
        (True, ["depth: expected a whole number from 1 to 2, got True"]),
    ],
)
def test_integer_between_bounds_a_field_against_the_server_s_own_limit(value, expected):
    """`True` is in the list deliberately: `isinstance(True, int)` is true in
    Python, so a naive check accepts `depth: true` and sends `1` to a route
    that never saw the author's intent."""
    assert [str(note) for note in integer_between(1, 2)(value, "depth")] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["A", "B"], []),
        (["A"], ["entities: expected at least 2 entries, got 1"]),
        ("A", ["entities: expected a list, got text"]),
        ([{"name": "A"}, "B"], ["entities[0]: expected text, got mapping"]),
    ],
)
def test_string_list_checks_each_entry_by_its_own_path(value, expected):
    assert [str(note) for note in string_list(minimum=2)(value, "entities")] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["entity_type"], []),
        (["entity_type", "window"], []),
        ([], ["vary: expected at least 1 entry, got 0"]),
        ("window", ["vary: expected a list, got text"]),
        (["window", "topic"], ["vary[1]: expected one of entity_type, window, got 'topic'"]),
        ([{"axis": "window"}], ["vary[0]: expected text, got mapping"]),
    ],
)
def test_string_subset_names_the_allowed_values_at_the_offending_subscript(value, expected):
    """A list checker that reports `vary: bad axis` rather than `vary[1]` sends
    a model back to re-read a list it mostly got right. The path is the whole
    reason validation feedback is hand-written here -- see `components.py`'s
    module docstring.

    The mapping case is delegated to `text` rather than reported as "not one
    of": `{axis: window}` is a shape mistake and `topic` is a vocabulary
    mistake, and telling an author their mapping is not in a list of two
    strings is a diagnosis of the wrong problem.
    """
    check = string_subset("entity_type", "window")

    assert [str(note) for note in check(value, "vary")] == expected

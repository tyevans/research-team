"""Tests for resolved component types: definition, evidence, graph,
timeline, and compare."""

import pytest

from research_team.application.components import (
    component_reference,
    parse_document,
    project,
)
from research_team.application.graph_read import MAX_NEIGHBORHOOD_DEPTH
from research_team.application.timeline_read import MAX_TIMELINE_BANDS

DEFINITION = """\
```component:definition
id: nicene
entity: Nicene Christianity
```
"""


def test_a_definition_carries_its_reference_through_both_views():
    """The body is a query, so there is nothing to strip and nothing to grade.

    Red against a `definition` entry that sets `gradeable=True` or a `strip`,
    both of which are the shape every other registered type has and therefore
    the shape a copy-paste addition would arrive in.
    """
    document = parse_document(DEFINITION, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert author["data"]["entity"] == "Nicene Christianity"
    assert learner["data"] == author["data"]
    assert learner["resolved"] is True
    assert learner["gradeable"] is False


def test_a_definition_without_an_entity_says_which_field_is_missing():
    source = "```component:definition\nid: nope\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == ["entity: required field missing"]


def test_a_definition_may_pin_an_ambiguous_name_with_an_entity_id():
    """`entity_id` is the escape hatch, and it is *not* a warned-about unknown
    key -- a human copying one out of the console must not be told the field
    they were told to use is unrecognised."""
    source = (
        "```component:definition\n"
        "id: c\n"
        "entity: Constantine\n"
        "entity_id: 8f2c1e00-0000-4000-8000-000000000000\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert block.warnings == ()
    assert block.data["entity_id"] == "8f2c1e00-0000-4000-8000-000000000000"


def test_the_generated_reference_renders_the_definition_example():
    """`component_reference` is what the authoring model reads. A type whose
    example does not appear in it is a type the model will never write."""
    reference = component_reference(only=["definition"])

    assert "component:definition" in reference
    assert "entity:" in reference


EVIDENCE = """\
```component:evidence
id: state-religion
claim: |
  Theodosius made Nicene Christianity the state religion in AD 380.
sources:
  - source: doc-1
    start: 4120
    end: 4380
```
"""


def test_evidence_carries_its_claim_and_ranges_through_both_views():
    """Red against an `evidence` entry that strips or grades.

    There is no answer key to withhold here -- the claim and the passages
    behind it are the whole body -- and the widget's entire value is that the
    reader compares the two, so a learner who sees less than the author does
    cannot do the one thing this component exists for.
    """
    document = parse_document(EVIDENCE, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["sources"][0] == {"source": "doc-1", "start": 4120, "end": 4380}
    assert learner["resolved"] is True


def test_evidence_needs_at_least_one_source():
    """A claim with no passage behind it is prose wearing a widget's clothes,
    and the widget's entire value is that the reader can check it."""
    source = "```component:evidence\nid: e\nclaim: Something happened.\nsources: []\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "sources: expected at least 1 entry, got 0"
    ]


def test_evidence_names_the_offending_source_by_its_subscript():
    source = (
        "```component:evidence\n"
        "id: e\n"
        "claim: Something happened.\n"
        "sources:\n"
        "  - start: 10\n"
        "    end: 20\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "sources[0].source: required field missing"
    ]


def test_evidence_refuses_a_negative_offset():
    """Red against `Spec(text)` on the offsets, which would accept `start: -5`
    and send it to a route that clamps it to 0 without saying so."""
    source = (
        "```component:evidence\n"
        "id: e\n"
        "claim: Something happened.\n"
        "sources:\n"
        "  - source: doc-1\n"
        "    start: -5\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "sources[0].start: expected a whole number from 0 to 100000000, got -5"
    ]


GRAPH = """\
```component:graph
id: constantine-around
entity: Constantine
depth: 1
```
"""


def test_a_graph_carries_its_reference_and_depth_through_both_views():
    document = parse_document(GRAPH, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["depth"] == 1
    assert learner["resolved"] is True


def test_a_graph_defaults_its_depth_to_one():
    """One hop is the readable neighbourhood; two is a hairball in a markdown
    column. Red against a registry entry with no `default`, which would leave
    `depth` absent and the client picking a second bound to keep in step."""
    source = "```component:graph\nid: g\nentity: Constantine\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert block.data["depth"] == 1


def test_a_graph_depth_past_the_server_s_bound_is_an_authoring_error():
    """The route answers 422 for this (`app.py`'s `read_graph_neighborhood`).
    Catching it here turns a failure the reader would meet into a note the
    model can act on, which is what the validation report exists for. Red
    against `Spec(text)` on `depth`."""
    source = "```component:graph\nid: g\nentity: Constantine\ndepth: 5\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "depth: expected a whole number from 1 to 2, got 5"
    ]


def test_a_graph_depth_bound_tracks_the_server_s_constant():
    """Red against a hardcoded `2` in the registry the day someone raises
    `MAX_NEIGHBORHOOD_DEPTH` -- the failure being a widget that validates to
    one bound and fetches against another, which nothing else would report."""
    source = (
        f"```component:graph\nid: g\nentity: Constantine\n"
        f"depth: {MAX_NEIGHBORHOOD_DEPTH}\n```\n"
    )

    assert parse_document(source, path="lesson.md").components[0].errors == ()


TIMELINE = """\
```component:timeline
id: fourth-century-people
entity_type: Person
from: "0300-01-01"
to: "0400-01-01"
```
"""


def test_a_timeline_carries_its_window_through_both_views():
    document = parse_document(TIMELINE, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["entity_type"] == "Person"
    assert author["data"]["from"] == "0300-01-01"
    assert learner["resolved"] is True


def test_a_timeline_has_no_entity_field_and_warns_about_one():
    """`GET /timeline` has no entity filter, so `entity:` here would be a
    field that silently does nothing -- and a widget that quietly ignores what
    the author asked for is worse than one that cannot do it at all.

    The warning is `_unknown_keys`' existing behaviour, so this is red only
    against a registry entry that *added* an `entity` field to be helpful.
    """
    source = "```component:timeline\nid: t\nentity: Constantine\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.warnings] == ["entity: unrecognised field, ignored"]
    assert block.errors == ()


def test_a_timeline_with_no_window_at_all_is_valid():
    """Every field is optional: the whole timeline is a real thing to ask for,
    and requiring a range would make the commonest use the fiddliest."""
    source = "```component:timeline\nid: t\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()


def test_a_timeline_limit_past_the_server_s_cap_is_an_authoring_error():
    source = f"```component:timeline\nid: t\nlimit: {MAX_TIMELINE_BANDS + 1}\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        f"limit: expected a whole number from 1 to {MAX_TIMELINE_BANDS}, "
        f"got {MAX_TIMELINE_BANDS + 1}"
    ]


@pytest.mark.parametrize(
    "name", ["definition", "evidence", "graph", "timeline", "compare", "explorer"]
)
def test_every_resolved_type_tells_the_model_how_to_write_a_good_one(name):
    """`craft` is not decoration: the failure mode this format produces is a
    model inventing a tidy canonical name for an entity extraction stored as
    it appeared. A type with no craft notes is one whose failure mode nobody
    wrote down, and the model reads this every time it authors."""
    from research_team.application.components import REGISTRY

    component = REGISTRY[name]

    assert component.craft, f"{name} has no craft guidance"
    assert component.summary
    assert f"component:{name}" in component.example


@pytest.mark.parametrize("name", ["definition", "graph", "compare"])
def test_every_name_resolved_type_warns_about_inventing_a_canonical_name(name):
    """The one thing every by-name reference has to say, and the only failure
    mode of this design a model can avoid on its own.

    Red against craft guidance that describes the syntax and not the trap:
    'Constantine I' for an entity stored as 'Constantine' resolves to nothing,
    the widget renders as a plain word, and nothing tells the author why.
    """
    from research_team.application.components import REGISTRY

    craft = " ".join(REGISTRY[name].craft).lower()

    assert "exactly as" in craft


def test_timeline_craft_says_limit_does_not_make_the_read_cheaper():
    """Measured, not reasoned, on 2026-08-17: `TimelineReader.timeline` makes
    two full passes over the tenant's entities before `limit` is applied as
    `bands[:capped]` (`timeline_reader.py:140-167`), and it is deliberately
    uncached. So an author writing `limit: 20` to make a heavy widget cheap
    gets a shorter answer for the same work, and nothing else in the system
    would ever tell them.

    Red against craft notes that describe `limit` only as a way to keep the
    widget readable.
    """
    from research_team.application.components import REGISTRY

    craft = " ".join(REGISTRY["timeline"].craft).lower()

    assert "limit" in craft
    assert "cheaper" in craft or "less work" in craft


def test_the_generated_reference_carries_every_resolved_example():
    """What the ask agent is actually handed. A type absent from here is a
    type the model will never write, however well registered it is."""
    reference = component_reference(
        only=["definition", "evidence", "graph", "timeline", "compare", "explorer"]
    )

    for name in ("definition", "evidence", "graph", "timeline", "compare", "explorer"):
        assert f"component:{name}" in reference


def test_an_entity_id_written_where_a_name_belongs_is_warned_about():
    """`compare` has no id field, so an id copied into `entities` renders raw.

    The authoring prompt hands the model entity ids and tells it to copy them
    exactly. `entities` is the only entity-shaped field `compare` has, and a
    uuid is a valid string, so this validates with nothing said -- and the
    browser then searches for an entity *named* by that uuid, finds none, and
    prints it beside "not in this project's graph".

    Warned, never rejected: the table draws and only the heading is wrong.
    Red against a registry with no id check -- this body parses clean today
    with zero errors and zero warnings.
    """
    source = (
        "```component:compare\n"
        "id: c\n"
        "entities:\n"
        '  - "9f2c1a44-0000-4000-8000-000000000000"\n'
        "  - Constantine\n"
        "rows:\n"
        "  - label: Reign\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert [str(note) for note in block.warnings] == [
        "entities[0]: looks like an entity id, not a name; this field takes "
        "names as the sources spell them, and there is nowhere here to put an id"
    ]


def test_a_definition_given_an_id_for_its_name_is_told_which_field_to_use():
    """The same defect on a type that *does* have somewhere to put it.

    `definition` and `graph` carry `entity_id` beside `entity`, so the fix the
    model needs is a move rather than a lookup -- and the warning says so.
    """
    source = (
        "```component:definition\nid: d\nentity: 9f2c1a44-0000-4000-8000-000000000000\n```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert [str(note) for note in block.warnings] == [
        "entity: looks like an entity id, not a name; `entity` is the name as "
        "the sources spell it, and the id goes in `entity_id`"
    ]


def test_a_short_hyphenated_value_is_not_mistaken_for_an_id():
    """`284-305` is a reign, and a compare table is full of them.

    The check is loose about hex grouping and strict about length -- 32 hex
    digits, a uuid's worth -- precisely so that dates, ranges and hyphenated
    names do not collect a warning nobody can act on. Red against a check
    written as "hex and hyphens", which every one of these matches.
    """
    source = (
        "```component:compare\n"
        "id: c\n"
        "entities: [Diocletian, Constantine]\n"
        "rows:\n"
        '  - label: "284-305"\n'
        '    cells: ["ab-cd-ef", "AD 284-305"]\n'
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert block.warnings == ()

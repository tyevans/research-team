"""Tests for resolved component types: definition, evidence, graph,
timeline, explorer, and compare."""

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


EXPLORER = """\
```component:explorer
id: fourth-century-explorer
over: timeline
entity_type: Person
from: "0300-01-01"
to: "0400-01-01"
vary: [entity_type, window]
prompt: |
  Narrow to Emperors and pull the window back.
```
"""


def test_an_explorer_carries_its_query_through_both_views():
    """Projection identity, as for every resolved type. Red against a build
    that gave `explorer` a `strip` -- the reader would be handed controls over
    a query with no bounds in it and would not be told."""
    document = parse_document(EXPLORER, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["over"] == "timeline"
    assert author["data"]["vary"] == ["entity_type", "window"]
    assert learner["resolved"] is True


def test_an_explorer_over_something_unsupported_warns_by_name_and_still_renders():
    """The `over:` seam's whole point, from the design's section 3.

    A warning and not an error, deliberately: an error routes the block to the
    error panel, and the reader is then told the *author* wrote something
    broken rather than that this build cannot read that corpus yet. The widget
    renders the refusal as prose naming what is supported, which is what every
    other failure in these widgets does -- and an error would leave no widget
    to say it.

    Red against `Spec(one_of("timeline"), required=True)`, which is the obvious
    implementation and produces an error.
    """
    source = (
        "```component:explorer\nid: e\nover: graph\n"
        "vary: [entity_type]\nprompt: Look around.\n```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert [str(note) for note in block.warnings] == [
        "over: only 'timeline' is supported today, got 'graph'"
    ]


def test_an_explorer_that_varies_an_axis_that_does_not_exist_is_an_error():
    """Rejected rather than warned, unlike `over`. An unknown `over` still
    names a coherent intent this build cannot serve; an unknown axis names a
    control the widget would simply not draw, and an author who wrote
    `vary: [topic]` and saw two controls would have no way to learn why."""
    source = (
        "```component:explorer\nid: e\nover: timeline\n"
        "vary: [entity_type, topic]\nprompt: Look around.\n```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "vary[1]: expected one of entity_type, window, got 'topic'"
    ]


def test_an_explorer_needs_an_over_an_axis_and_a_prompt():
    """All three are required and the reasons differ. Without `prompt` the
    reader is handed controls with no reason to touch them (design section 3);
    without `vary` nothing is varyable and the block is a `timeline` with worse
    dressing; without `over` there is no backing read to make.

    The order is the order `fields` declares them in, which is what
    `validation_report` walks.
    """
    source = "```component:explorer\nid: e\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "over: required field missing",
        "vary: required field missing",
        "prompt: required field missing",
    ]


def test_an_explorer_limit_past_the_server_s_cap_is_an_authoring_error():
    """The same bound `timeline` carries, for the same reason: the route 422s
    on it, and an authoring-time note is a failure the model can act on where a
    fetch-time one is a failure only the reader sees."""
    source = (
        f"```component:explorer\nid: e\nover: timeline\nvary: [window]\n"
        f"prompt: Look.\nlimit: {MAX_TIMELINE_BANDS + 1}\n```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        f"limit: expected a whole number from 1 to {MAX_TIMELINE_BANDS}, "
        f"got {MAX_TIMELINE_BANDS + 1}"
    ]


def test_explorer_craft_says_limit_does_not_make_the_read_cheaper():
    """The same measured claim `timeline`'s craft carries, and it matters more
    here: an explorer re-runs the read on every window commit, so an author who
    believes `limit` bounds the cost will write one and hand a reader a control
    they think is cheap. Red against craft notes that describe `limit` only as
    a way to keep the widget readable."""
    from research_team.application.components import REGISTRY

    craft = " ".join(REGISTRY["explorer"].craft).lower()

    assert "limit" in craft
    assert "cheaper" in craft or "less work" in craft


def test_explorer_craft_tells_the_author_a_reader_cannot_link_to_what_they_find():
    """Design section 5: no serialisable query state exists anywhere in this
    app, so a reader can explore and cannot share the result. The `prompt` the
    author writes is the only place expectations get set, and this is the only
    place the author will be told."""
    from research_team.application.components import REGISTRY

    craft = " ".join(REGISTRY["explorer"].craft).lower()

    assert "link" in craft or "share" in craft


COMPARE = """\
```component:compare
id: two-emperors
entities: [Diocletian, Constantine]
rows:
  - label: Reign
    cells:
      - "284-305"
      - "306-337"
  - label: Religious policy
```
"""


def test_compare_carries_its_entities_and_rows_through_both_views():
    document = parse_document(COMPARE, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["entities"] == ["Diocletian", "Constantine"]
    assert author["data"]["rows"][0]["label"] == "Reign"
    assert learner["resolved"] is True


def test_compare_needs_two_entities_to_compare():
    """One column is not a comparison, and a table of one is a definition
    with extra ceremony."""
    source = (
        "```component:compare\nid: c\nentities: [Constantine]\nrows:\n  - label: Reign\n```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "entities: expected at least 2 entries, got 1"
    ]


def test_compare_names_a_non_string_entity_by_its_subscript():
    source = (
        "```component:compare\n"
        "id: c\n"
        "entities:\n"
        "  - name: Constantine\n"
        "  - Diocletian\n"
        "rows:\n"
        "  - label: Reign\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == ["entities[0]: expected text, got mapping"]


def test_a_compare_row_may_carry_no_cells_at_all():
    """A row label with nothing under it is a real thing to write -- it is the
    spec's own example -- and it renders as an empty row rather than an error.
    Red against `cells` being required."""
    source = "```component:compare\nid: c\nentities: [A, B]\nrows:\n  - label: Reign\n```\n"

    assert parse_document(source, path="lesson.md").components[0].errors == ()


def test_two_compare_rows_with_one_label_are_warned_about_and_still_render():
    """The renderer keys rows on the author's `label`, so a repeat is a React
    key collision: it draws correctly and logs a warning nobody reading the
    lesson will see. Warned rather than rejected, on `_unknown_keys`' and the
    duplicate-`id` warning's precedent -- deduping would mean inventing which
    row the author meant, and refusing would cost the whole table over a
    cosmetic defect.

    Red against a registry with no `warn` hook: the block parses clean today
    and says nothing.
    """
    source = (
        "```component:compare\n"
        "id: c\n"
        "entities: [A, B]\n"
        "rows:\n"
        "  - label: Reign\n"
        "  - label: Reign\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert [str(note) for note in block.warnings] == [
        "rows[1].label: duplicate label 'Reign'; the table keys rows on it and "
        "the two will collide"
    ]


def test_two_compare_columns_with_one_name_are_warned_about_too():
    """The same collision on the other axis -- `entities` keys the header
    cells and every row's cells. Missed by a check that only walked `rows`,
    which is what the first draft of this did."""
    source = (
        "```component:compare\n"
        "id: c\n"
        "entities: [Constantine, Constantine]\n"
        "rows:\n"
        "  - label: Reign\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert [str(note) for note in block.warnings] == [
        "entities[1]: duplicate entity 'Constantine'; the table keys columns on "
        "it and the two will collide"
    ]


def test_a_compare_body_that_never_validated_is_not_also_warned_about():
    """A body whose `rows` is a string has no rows to check for duplicates,
    and asking anyway is how a validator raises inside a parser that promises
    never to. Red against a `warn` hook that indexes before it checks types."""
    source = "```component:compare\nid: c\nentities: Constantine\nrows: nope\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors
    assert block.warnings == ()


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


def test_a_short_compare_row_is_not_warned_about_for_the_cells_it_omits():
    """The blank the craft note invites stays free of complaint.

    "A short row is padded, so a dimension one entity has and another does not
    is fine to leave blank -- that blank is itself the comparison"
    (`compare`'s craft notes). `cells` is optional and its entries are not
    required fields, so the blank-field warning must not reach them. Red
    against a hook that warned on any empty string it found.
    """
    source = (
        "```component:compare\n"
        "id: c\n"
        "entities: [Diocletian, Constantine]\n"
        "rows:\n"
        "  - label: Religious policy\n"
        '    cells: ["Persecution"]\n'
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert block.warnings == ()

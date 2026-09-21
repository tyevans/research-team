"""Tests for the Compare resolved component type."""

from research_team.platform.components import (
    parse_document,
    project,
)

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

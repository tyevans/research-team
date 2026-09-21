"""Tests for the resolved explorer component type."""

from research_team.knowledge.application.timeline_read import MAX_TIMELINE_BANDS
from research_team.platform.components import (
    REGISTRY,
    parse_document,
    project,
)

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
    craft = " ".join(REGISTRY["explorer"].craft).lower()

    assert "limit" in craft
    assert "cheaper" in craft or "less work" in craft


def test_explorer_craft_tells_the_author_a_reader_cannot_link_to_what_they_find():
    """Design section 5: no serialisable query state exists anywhere in this
    app, so a reader can explore and cannot share the result. The `prompt` the
    author writes is the only place expectations get set, and this is the only
    place the author will be told."""
    craft = " ".join(REGISTRY["explorer"].craft).lower()

    assert "link" in craft or "share" in craft

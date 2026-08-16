"""Turning a citation's character span into a place in the medium.

Pure, so there is no fixture in this file and nothing here awaits anything.
The map is written as JSON literals rather than built through
`MediaPerceiver`, deliberately: this is the reader of a *stored* field, and a
stored field can carry a payload written by a build that is not this one.
"""

import json

from research_team.application.locators import resolve


def _map(*segments: tuple[int, int, dict[str, object]]) -> str:
    """A locator map in the shape `MediaPerceiver` writes it."""
    return json.dumps(
        [
            {"char_start": start, "char_end": end, "locator": locator}
            for start, end, locator in segments
        ]
    )


TWO_SEGMENTS = _map(
    (0, 10, {"kind": "time", "start_s": 0.0, "end_s": 4.0}),
    (10, 20, {"kind": "time", "start_s": 4.0, "end_s": 8.0}),
)


def test_an_empty_map_resolves_to_nothing() -> None:
    assert resolve("[]", 0, 5) == ()


def test_a_span_inside_one_segment_resolves_to_that_segment() -> None:
    assert resolve(TWO_SEGMENTS, 2, 6) == ({"kind": "time", "start_s": 0.0, "end_s": 4.0},)


def test_a_span_crossing_two_segments_resolves_to_both_in_order() -> None:
    """In map order, not in overlap order.

    A citation renderer prints these as "0:00-0:08", so a pair that came back
    reversed would read as a backwards range rather than as a bug.
    """
    assert resolve(TWO_SEGMENTS, 8, 12) == (
        {"kind": "time", "start_s": 0.0, "end_s": 4.0},
        {"kind": "time", "start_s": 4.0, "end_s": 8.0},
    )


def test_one_shared_character_is_enough() -> None:
    """The inclusive end of "inclusive at both ends".

    A quote clipped mid-sentence still came from the moment it was clipped in,
    and answering nothing there would render as "this quote is from nowhere".
    `[9, 10)` shares exactly the character at offset 9 with the first segment
    and touches the second only at its boundary.
    """
    assert resolve(TWO_SEGMENTS, 9, 10) == ({"kind": "time", "start_s": 0.0, "end_s": 4.0},)


def test_a_boundary_touch_alone_does_not_pull_in_the_next_segment() -> None:
    """The exclusive end of it. `[0, 10)` ends exactly where segment two
    begins and shares no character with it; a locator pair reaching into a
    moment the quote does not contain would misplace the citation by a
    segment, which is a wrong answer indistinguishable from a right one."""
    assert resolve(TWO_SEGMENTS, 0, 10) == ({"kind": "time", "start_s": 0.0, "end_s": 4.0},)


def test_an_empty_span_resolves_to_the_segment_it_sits_in() -> None:
    """`quote` collapses reversed offsets to an empty span, so this arrives."""
    assert resolve(TWO_SEGMENTS, 12, 12) == ({"kind": "time", "start_s": 4.0, "end_s": 8.0},)


def test_an_empty_span_on_a_boundary_resolves_to_the_segment_it_begins() -> None:
    """The case the zero-width branch is actually for, and the reason this
    test is separate from the one above -- which passes with that branch
    deleted, because half-open arithmetic already answers a caret strictly
    inside a segment. On a boundary it answers nothing at all, and a caret at
    exactly 0:04 reporting no moment is the "this quote is from nowhere"
    rendering in its smallest form.

    It resolves to the segment it *begins* rather than to both neighbours: a
    zero-width span contains no character of the segment ending there, and
    two locators for a point would render as a range spanning a moment the
    caret is not in.
    """
    assert resolve(TWO_SEGMENTS, 10, 10) == ({"kind": "time", "start_s": 4.0, "end_s": 8.0},)


def test_a_span_past_the_end_resolves_to_nothing_rather_than_raising() -> None:
    """Matching `quote`'s clamping habit: offsets reach here from a model's
    output, where they are a guess, and an exception would abort a turn over
    an off-by-a-few."""
    assert resolve(TWO_SEGMENTS, 500, 600) == ()


def test_a_reversed_span_resolves_to_nothing_rather_than_raising() -> None:
    assert resolve(TWO_SEGMENTS, 12, 4) == ()


def test_a_locator_whose_kind_is_not_in_the_vocabulary_is_left_out() -> None:
    """Every reader of a locator dispatches on `kind`, and none has a default
    arm that could render one it has never heard of. Dropping it here keeps
    the failure in one place with one fix -- add the spelling to
    `LOCATOR_KINDS` -- rather than in three renderers that each fall through
    differently."""
    unknown = _map((0, 10, {"kind": "waveform", "start_s": 0.0}))
    assert resolve(unknown, 0, 5) == ()


def test_every_declared_kind_survives_the_filter() -> None:
    """The other half of the filter above: it must not be the thing that
    quietly drops a locator kind this repository does declare."""
    declared = _map(
        (0, 2, {"kind": "time", "start_s": 0.0, "end_s": 1.0}),
        (2, 4, {"kind": "page", "page": 3}),
        (4, 6, {"kind": "bbox", "page": 3, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.4}),
        (6, 8, {"kind": "char", "start": 0, "end": 2}),
        (8, 10, {"kind": "byte", "start": 0, "end": 2}),
    )
    assert len(resolve(declared, 0, 10)) == 5


def test_a_map_that_will_not_parse_resolves_to_nothing() -> None:
    """`decide` refuses these payloads, so nothing this build writes gets
    here broken -- but an event already written is never rewritten, and a
    citation renderer that raised on one would take a whole page down over a
    field it only wanted to decorate with."""
    assert resolve("not json", 0, 5) == ()
    assert resolve('{"kind": "time"}', 0, 5) == ()


def test_a_segment_missing_its_offsets_is_skipped_rather_than_raising() -> None:
    """Same reasoning, one level in: the domain checks that the map is a list
    of objects and deliberately checks nothing about their keys."""
    partial = json.dumps(
        [
            {"locator": {"kind": "page", "page": 1}},
            {"char_start": 0, "char_end": 10, "locator": {"kind": "page", "page": 2}},
        ]
    )
    assert resolve(partial, 0, 5) == ({"kind": "page", "page": 2},)

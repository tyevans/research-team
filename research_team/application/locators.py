"""Where in a medium a stretch of its transcript came from.

The one reader of `CorpusDerivedTextStored.locator_map`. It exists as its own
module rather than as a method on the perceiver because it is pure and its
callers are not the perceiver's callers: a citation renderer and the timeline
resolve locators without ever perceiving anything, and reaching them through a
use case that holds a corpus repository would make them depend on storage to
answer a question that is arithmetic.

**Total, never raising.** Every branch that could fail answers `()` instead.
The map arrives from an event, and an event already written is never
rewritten -- `decide` refuses a malformed payload at the boundary, but a
payload from an earlier build, a repair script or a direct append is beyond
its reach. A renderer that raised on one would take a page down over a field
it only wanted to decorate a quote with. The cost is real and worth naming:
a locator dropped here is silent, and the way anyone notices is a citation
that shows no moment when it should show one.
"""

import json

from research_team.application.perception import LOCATOR_KINDS

__all__ = ["resolve"]


def resolve(locator_map: str, start: int, end: int) -> tuple[dict[str, object], ...]:
    """Which moments or regions a character span covers.

    The span is the one `corpus_spans.quote` already produces for a citation,
    so a media citation costs no new event and no stored offset: the quote is
    resolved against the derived text exactly as it is for any document, and
    this turns the result into a place in the medium.

    Overlap is inclusive at both ends -- a span touching one character of a
    segment gets that segment -- because a quote clipped mid-sentence still
    came from the moment it was clipped in, and returning nothing there would
    read as "this quote is from nowhere".

    "Touching one character" is the whole of it, and the boundary case is the
    other way: `[0, 10)` against a segment starting at 10 shares no character
    with it and does not get it. A locator pair reaching into a moment the
    quote does not contain would misplace the citation by a segment, which is
    the wrong answer indistinguishable from a right one.

    Results come back in map order rather than overlap order, because a
    renderer prints a pair of time locators as one range and a reversed pair
    would read as a backwards range rather than as a bug.
    """
    segments = _segments(locator_map)
    if not segments:
        return ()
    if end < start:
        # `quote` collapses reversed offsets to an empty span before a caller
        # ever sees them, so this is defence rather than a case that arrives;
        # answering () keeps the promise above that nothing here raises.
        return ()
    return tuple(
        locator
        for segment_start, segment_end, locator in segments
        if _overlaps(segment_start, segment_end, start, end)
    )


def _overlaps(segment_start: int, segment_end: int, start: int, end: int) -> bool:
    """Whether `[start, end)` shares a character with `[segment_start, segment_end)`.

    The zero-width case is separate on purpose. Half-open arithmetic answers
    False for every empty span, and an empty span is not a malformed one --
    `quote` produces one from reversed offsets, and a caret in the middle of a
    transcript still sits at a moment. Treated as a point *inside* a segment
    rather than as a span touching two, so a caret exactly on a boundary
    resolves to the segment it begins rather than to both neighbours.
    """
    if start == end:
        return segment_start <= start < segment_end
    return segment_start < end and start < segment_end


def _segments(locator_map: str) -> list[tuple[int, int, dict[str, object]]]:
    """The map as offsets and locators, dropping anything unusable.

    Element keys are unvalidated in the domain by deliberate decision (see
    `_reject_unless_json_list_of_objects`), so "a list whose elements are
    objects" is everything a caller is entitled to assume and the rest is
    checked here.

    An unrecognised `kind` is dropped rather than passed through. Three
    readers dispatch on the tag and none has a default arm that could render a
    spelling it has never heard of, so passing one on moves the failure into
    whichever renderer meets it first, differently in each. Dropping it keeps
    the fix in one place: add the spelling to `LOCATOR_KINDS`.
    """
    try:
        parsed = json.loads(locator_map)
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    segments: list[tuple[int, int, dict[str, object]]] = []
    for element in parsed:
        if not isinstance(element, dict):
            continue
        segment_start = element.get("char_start")
        segment_end = element.get("char_end")
        locator = element.get("locator")
        # `bool` is excluded because `isinstance(True, int)` is True and a
        # boolean offset would slice at 0 or 1 rather than being noticed.
        if not isinstance(segment_start, int) or isinstance(segment_start, bool):
            continue
        if not isinstance(segment_end, int) or isinstance(segment_end, bool):
            continue
        if not isinstance(locator, dict) or locator.get("kind") not in LOCATOR_KINDS:
            continue
        segments.append((segment_start, segment_end, locator))
    return segments

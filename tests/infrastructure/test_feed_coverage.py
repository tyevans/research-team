"""Every aggregate type this application writes is either on the feed or not, on purpose.

This exists because the same bug has now shipped four times. `read_since`
scopes the live feed to a hand-written tuple of aggregate types; an aggregate
whose type is missing from it can append all it likes and no frame ever reaches
the browser, so the view that renders it updates only on a reload. Topics went
out that way (`c4d81a9`), then the knowledge graph and `Corpus` (#70), then
`Project`. Each fix added one entry to the tuple and left the next
aggregate to fail identically.

Three properties made it survive review every time, and the guard is built
against them rather than against the symptom:

- the defect is an **absence**, and nothing fails on an absence;
- every test builds its own store and asserts on the aggregates it wrote, so
  no test was ever in a position to notice the ones it did not;
- the accompanying comments described the live path as working, because when
  they were written the intent was real even though the wiring was not.

So the list of aggregate types comes from the domain itself, read at test time
by walking every registered `DomainEvent` subclass. Adding an aggregate is what
makes this test start demanding a decision about it. What it cannot check is
stated at the bottom of this file, in the same spirit as
`test_web_entrypoint.py`: this is a coverage guard, not a delivery guard.
"""

import importlib
import pkgutil

from eventsource import DomainEvent

import research_team.domain
from research_team.infrastructure.persistence.event_store import (
    FEED_AGGREGATE_TYPES,
    KNOWLEDGE_CATEGORIES,
    UNROUTED_AGGREGATE_TYPES,
)


def _domain_aggregate_types() -> set[str]:
    """Every `aggregate_type` any event in `research_team.domain` declares.

    Read off the classes rather than listed here, which is the entire point --
    a hand-written list would rot on the next aggregate added, and rotting
    silently is the failure being guarded against.

    Every module in the package is imported first. `DomainEvent.__subclasses__`
    only knows about classes that have actually been imported, and the domain
    package's `__init__` does not re-export all of them -- `learner` and
    `research_run` in particular are reached only through their own modules.
    Without this walk the guard would pass by not looking, which is the same
    shape as the bug.
    """
    for module in pkgutil.walk_packages(
        research_team.domain.__path__, f"{research_team.domain.__name__}."
    ):
        importlib.import_module(module.name)

    def descendants(cls: type) -> set[type]:
        found = set(cls.__subclasses__())
        return found | {nested for child in found for nested in descendants(child)}

    types = set()
    for event in descendants(DomainEvent):
        # Scoped to this application's own domain, because `__subclasses__` is
        # global: `eventsource.testing.conformance` declares an event under an
        # aggregate type of `Conformance`, and any test that imports the
        # library's suite puts it in this walk. The first run of this guard
        # failed on exactly that -- passing alone and failing in the full
        # suite, which is the signature of a global registry read as if it
        # were a local one. A library's test double is not an aggregate this
        # feed could ever be asked to carry, so it is not this guard's to
        # decide about.
        if not event.__module__.startswith(f"{research_team.domain.__name__}."):
            continue
        declared = event.model_fields.get("aggregate_type")
        # Abstract intermediates redeclare nothing and have no default; only a
        # concrete event class pins the type its stream is filed under.
        if declared is not None and isinstance(declared.default, str):
            types.add(declared.default)
    return types


def test_every_aggregate_type_is_routed_or_deliberately_not():
    """No aggregate type may be absent from both lists.

    The assertion is on the *undecided* set rather than on equality, because
    equality would also fail when a routed type has no events of its own --
    redstring's two categories are exactly that, and they are not this
    application's classes to find. What must never happen is a type appearing
    in neither list, because that is indistinguishable from nobody having
    thought about it.

    This test passes with the `Project` admission reverted only if `Project`
    is also moved into
    `UNROUTED_AGGREGATE_TYPES` -- which is the trade being made: the guard
    cannot tell a wrong decision from a right one, it can only refuse to let
    one go unwritten.
    """
    decided = set(FEED_AGGREGATE_TYPES) | UNROUTED_AGGREGATE_TYPES
    undecided = _domain_aggregate_types() - decided

    assert not undecided, (
        f"aggregate types {sorted(undecided)} reach the event store but appear in neither "
        "FEED_AGGREGATE_TYPES nor UNROUTED_AGGREGATE_TYPES. A view that renders one of these "
        "will update only on a reload. Add it to whichever list is right and say why."
    )


def test_the_two_lists_do_not_overlap():
    """A type in both lists is a decision that contradicts itself.

    Cheap, and it is what keeps the guard above honest: without it, adding a
    type to `UNROUTED_AGGREGATE_TYPES` would silence the coverage assertion
    whether or not the type was also being read, so the excluded list would
    stop describing anything.
    """
    assert not set(FEED_AGGREGATE_TYPES) & UNROUTED_AGGREGATE_TYPES


def test_the_feed_list_holds_no_duplicates():
    """Each admitted type is one query per poll, so a duplicate is a doubled read.

    It would not corrupt anything -- `read_since` sorts by position and both
    copies of an entry would sort together -- so the browser would receive the
    same frame twice and repaint twice. Invisible, and a fair way to slow the
    feed down while adding an entry beside an existing one.
    """
    assert len(FEED_AGGREGATE_TYPES) == len(set(FEED_AGGREGATE_TYPES))


def test_redstrings_categories_are_still_on_the_feed():
    """The one part of the feed list this application does not own.

    redstring is pre-1.0 with a no-shim policy, so its category names can be
    renamed under us. The import in `event_store` already turns a rename into
    an `ImportError` at startup; this pins the weaker half -- that whatever the
    names are today, both are admitted rather than one.
    """
    assert set(KNOWLEDGE_CATEGORIES) <= set(FEED_AGGREGATE_TYPES)


# What this file does not catch, said plainly rather than left to be discovered
# the way the original bug was:
#
# - It checks that a type is *read*, not that a frame is *rendered*. `_sse`
#   routes on aggregate type and a type admitted here with no branch there
#   falls through to `feed_event`, which addresses it as a session -- the
#   mislabelled-frame failure `KNOWLEDGE_CATEGORIES` warns about. The per-type
#   tests in `test_persistence.py` and `test_app.py` are what cover that; this
#   one would pass.
# - It checks nothing about the browser. A frame can arrive correctly and no
#   view subscribe to it, which is the second half of every one of these four
#   bugs and lives entirely in the frontend tests.
# - It cannot tell a considered exclusion from a lazy one. `UNROUTED_AGGREGATE_TYPES`
#   is a place to write the reasoning down, and a reviewer reading it is still
#   the check on whether the reasoning is any good.

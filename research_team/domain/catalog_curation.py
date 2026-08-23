"""The one part of the catalog a person decides rather than the graph derives.

Its own module beside `course_catalog.py`, and the split is the point. Every
value object next door is a derivation and must stay recomputable. Featuring is
a *choice*, so it goes on the log -- and keeping the two in separate files is
what stops that distinction eroding the first time somebody wants to cache a
candidate "just like the featured ones".

Appended directly rather than through a `DeciderAggregate`, following
`domain/ontology.py`: these enforce no invariant. Featuring an already-featured
slug is idempotent in effect, and there is no state for a decider to protect.

**Keyed on `slug`, not on a course id.** A person features a *candidate*, and
on a fresh project no candidate has been realized -- a minted id would make the
hero row unusable exactly when it matters most. The cost is real and is handled
on read: a slug is derived from an area's top anchor, so re-clustering can move
it, and a featured slug that names no current area cannot be placed. It is
reported rather than dropped (see `CatalogService.build`), because curation
work that silently disappears is worse than curation work that is visibly
stranded.
"""

from uuid import UUID

from eventsource import DomainEvent, register_event

CATALOG_AGGREGATE_TYPE = "CourseCatalog"
"""The stream these are appended to, named rather than spelled twice.

There is no `CourseCatalog` aggregate to ask for `aggregate_type`, deliberately
-- see the module docstring -- so this constant stands in for the class
attribute the way `ONTOLOGY_AGGREGATE_TYPE` does, and the feed-coverage guard
has something to name that cannot drift from the events' own default.
"""


@register_event
class CourseFeatured(DomainEvent):
    """Somebody put this candidate on the front page.

    `rank` orders the hero row among featured candidates. Ties are broken on
    slug when they occur, which they will: nothing stops two candidates being
    featured at the same rank, and refusing that would mean this event
    enforcing an invariant it has no aggregate to enforce it with.
    """

    aggregate_type: str = CATALOG_AGGREGATE_TYPE
    project_id: UUID
    slug: str
    rank: int = 0


@register_event
class CourseUnfeatured(DomainEvent):
    """Somebody took this candidate off the front page.

    Unfeaturing a slug that was never featured is appended rather than refused,
    for this module's no-invariant reason: the projection treats it as a
    delete, and a delete of nothing is nothing.
    """

    aggregate_type: str = CATALOG_AGGREGATE_TYPE
    project_id: UUID
    slug: str

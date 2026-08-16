"""`ProjectTimelineReader`: `TimelineReadPort` over a live redstring `GraphStore`.

The third module importing redstring's own types, alongside `graph_reader.py`
and `redstring_adapter.py`, and for the same reason: everything above
`TimelineReadPort` speaks this application's `TimelineBand`, so the
translation happens here or nowhere.

**No read model, and that is worth stating because the surrounding code argues
otherwise.** `CorpusStore`, `TopicRow` and `CheckOutcomeRow` are all SQLite
read models fed by projections, so the reflex on meeting a new read is to add
a fourth. The graph read path is this repository's exception: it computes
everything per request from a store folded out of the knowledge event log, and
a timeline is a second read of that same kind. `GraphStore` satisfies
redstring's `EntityReader` protocol -- verified by introspection, all six
methods present -- and `TemporalQuery` takes exactly an `EntityReader`, so this
reads the store `ProjectGraphs` already opened for the graph view.
"""

from typing import Any
from uuid import UUID

from eventsource.domain.tenant_context import tenant_scope
from redstring import Bounds, TemporalQuery

from research_team.application.timeline_read import (
    MAX_TIMELINE_BANDS,
    Timeline,
    TimelineBand,
    TimelineInterval,
)
from research_team.infrastructure.knowledge.temporal_interval import extent_bounds
from research_team.infrastructure.knowledge.temporal_rendering import (
    entity_extent_label,
)


def _to_band(entity: Any) -> TimelineBand | None:
    """`entity` as a band, or `None` when it has nothing to draw.

    Returns `None` rather than raising for an undated entity because undated
    is the *ordinary* case -- most entities in a real graph are not events --
    and the caller counts them rather than treating them as a failure.
    """
    bounds = extent_bounds(entity.temporal)
    if bounds is None:
        return None
    lower, upper = bounds
    return TimelineBand(
        entity_id=str(entity.id),
        name=entity.name,
        entity_type=entity.entity_type,
        # `or ""` rather than letting `None` through: `extent_bounds` already
        # said this entity is dated, so a `None` here would mean the two
        # modules disagree about what "undated" is -- and an empty label is a
        # visible defect where a `None` in a `str` field is a type error at
        # some distance from its cause.
        extent=entity_extent_label(entity) or "",
        start=lower.isoformat() if lower is not None else None,
        end=upper.isoformat() if upper is not None else None,
        precision=getattr(getattr(entity.temporal, "precision", None), "name", ""),
        uncertainty=getattr(getattr(entity.temporal, "uncertainty", None), "name", ""),
    )


class ProjectTimelineReader:
    """`TimelineReadPort` for one project, over the store `ProjectGraphs` opened.

    Bound to a `project_id` at construction, the shape `ProjectGraphReader`
    uses: the project a caller can read is fixed by which reader it was
    handed, not by anything passed per call.
    """

    def __init__(self, *, project_id: UUID, store: Any) -> None:
        self._project_id = project_id
        self._store = store

    async def _without_aliases(self, entities: list[Any]) -> list[Any]:
        """`entities` with everything merged away removed.

        The same filter `ProjectGraphReader` applies, needed here for a
        sharper reason. On a canvas an absorbed entity draws as an isolated
        node with no edges, which reads as a duplicate. On a timeline it draws
        as a *second bar with an identical extent*, which reads as two sources
        agreeing -- corroboration rather than double-counting, and a reader
        has no way to tell.

        `==`, not `is`: `resolve_entity_ids` may hand back a rebuilt `UUID`
        for an id that is not an alias, and `is` would filter out every entity
        and draw an empty timeline. redstring's own `CandidateFinder` carries
        the same warning over the same call, having been bitten by it.
        """
        if not entities:
            return []
        canonical = await self._store.resolve_entity_ids(
            [entity.id for entity in entities], self._project_id
        )
        return [entity for entity in entities if canonical[entity.id] == entity.id]

    async def timeline(
        self,
        *,
        entity_type: str | None = None,
        interval: TimelineInterval | None = None,
        limit: int = MAX_TIMELINE_BANDS,
    ) -> Timeline:
        """This project's dated entities, ascending by when they begin.

        **Two passes over the tenant, and the second is the price of
        `undated_count`.** `TemporalQuery.timeline` returns only dated
        entities, so the denominator has to come from somewhere else --
        `find_entities` over the same store. This is the same order of cost
        `ProjectGraphReader.whole` already pays on every graph open, so it is
        not a new class of expense, but it is double a single read and it is
        paid on a tab a reader may return to repeatedly.

        Deliberately uncached. A cache needs an invalidation, the knowledge
        log already emits frames that would have to drive one, and building
        that before a measurement says which half is slow would be guessing at
        which one to fix.

        Ordering comes from the library rather than being redone here.
        redstring promises start, then end, then id, and documents why the id
        tiebreak exists: two entities routinely carry the same extent -- a
        document naming three things that happened in 1066 -- and without it
        their order would depend on what the store handed back, which the port
        does not promise to keep stable across adapters. Re-sorting here would
        throw that away and reintroduce the instability at the next adapter
        change.
        """
        # `max(1, ...)` and not just `min`: a negative limit reaches
        # `bands[:capped]`, where Python's slice semantics quietly *drop the
        # last N* and report `truncated=True` -- `?limit=-1` would return
        # everything but the final event and say the cap did it. One band is
        # the smallest honest answer to "as few as possible".
        capped = max(1, min(limit, MAX_TIMELINE_BANDS))
        # Translated here rather than above: `Bounds` is redstring's, and the
        # port names none of its types. Field-for-field because
        # `TimelineInterval` is deliberately the same half-open convention.
        bounds = None if interval is None else Bounds(interval.start, interval.end)
        async with tenant_scope(self._project_id):
            dated = await TemporalQuery(self._store).timeline(
                self._project_id, interval=bounds, entity_type=entity_type
            )
            dated = await self._without_aliases(list(dated))
            # No `interval` here, and that is the point of `undated_count`: an
            # undated entity intersects no window, so filtering the denominator
            # by one would count zero of them and report a timeline that is
            # missing nothing.
            everything = await self._store.find_entities(
                self._project_id, entity_type=entity_type
            )
            everything = await self._without_aliases(list(everything))

        bands = [band for band in map(_to_band, dated) if band is not None]
        # Asked of each entity directly rather than computed as
        # `len(everything) - len(bands)`, which is what this was until
        # `interval` arrived and broke it: with a window in play `bands` is a
        # subset of the dated entities, so the subtraction would report every
        # entity dated *outside* the window as undated. Asking `_to_band` is
        # also the definition the field claims -- "carrying no drawable
        # extent" -- rather than a difference between two counts that two
        # modules decide separately.
        undated_count = sum(1 for entity in everything if _to_band(entity) is None)
        return Timeline(
            bands=tuple(bands[:capped]),
            undated_count=undated_count,
            truncated=len(bands) > capped,
        )

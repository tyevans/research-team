"""Rebuilding a project's graph from the log.

Runs at project open, which is what lets the default install keep the graph in
memory: the store is derived, so losing it costs a fold rather than data.

The two workarounds that used to live here -- R3 (no scoping, so the fold read
the whole log and dropped foreign events in Python) and R4 (a failed replay was
a count, so a partial graph came up silently and undiagnosably) -- are both
closed upstream. redstring 0.3.0 removed its own replay module in favour of
`eventsource.replay`, which takes `tenant_id` (pushed into the adapter's
`WHERE` clause) and `strict`, and whose failures name the offending event.
"""

from uuid import UUID

from eventsource import ReplayFailedError, replay
from redstring import ChunkProjection, ChunkStore, GraphProjection, GraphStore

from research_team.application.knowledge import KnowledgeError


async def rebuild_graph(
    store: GraphStore, *, feed, project_id: UUID, chunks: ChunkStore | None = None
) -> int:
    """Fold this project's knowledge events into `store`. Returns events applied.

    Takes no provider, and must not grow one: extraction happens once, when the
    agent asks for it, and is replayed from the log thereafter. A model call on
    this path would mean a session refolded years from now depends on a live
    endpoint.

    `tenant_id` scopes the read rather than the delivery: redstring knows a
    research-team project only as a tenant, and this store is shared, so the
    alternative is reading every session event in the file and discarding it.
    research-team's own events carry no tenant and so are excluded by the same
    filter.

    `chunks` is keyword-only with a `None` default so no existing caller
    breaks. **A log holding `DocumentChunked` cannot fail to open just
    because `chunks` is omitted** -- `eventsource.replay` applies an event no
    projection handles rather than rejecting it (verified against
    `eventsource.application.projections.replay`'s docstring: "An event that
    every projection ignores still counts as applied -- it was delivered and
    nothing rejected it"). The failure mode of omitting `ChunkProjection` is
    therefore silent rather than loud: the corpus comes up empty, BM25
    returns nothing, and the UI says "no mentions found" -- the same sentence
    it truthfully says about an entity that has none. Nothing here can raise
    to catch that; it is why the corresponding test asserts retrieval, not
    that `rebuild_graph` merely returned.
    """
    projections: list[object] = [GraphProjection(store)]
    if chunks is not None:
        # Folded in the same pass rather than a second replay: the log is
        # read once and both read models are derived from it, so a corpus can
        # never be a different age than the graph its citations sit alongside.
        projections.append(ChunkProjection(chunks))
    try:
        report = await replay(feed, projections, tenant_id=project_id, strict=True)
    except ReplayFailedError as error:
        # `strict` refuses at the first bad event rather than folding on and
        # reporting a count. The failure names the event, which is the whole
        # difference between a refusal an operator can act on and one they
        # cannot -- so it is repeated here rather than left to the `__cause__`.
        failure = error.failure
        raise KnowledgeError(
            f"knowledge event {failure.event_type} at {failure.position} failed to "
            f"replay for project {project_id} ({failure.error!r}); refusing to serve "
            "a partial graph"
        ) from error
    return report.applied

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
from redstring import GraphProjection, GraphStore

from research_team.application.knowledge import KnowledgeError


async def rebuild_graph(store: GraphStore, *, feed, project_id: UUID) -> int:
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
    """
    projection = GraphProjection(store)
    try:
        report = await replay(feed, [projection], tenant_id=project_id, strict=True)
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

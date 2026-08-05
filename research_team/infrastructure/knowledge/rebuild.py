"""Rebuilding a project's graph from the log.

Runs at project open, which is what lets the default install keep the graph in
memory: the store is derived, so losing it costs a fold rather than data.

Two workarounds live here, both waiting on upstream redstring work recorded in
`docs/superpowers/specs/2026-08-04-projects-and-redstring-knowledge-design.md`:

- **R3.** `project()` folds the *global* feed -- no stream, category or tenant
  argument -- so in a shared store it reads every session event too. Scoping is
  by `tenant_filter` on the projection instead; research-team's own events
  carry no tenant and are filtered out. Still open in redstring 0.2.0, and
  cheaper to close than it looks: `GlobalEventFeed.read_all` already takes
  `FeedReadOptions(tenant_id=...)`, which the SQLite adapter pushes into the
  `WHERE` clause. `project()` simply never passes it, so the filtering that
  could happen in the query happens here in Python instead.
- **R4.** `ReplayReport.failed` is a count, not a raise. A poison event is
  swallowed and the graph comes up quietly incomplete, so the count is checked
  here and refused. Note what the refusal below *cannot* say: redstring
  discards the exception, so there is no way to name which event failed or
  why. The check is safe and undiagnosable at the same time.

redstring exports its replay entry point as the bare verb `project`, which in
this file would sit next to `project_id` meaning something entirely unrelated
-- a research-team project, which redstring knows only as a tenant. It is
imported under `fold_into` so the two never read as the same idea.
"""

from uuid import UUID

from redstring import GraphProjection, GraphStore
from redstring import project as fold_into

from research_team.application.knowledge import KnowledgeError


async def rebuild_graph(store: GraphStore, *, feed, project_id: UUID) -> int:
    """Fold this project's knowledge events into `store`. Returns events applied.

    Takes no provider, and must not grow one: extraction happens once, when the
    agent asks for it, and is replayed from the log thereafter. A model call on
    this path would mean a session refolded years from now depends on a live
    endpoint.
    """
    # Workaround for R3: project() has no stream/category scoping, so the
    # projection itself filters to this tenant.
    projection = GraphProjection(store, tenant_filter=project_id)
    report = await fold_into(feed, [projection])
    # Workaround for R4: a failed replay is a count, not an exception, so a
    # partial graph would otherwise come up silently.
    if report.failed:
        raise KnowledgeError(
            f"{report.failed} knowledge event(s) failed to replay for project "
            f"{project_id}; refusing to serve a partial graph"
        )
    return report.applied

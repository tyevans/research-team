"""Rebuilding a project's graph from the log.

Runs at project open, which is what lets the default install keep the graph in
memory: the store is derived, so losing it costs a fold rather than data.

Two workarounds live here, both waiting on upstream redstring work recorded in
`docs/superpowers/specs/2026-08-04-projects-and-redstring-knowledge-design.md`:

- **R3.** `project()` folds the *global* feed -- no stream or category
  argument -- so in a shared store it reads every session event too. Scoping is
  by `tenant_filter` on the projection instead; research-team's own events
  carry no tenant and are filtered out.
- **R4.** `ReplayReport.failed` is a count, not a raise. A poison event is
  swallowed and the graph comes up quietly incomplete, so the count is checked
  here and refused.
"""

from uuid import UUID

from redstring import GraphStore
from redstring.projections import GraphProjection, project

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
    report = await project(feed, [projection])
    # Workaround for R4: a failed replay is a count, not an exception, so a
    # partial graph would otherwise come up silently.
    if report.failed:
        raise KnowledgeError(
            f"{report.failed} knowledge event(s) failed to replay for project "
            f"{project_id}; refusing to serve a partial graph"
        )
    return report.applied

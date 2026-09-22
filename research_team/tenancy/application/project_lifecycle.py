"""Project aggregate lifecycle commands and persistence operations.

Extracted from `project_sessions.py` to isolate project-level mutation commands
(delete, archive, unarchive, rename, metadata update) from session file
binding and tip synchronization.
"""

from uuid import UUID

from eventsource.application.aggregates.repository import AggregateRepository

from research_team.knowledge.application.knowledge_attachment import (
    KnowledgeAttachment,
)
from research_team.knowledge.application.project_graphs import ProjectGraphs
from research_team.tenancy.domain import (
    ArchiveProject,
    DeleteProject,
    Project,
    RenameProject,
    UnarchiveProject,
    UpdateProjectMetadata,
)

__all__ = [
    "archive_project_aggregate",
    "delete_project_aggregate",
    "rename_project_aggregate",
    "unarchive_project_aggregate",
    "update_project_metadata_aggregate",
]


async def delete_project_aggregate(
    projects: AggregateRepository[Project],
    project_id: UUID,
    *,
    graphs: ProjectGraphs | None = None,
) -> None:
    """Retire a project: no more joins, and gone from every listing.

    A tombstone, not an erasure -- see `ProjectDeleted`. What this does
    *not* touch is deliberate: the sessions that were in the project keep
    their streams, their files and their readable history, because those
    live on the session's own stream and were never the project's to
    delete. The knowledge graph's data is left in place too; dropping a
    tenant's contents is a destructive, unreplayable act, and nothing
    here asks for it.

    Rejects a project still held by a session. Releasing is the caller's
    move to make, because releasing advances the tip -- a write to the
    holder's session -- and deletion doing that silently would hide a
    real change behind an unrelated verb.

    Evicts the project's graph store from `graphs` after the tombstone
    commits, not before: a rejected `DeleteProject` (still held) must
    leave a live project's cached store exactly as it was, and evicting
    first would have to be undone on every rejection path this or a
    future one grows.
    """
    project = await projects.load(project_id)
    project.execute(DeleteProject())
    await projects.save(project)
    if graphs is not None:
        await graphs.close(project_id)


async def archive_project_aggregate(
    projects: AggregateRepository[Project],
    project_id: UUID,
    *,
    attachment: KnowledgeAttachment | None = None,
) -> None:
    """Archive a project: mark read-only and detach knowledge graph if attached."""
    project = await projects.load(project_id)
    project.execute(ArchiveProject())
    await projects.save(project)
    if attachment is not None and attachment.attached_project_id == project_id:
        await attachment.detach()


async def unarchive_project_aggregate(
    projects: AggregateRepository[Project],
    project_id: UUID,
) -> None:
    """Restore an archived project to active standing."""
    project = await projects.load(project_id)
    project.execute(UnarchiveProject())
    await projects.save(project)


async def rename_project_aggregate(
    projects: AggregateRepository[Project],
    project_id: UUID,
    name: str,
) -> None:
    """Rename an active project."""
    project = await projects.load(project_id)
    project.execute(RenameProject(name=name))
    await projects.save(project)


async def update_project_metadata_aggregate(
    projects: AggregateRepository[Project],
    project_id: UUID,
    *,
    description: str | None = None,
    tags: tuple[str, ...] | list[str] | None = None,
    metadata: dict[str, str] | None = None,
) -> None:
    """Update project metadata, tags, and description."""
    project = await projects.load(project_id)
    project.execute(
        UpdateProjectMetadata(description=description, tags=tags, metadata=metadata)
    )
    await projects.save(project)

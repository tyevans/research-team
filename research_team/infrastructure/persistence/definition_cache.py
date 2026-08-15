"""The definition cache, behind `DefinitionCachePort`, scoped to one project.

`EntityDefinitionRunner` answers for every project -- one table following one
log -- and `DefinitionCachePort` deliberately takes no project argument, for
the reason `ProjectCorpusReader` gives about `CorpusReadPort`: a caller that
could pass a different project id is a caller that could read, or overwrite,
another project's cached definitions. The project is bound once, here.

The other half of this module's job is the `Definition` <-> `EntityDefinition
Row` translation, and it lives here rather than on either side because both
sides are right to be ignorant of the other: the application layer's
`Definition` holds `Citation` objects a reader can iterate, and the row holds
the JSON string the browser is handed whole (see `EntityDefinitionRow.
citations` for why that column is a string). One of the two has to know both
shapes; an adapter is what that is.
"""

import json
from uuid import UUID

from research_team.application.entity_definitions import Citation, Definition
from research_team.infrastructure.persistence.read_models import (
    EntityDefinitionRow,
    EntityDefinitionRunner,
)


def _citations_of(encoded: str) -> list[Citation]:
    """The row's JSON column as citations, or none of them.

    A malformed column answers `[]` rather than raising. It should not
    happen -- `put` below is the only writer and it encodes from typed
    objects -- but the cost of being wrong differs sharply by direction: a
    definition that comes back with no citations is regenerated on the next
    read (see `DefinitionService.define`), where an exception here would 500
    the entity panel and keep 500ing it until someone found the row by hand.
    """
    try:
        payload = json.loads(encoded)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, list):
        return []
    return [
        Citation(source_id=item["source_id"], start=item["start"], end=item["end"])
        for item in payload
        if isinstance(item, dict)
        and isinstance(item.get("source_id"), str)
        and isinstance(item.get("start"), int)
        and isinstance(item.get("end"), int)
    ]


class ProjectDefinitionCache:
    """`DefinitionCachePort` over `EntityDefinitionRunner`, fixed to one project."""

    def __init__(self, runner: EntityDefinitionRunner, project_id: UUID) -> None:
        self._runner = runner
        self._project_id = project_id

    async def get(self, entity_id: UUID) -> Definition | None:
        row = await self._runner.get(self._project_id, entity_id)
        if row is None:
            return None
        return Definition(
            text=row.text,
            citations=_citations_of(row.citations),
            model=row.model,
            generated_at=row.generated_at,
            # The whole point of the shared table: `stale` was written by the
            # invalidation projection reacting to a graph event, not by
            # anything on the read path, and it travels with the text so the
            # service can decide whether to regenerate.
            stale=row.stale,
        )

    async def put(self, entity_id: UUID, definition: Definition) -> None:
        await self._runner.put(
            EntityDefinitionRow(
                id=EntityDefinitionRow.row_id(self._project_id, entity_id),
                project_id=self._project_id,
                entity_id=entity_id,
                text=definition.text,
                citations=json.dumps(
                    [
                        {
                            "source_id": citation.source_id,
                            "start": citation.start,
                            "end": citation.end,
                        }
                        for citation in definition.citations
                    ]
                ),
                model=definition.model,
                generated_at=definition.generated_at,
                stale=definition.stale,
            )
        )

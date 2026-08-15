"""Where in the corpus an entity is mentioned, in this application's own terms.

`Usage` and `UsageReadPort` name no redstring type -- `StoredChunk`,
`RankedChunk`, `TenantId` never appear in a signature here -- for the same
reason `CorpusReadPort` and `GraphReadPort` don't: everything above
`infrastructure/knowledge/` speaks this application's own vocabulary, and
`tests/test_architecture.py` enforces that a redstring import never crosses
this boundary. `usage_reader.py` is where the translation happens.

The project/tenant is not a parameter on `usages`, for the same reason it
isn't on `KnowledgePort` or `CorpusReadPort`: an instance belongs to one
project and supplies it, so a caller cannot ask for another project's
mentions by passing a different id.
"""

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True)
class Usage:
    """One passage that names an entity (or a name it has been merged under).

    `start`/`end` are character offsets into the source identified by
    `source_id`, and `text` is exactly the slice they name -- carried
    alongside rather than left for a caller to re-slice, because re-slicing
    would mean every caller also needing the source's full text just to show
    one sentence.

    `score` ranks usages of the *same* entity against each other; see
    `UsageReader.usages` for why it must not be compared across entities.
    """

    source_id: str
    start: int
    end: int
    text: str
    score: float


class UsageReadPort(Protocol):
    """Passages naming an entity, best matches first.

    `limit` caps how many usages come back, not how many candidate passages
    are considered per name -- an adapter fanning out over several names
    (aliases, past merges) may look at more than `limit` passages before
    settling on the top `limit`.
    """

    async def usages(self, entity_id: UUID, *, limit: int = 20) -> list[Usage]: ...

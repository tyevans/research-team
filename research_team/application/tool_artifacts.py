"""What a tool hands the console beside the string it hands the model.

Seven shapes rather than one per tool. A shape is a visual grammar the reader
learns once, so a new tool inherits a rendering instead of falling back to a
block quote -- and there are seven things to keep in step with the console
rather than seventeen. `docs/superpowers/specs/2026-08-28-activity-stream-design.md`
argues the choice.

Pure and in `application/` because the shapes are a contract between the tools
and the web layer, and neither may own it: `infrastructure/agent/` would make
the presenter import an adapter, and `interfaces/web/` would make every tool
import the console.
"""

from dataclasses import dataclass
from typing import Any

ARTIFACT_VERSION = 1
"""Present from the first commit, and not because a migration is planned.

The project is pre-release and breaks stored data freely. This exists so a
reader of an old event can tell "no artifact" from "an artifact I do not
understand" -- those want different fallbacks, and without a version they are
the same `None`.
"""


@dataclass(frozen=True)
class Hit:
    """One match, addressed in the only scheme `read_source` accepts."""

    start: int
    end: int
    snippet: str

    def as_artifact(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "snippet": self.snippet}


@dataclass(frozen=True)
class SourceHits:
    """One source's matches, with what the renderer needs to place them.

    `char_count` travels because the sparkline positions each hit against the
    length of its own document; without it the renderer would have to guess a
    denominator, and every source would be drawn on a different scale while
    looking like one scale.
    """

    source_id: str
    title: str | None
    label: str | None
    char_count: int
    total: int
    """Matches in this source, including any beyond the ones in `hits` --
    `MAX_PER_SOURCE` caps what is carried, and a count that silently became
    "the ones we kept" is how a corpus with eleven hits reports four."""
    hits: tuple[Hit, ...]

    def as_artifact(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "label": self.label,
            "char_count": self.char_count,
            "total": self.total,
            "hits": [hit.as_artifact() for hit in self.hits],
        }


@dataclass(frozen=True)
class HitList:
    SHAPE = "hit_list"

    pattern: str
    total: int
    suppressed: int
    sources: tuple[SourceHits, ...]

    def as_artifact(self) -> dict[str, Any]:
        return {
            "shape": self.SHAPE,
            "version": ARTIFACT_VERSION,
            "pattern": self.pattern,
            "total": self.total,
            "suppressed": self.suppressed,
            "sources": [source.as_artifact() for source in self.sources],
        }


@dataclass(frozen=True)
class EntityRef:
    entity_id: str
    name: str
    entity_type: str
    relationship_count: int

    def as_artifact(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "name": self.name,
            "entity_type": self.entity_type,
            "relationship_count": self.relationship_count,
        }


@dataclass(frozen=True)
class EntityList:
    SHAPE = "entity_list"

    query: str
    entities: tuple[EntityRef, ...]
    mode: str
    """Which channels actually ran. Carried because `SearchOutcome.mode`
    exists to make a silent degradation visible, and a console that drops it
    reintroduces exactly the silence the field was added to break."""

    def as_artifact(self) -> dict[str, Any]:
        return {
            "shape": self.SHAPE,
            "version": ARTIFACT_VERSION,
            "query": self.query,
            "mode": self.mode,
            "entities": [entity.as_artifact() for entity in self.entities],
        }


@dataclass(frozen=True)
class Excerpt:
    SHAPE = "excerpt"

    source_id: str
    title: str | None
    label: str | None
    start: int
    end: int
    char_count: int
    text: str
    uri: str | None = None

    def as_artifact(self) -> dict[str, Any]:
        return {
            "shape": self.SHAPE,
            "version": ARTIFACT_VERSION,
            "source_id": self.source_id,
            "title": self.title,
            "label": self.label,
            "start": self.start,
            "end": self.end,
            "char_count": self.char_count,
            "text": self.text,
            "uri": self.uri,
        }


@dataclass(frozen=True)
class InventoryItem:
    item_id: str
    title: str | None
    label: str | None
    size: int
    """Characters for a text source, bytes for media. The unit travels on the
    parent's `unit` rather than per item: a list mixing the two on one bar
    axis is the grid mistake in miniature."""
    detail: str | None = None

    def as_artifact(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "label": self.label,
            "size": self.size,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class Inventory:
    SHAPE = "inventory"

    kind: str
    unit: str
    total: int
    items: tuple[InventoryItem, ...]

    def as_artifact(self) -> dict[str, Any]:
        return {
            "shape": self.SHAPE,
            "version": ARTIFACT_VERSION,
            "kind": self.kind,
            "unit": self.unit,
            "total": self.total,
            "items": [item.as_artifact() for item in self.items],
        }


@dataclass(frozen=True)
class Acknowledgement:
    SHAPE = "acknowledgement"

    action: str
    subject: str
    detail: str | None = None
    ok: bool = True

    def as_artifact(self) -> dict[str, Any]:
        return {
            "shape": self.SHAPE,
            "version": ARTIFACT_VERSION,
            "action": self.action,
            "subject": self.subject,
            "detail": self.detail,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class FileChange:
    SHAPE = "file_change"

    path: str
    added: int
    removed: int
    total_lines: int
    before: str | None = None
    after: str | None = None

    def as_artifact(self) -> dict[str, Any]:
        return {
            "shape": self.SHAPE,
            "version": ARTIFACT_VERSION,
            "path": self.path,
            "added": self.added,
            "removed": self.removed,
            "total_lines": self.total_lines,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class Worker:
    name: str
    started_ms: int
    """Milliseconds after the turn began. Relative rather than absolute so the
    renderer needs no clock skew reasoning, and so a bar means the same thing
    on a replayed turn as on a live one."""
    duration_ms: int | None
    """`None` while still running."""
    ok: bool = True

    def as_artifact(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "started_ms": self.started_ms,
            "duration_ms": self.duration_ms,
            "ok": self.ok,
        }


@dataclass(frozen=True)
class Delegation:
    SHAPE = "delegation"

    task: str
    workers: tuple[Worker, ...]

    def as_artifact(self) -> dict[str, Any]:
        return {
            "shape": self.SHAPE,
            "version": ARTIFACT_VERSION,
            "task": self.task,
            "workers": [worker.as_artifact() for worker in self.workers],
        }


SHAPES: dict[str, type] = {
    cls.SHAPE: cls
    for cls in (
        HitList,
        EntityList,
        Excerpt,
        Inventory,
        Acknowledgement,
        FileChange,
        Delegation,
    )
}
"""Every shape, by discriminator.

Built from the classes rather than hand-written, because a hand-written list
is documentation and the thing this needs to be is a contract -- see
`test_the_registry_names_every_shape_class`.
"""

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

    @classmethod
    def from_text(
        cls,
        source_id: str,
        text: str,
        start: int = 0,
        end: int | None = None,
        char_count: int | None = None,
        title: str | None = None,
        label: str | None = None,
        uri: str | None = None,
    ) -> "Excerpt":
        actual_end = len(text) if end is None else end
        actual_char_count = len(text) if char_count is None else char_count
        snippet = text[start:actual_end]
        return cls(
            source_id=source_id,
            title=title,
            label=label,
            start=start,
            end=actual_end,
            char_count=actual_char_count,
            text=snippet,
            uri=uri,
        )


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

    @classmethod
    def success(
        cls, action: str, subject: str, detail: str | None = None
    ) -> "Acknowledgement":
        return cls(action=action, subject=subject, detail=detail, ok=True)

    @classmethod
    def failure(
        cls, action: str, subject: str, detail: str | None = None
    ) -> "Acknowledgement":
        return cls(action=action, subject=subject, detail=detail, ok=False)


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

    @classmethod
    def from_diff(
        cls,
        path: str,
        before: str | None,
        after: str | None,
    ) -> "FileChange":
        import difflib

        before_lines = before.splitlines(keepends=True) if before else []
        after_lines = after.splitlines(keepends=True) if after else []
        diff = list(difflib.unified_diff(before_lines, after_lines))
        added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
        removed = sum(
            1 for line in diff if line.startswith("-") and not line.startswith("---")
        )
        total_lines = len(after_lines)
        return cls(
            path=path,
            added=added,
            removed=removed,
            total_lines=total_lines,
            before=before,
            after=after,
        )


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


def parse_artifact(data: dict[str, Any]) -> Any:
    """Parse a serialized artifact dict back into its typed dataclass shape.

    Returns None if `data` is not an artifact dict or has an unknown shape.
    """
    if not isinstance(data, dict):
        return None
    shape = data.get("shape")
    match shape:
        case HitList.SHAPE:
            sources = tuple(
                SourceHits(
                    source_id=src["source_id"],
                    title=src.get("title"),
                    label=src.get("label"),
                    char_count=src.get("char_count", 0),
                    total=src.get("total", 0),
                    hits=tuple(
                        Hit(start=h["start"], end=h["end"], snippet=h.get("snippet", ""))
                        for h in src.get("hits", [])
                    ),
                )
                for src in data.get("sources", [])
            )
            return HitList(
                pattern=data.get("pattern", ""),
                total=data.get("total", 0),
                suppressed=data.get("suppressed", 0),
                sources=sources,
            )
        case EntityList.SHAPE:
            entities = tuple(
                EntityRef(
                    entity_id=ent["entity_id"],
                    name=ent["name"],
                    entity_type=ent["entity_type"],
                    relationship_count=ent.get("relationship_count", 0),
                )
                for ent in data.get("entities", [])
            )
            return EntityList(
                query=data.get("query", ""),
                entities=entities,
                mode=data.get("mode", ""),
            )
        case Excerpt.SHAPE:
            return Excerpt(
                source_id=data["source_id"],
                title=data.get("title"),
                label=data.get("label"),
                start=data.get("start", 0),
                end=data.get("end", 0),
                char_count=data.get("char_count", 0),
                text=data.get("text", ""),
                uri=data.get("uri"),
            )
        case Inventory.SHAPE:
            items = tuple(
                InventoryItem(
                    item_id=it["item_id"],
                    title=it.get("title"),
                    label=it.get("label"),
                    size=it.get("size", 0),
                    detail=it.get("detail"),
                )
                for it in data.get("items", [])
            )
            return Inventory(
                kind=data.get("kind", ""),
                unit=data.get("unit", ""),
                total=data.get("total", 0),
                items=items,
            )
        case Acknowledgement.SHAPE:
            return Acknowledgement(
                action=data.get("action", ""),
                subject=data.get("subject", ""),
                detail=data.get("detail"),
                ok=data.get("ok", True),
            )
        case FileChange.SHAPE:
            return FileChange(
                path=data.get("path", ""),
                added=data.get("added", 0),
                removed=data.get("removed", 0),
                total_lines=data.get("total_lines", 0),
                before=data.get("before"),
                after=data.get("after"),
            )
        case Delegation.SHAPE:
            workers = tuple(
                Worker(
                    name=w.get("name", ""),
                    started_ms=w.get("started_ms", 0),
                    duration_ms=w.get("duration_ms"),
                    ok=w.get("ok", True),
                )
                for w in data.get("workers", [])
            )
            return Delegation(
                task=data.get("task", ""),
                workers=workers,
            )
        case _:
            return None

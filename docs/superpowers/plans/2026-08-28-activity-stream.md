# Activity Stream Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render every tool result in the console as a designed, information-dense card driven by structured data the tool itself produces, instead of printing the string the model reads.

**Architecture:** Each converted tool returns `(existing_string, artifact)` via LangChain's `response_format="content_and_artifact"`. The artifact is a plain JSON dict with a `shape` discriminator, persisted for free inside `message_to_dict(ToolMessage)` and broadcast for free by `activity.py`. The browser parses it into a discriminated union and dispatches to one of seven shape components, shared by the in-flight feed and the committed transcript. An absent or unrecognised artifact falls back to today's text rendering, permanently.

**Tech Stack:** Python 3.12 · LangChain `@tool` · FastAPI/Starlette · React 19 · TypeScript · Zod · Tailwind v4 · vitest (jsdom + browser mode)

**Spec:** `docs/superpowers/specs/2026-08-28-activity-stream-design.md` — read it first; this plan argues from it.

## Global Constraints

- **Four gates, all of them, every task:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`. The two ruff commands run over the whole repository, not the files you touched.
- **`npm run test:browser` is mandatory in this plan** (Tasks 8–13) though it is not a CI gate. jsdom lays nothing out: `getComputedStyle` returns only what an inline style said and `scrollHeight` is 0 everywhere.
- **Never run two `vitest` processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- **Tool return strings must not change.** Every `format_*` function keeps its exact current output. The artifact is additive. A test in Task 2 pins this.
- **`shape` and `version: 1` on every artifact dict.**
- **Offsets and totals on the wire, never percentages.**
- **No Tailwind utility may be relied on to override an unlayered rule in `tokens.css`.** `button`, `input`, `textarea`, `select` carry unlayered `background`, `color` and `font: inherit` there; `font` is a shorthand, so it sets `font-size` and defeats `text-xs` too. Style stream controls with named classes in `frontend/src/styles/stream.css`.
- **`border-0` beside a *directional* width is the correct pairing; `border-0 border` is a conflict.** The spine is a directional border.
- **Prove every test red before trusting it green.** Do not use `git checkout <file>` to undo a deliberate break — it discards the rest of your uncommitted edits in that file. Comment the line out and restore it by hand.
- **Commit after every task.** Stage and commit in one shell invocation.

---

## File Structure

**Python — created**

- `research_team/application/tool_artifacts.py` — the seven artifact dataclasses, the `SHAPES` registry, and `ARTIFACT_VERSION`. Pure: no I/O, no imports from `infrastructure/`.
- `tests/application/test_tool_artifacts.py` — shape construction and the registry-coverage contract.
- `tests/infrastructure/test_tool_artifacts_from_real_tools.py` — drives real tools over real seeded stores.

**Python — modified**

- `research_team/infrastructure/agent/corpus_tools.py` — `search_sources`, `read_source`, `list_sources` return artifacts.
- `research_team/infrastructure/agent/knowledge_tools.py` — `graph_search`, `graph_describe`, `remember`, `remember_page`, `unmerge`.
- `research_team/infrastructure/agent/search.py` — `search`.
- `research_team/infrastructure/agent/topic_tools.py` — `list_topics`, `open_topic`, `record_finding`, `record_gap`, `link_source`.
- `research_team/infrastructure/agent/fetch.py` — `fetch`.
- `research_team/interfaces/web/presenters.py` — `message_view` passes `name` and `artifact`.

**TypeScript — created**

- `frontend/src/domain/conversation/artifact.ts` — the union, `artifactOf`, and `SHAPE_GLYPH`.
- `frontend/src/presentation/session/shapes/ToolResult.tsx` — the dispatcher.
- `frontend/src/presentation/session/shapes/{HitList,EntityList,Excerpt,Inventory,Acknowledgement,FileChange,Delegation}.tsx`
- `frontend/src/presentation/session/shapes/parts.tsx` — `Row`, `Header`, `Bar`, `Sparkline`, `Expander`, `Quote`. Shared primitives, so seven components do not each invent a bar.
- `frontend/src/styles/stream.css` — spine, phase, shape rules.

**TypeScript — modified**

- `frontend/src/infrastructure/http/dto.ts`, `mappers.ts` — carry `name` and `artifact`.
- `frontend/src/domain/conversation/message.ts` — `Message` gains `name` and `artifact`.
- `frontend/src/domain/activity/activity.ts` — `activityBody` keeps its job as the fallback only.
- `frontend/src/presentation/session/ActivityFeed.tsx`, `Segments.tsx` — render through `ToolResult`.

---

### Task 1: The artifact vocabulary

**Files:**
- Create: `research_team/application/tool_artifacts.py`
- Test: `tests/application/test_tool_artifacts.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ARTIFACT_VERSION: int`, `SHAPES: dict[str, type]`, and seven frozen dataclasses each with `as_artifact() -> dict[str, Any]`: `HitList`, `EntityList`, `Excerpt`, `Inventory`, `Acknowledgement`, `FileChange`, `Delegation`. Supporting records: `SourceHits`, `Hit`, `EntityRef`, `InventoryItem`, `Worker`.

- [ ] **Step 1: Write the failing test**

```python
"""The artifact vocabulary the console renders from."""

from research_team.application.tool_artifacts import (
    ARTIFACT_VERSION,
    SHAPES,
    EntityList,
    EntityRef,
    Hit,
    HitList,
    SourceHits,
)


def test_a_hit_list_carries_offsets_and_totals_not_percentages() -> None:
    """The bar widths are the renderer's business; a percentage on the wire
    cannot be turned back into the range a citation needs."""
    artifact = HitList(
        pattern="magic",
        total=19,
        suppressed=0,
        sources=(
            SourceHits(
                source_id="manuscriptreport-com-blog-42e281d8",
                title="manuscriptreport.com",
                label="types of fictional genres",
                char_count=25784,
                total=9,
                hits=(Hit(start=1529, end=1694, snippet="…use of magic…"),),
            ),
        ),
    ).as_artifact()

    assert artifact["shape"] == "hit_list"
    assert artifact["version"] == ARTIFACT_VERSION
    assert artifact["total"] == 19
    assert artifact["sources"][0]["char_count"] == 25784
    assert artifact["sources"][0]["hits"][0] == {
        "start": 1529,
        "end": 1694,
        "snippet": "…use of magic…",
    }
    assert not any("percent" in key for key in artifact["sources"][0])


def test_an_unlinked_entity_is_zero_not_absent() -> None:
    """`0 relationship(s)` is the graph's most actionable gap. It has to
    survive to the renderer as a value, not as an omission."""
    artifact = EntityList(
        query="magic",
        entities=(
            EntityRef(entity_id="c0eaaeba", name="Magic Systems", entity_type="concept",
                      relationship_count=2),
            EntityRef(entity_id="af6f2548", name="magic", entity_type="concept",
                      relationship_count=0),
        ),
        mode="fused",
    ).as_artifact()

    assert [entity["relationship_count"] for entity in artifact["entities"]] == [2, 0]


def test_the_registry_names_every_shape_class() -> None:
    """Derived by introspection rather than hand-listed, so an eighth shape
    fails here instead of rendering as a permanent fallback nobody notices."""
    import research_team.application.tool_artifacts as module

    declared = {
        value.SHAPE
        for value in vars(module).values()
        if isinstance(value, type) and hasattr(value, "SHAPE")
    }
    assert set(SHAPES) == declared
    assert len(SHAPES) == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_tool_artifacts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.application.tool_artifacts'`

- [ ] **Step 3: Write the implementation**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/application/test_tool_artifacts.py -v`
Expected: 3 passed

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && \
git add research_team/application/tool_artifacts.py tests/application/test_tool_artifacts.py && \
git commit -m "Add the artifact vocabulary the console will render from"
```

---

### Task 2: Corpus tools produce artifacts

**Files:**
- Modify: `research_team/infrastructure/agent/corpus_tools.py`
- Test: `tests/infrastructure/test_corpus_tool_artifacts.py`

**Interfaces:**
- Consumes: `HitList`, `SourceHits`, `Hit`, `Excerpt`, `Inventory`, `InventoryItem` from Task 1.
- Produces: `build_corpus_tools` unchanged in signature; its three tools now return `tuple[str, dict]`. New pure builders `hit_list_artifact(pattern, hits, suppressed, listings) -> HitList`, `excerpt_artifact(document, span) -> Excerpt`, `inventory_artifact(listings) -> Inventory`.

- [ ] **Step 1: Write the failing test**

```python
"""Artifacts from the corpus tools, driven through the real tool objects."""

import pytest

from research_team.infrastructure.agent.corpus_tools import build_corpus_tools


def tool_named(tools, name):
    return next(tool for tool in tools if tool.name == name)


@pytest.mark.asyncio
async def test_search_sources_reports_every_hit_it_printed(seeded_corpus) -> None:
    tools = build_corpus_tools(seeded_corpus)
    text, artifact = await tool_named(tools, "search_sources").ainvoke(
        {"pattern": "magic"}
    )

    assert artifact["shape"] == "hit_list"
    carried = sum(len(source["hits"]) for source in artifact["sources"])
    assert carried == text.count(" | "), (
        "every line the model was shown is a hit the console can draw"
    )
    assert artifact["total"] >= carried


@pytest.mark.asyncio
async def test_the_string_the_model_reads_did_not_change(seeded_corpus) -> None:
    """The whole design rests on this: the artifact is additive, so no prompt,
    checkpoint or eval moves. Red if a tool starts formatting for the console."""
    from research_team.infrastructure.agent import corpus_tools

    tools = build_corpus_tools(seeded_corpus)
    text, _ = await tool_named(tools, "search_sources").ainvoke({"pattern": "magic"})

    listings = await seeded_corpus.list_sources()
    hits, suppressed = corpus_tools.collect_matches("magic", listings)
    assert text == corpus_tools.format_matches("magic", hits, suppressed)


@pytest.mark.asyncio
async def test_an_excerpt_carries_the_span_and_the_whole_length(seeded_corpus) -> None:
    """The ruler is the point of this card: 9% of a document read from near
    its start is a different claim than the whole of it."""
    tools = build_corpus_tools(seeded_corpus)
    _, artifact = await tool_named(tools, "read_source").ainvoke(
        {"source_id": "seed-one", "start": 100, "end": 300}
    )

    assert artifact["shape"] == "excerpt"
    assert artifact["start"] == 100
    assert artifact["end"] <= 300
    assert artifact["char_count"] > artifact["end"] - artifact["start"]


@pytest.mark.asyncio
async def test_an_empty_corpus_still_answers_with_a_shape(empty_corpus) -> None:
    """A miss is a rendering, not a fallback. `sources: []` draws "no matches
    for X"; a `None` artifact would silently drop to the text path and look
    identical to a tool nobody converted."""
    tools = build_corpus_tools(empty_corpus)
    _, artifact = await tool_named(tools, "search_sources").ainvoke({"pattern": "x"})

    assert artifact["shape"] == "hit_list"
    assert artifact["sources"] == []
```

Add to `tests/infrastructure/conftest.py` (or the nearest existing conftest — check first; do not create a duplicate basename, which aborts collection for the whole run):

```python
@pytest.fixture
def seeded_corpus():
    """A corpus holding two real documents.

    Deliberately NOT built by calling the same reader the tool under test
    calls -- see CLAUDE.md on fixtures that supply the contract they are
    testing. This seeds through the writer.
    """
    ...  # follow the existing corpus fixtures in tests/infrastructure/
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_corpus_tool_artifacts.py -v`
Expected: FAIL — the tool returns a `str`, so tuple unpacking raises `ValueError: too many values to unpack`.

- [ ] **Step 3: Implement**

Extract the match-collecting loop currently inline in `search_sources` into a module-level `collect_matches(pattern, listings) -> tuple[list[tuple[str, Span]], int]` so the string test above can call it. Then:

```python
    @tool(SEARCH_SOURCES_TOOL, response_format="content_and_artifact")
    async def search_sources(
        pattern: str, source_id: str | None = None
    ) -> tuple[str, dict[str, Any]]:
        """Search stored sources for a regular expression, reporting
        `source_id@start-end` for every match."""
        # ... existing validation, unchanged, each early return now paired
        # with an Acknowledgement(ok=False) artifact so a failure renders as a
        # failure rather than as a card with nothing in it.
        hits, suppressed = collect_matches(expression, listings)
        return (
            format_matches(pattern, hits, suppressed),
            hit_list_artifact(pattern, hits, suppressed, listings).as_artifact(),
        )
```

`hit_list_artifact` groups `hits` by `source_id`, looks each source's `title` and `char_count` up from `listings`, and sets `SourceHits.total` from the per-source count *before* `MAX_PER_SOURCE` truncation. Do the same for `read_source` (`Excerpt`) and `list_sources` (`Inventory`, `unit="chars"`, media items contributing `size` in bytes with `detail=media_type` — and note the unit mismatch in a comment, because one bar axis over two units is the grid mistake in miniature; carry media items with `size=0` and their byte count in `detail` rather than drawing them on the character axis).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/infrastructure/test_corpus_tool_artifacts.py -v`
Expected: 4 passed

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest tests/infrastructure -q && \
git add research_team/infrastructure/agent/corpus_tools.py tests/infrastructure/ && \
git commit -m "Corpus tools hand the console the structure they already computed"
```

---

### Task 3: Knowledge tools produce artifacts

**Files:**
- Modify: `research_team/infrastructure/agent/knowledge_tools.py`
- Test: `tests/infrastructure/test_knowledge_tool_artifacts.py`

**Interfaces:**
- Consumes: `EntityList`, `EntityRef`, `Acknowledgement` from Task 1.
- Produces: `entity_list_artifact(query: str, outcome: SearchOutcome) -> EntityList`; `graph_search`, `graph_describe`, `remember`, `remember_page`, `unmerge` returning `tuple[str, dict]`.

- [ ] **Step 1: Write the failing test**

```python
"""Artifacts from the knowledge tools."""

import pytest

from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools


def tool_named(tools, name):
    return next(tool for tool in tools if tool.name == name)


@pytest.mark.asyncio
async def test_an_unlinked_entity_survives_to_the_artifact(seeded_graph) -> None:
    """The graph's most actionable fact is an entity connected to nothing, and
    the current rendering makes it the least visible thing on the card."""
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await tool_named(tools, "graph_search").ainvoke({"query": "magic"})

    counts = [entity["relationship_count"] for entity in artifact["entities"]]
    assert 0 in counts, "seed the fixture with an orphan or this proves nothing"
    assert artifact["shape"] == "entity_list"


@pytest.mark.asyncio
async def test_the_search_mode_reaches_the_console(seeded_graph) -> None:
    """`SearchOutcome.mode` exists to make a silent degradation visible. A
    console that drops it restores the silence."""
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await tool_named(tools, "graph_describe").ainvoke({"query": "magic"})

    assert artifact["mode"] in {"fused", "cards", "unavailable"}


@pytest.mark.asyncio
async def test_a_failed_unmerge_is_an_acknowledgement_that_says_so(seeded_graph) -> None:
    tools = build_knowledge_tools(seeded_graph)
    _, artifact = await tool_named(tools, "unmerge").ainvoke(
        {"merge_id": "00000000-0000-0000-0000-000000000000"}
    )

    assert artifact["shape"] == "acknowledgement"
    assert artifact["ok"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_knowledge_tool_artifacts.py -v`
Expected: FAIL — `ValueError: too many values to unpack`

- [ ] **Step 3: Implement**

```python
def entity_list_artifact(query: str, outcome: SearchOutcome) -> EntityList:
    """The matches as the console draws them.

    Sorted here rather than in the renderer: the order is a property of the
    answer (most connected first, orphans last), and two sorts that must agree
    is one sort too many.
    """
    return EntityList(
        query=query,
        mode=str(outcome.mode),
        entities=tuple(
            EntityRef(
                entity_id=str(match.entity_id),
                name=match.name,
                entity_type=match.entity_type,
                relationship_count=match.relationship_count,
            )
            for match in sorted(
                outcome.matches, key=lambda m: -m.relationship_count
            )
        ),
    )
```

Every `except KnowledgeError` branch that currently returns an error string returns `(that_string, Acknowledgement(action=…, subject=…, detail=str(error), ok=False).as_artifact())`.

- [ ] **Step 4: Run tests** — `uv run pytest tests/infrastructure/test_knowledge_tool_artifacts.py -v` → 3 passed

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && \
git add research_team/infrastructure/agent/knowledge_tools.py tests/infrastructure/test_knowledge_tool_artifacts.py && \
git commit -m "Knowledge tools carry relationship counts and search mode to the console"
```

---

### Task 4: Search, topic and fetch tools produce artifacts

**Files:**
- Modify: `research_team/infrastructure/agent/search.py`, `topic_tools.py`, `fetch.py`
- Test: `tests/infrastructure/test_remaining_tool_artifacts.py`

**Interfaces:**
- Consumes: every shape from Task 1; `entity_list_artifact` from Task 3.
- Produces: `search` → `EntityList`; `list_topics` → `Inventory(kind="topics", unit="findings")`; `open_topic` → `Inventory(kind="topic", unit="findings")`; `record_finding`, `record_gap`, `link_source` → `Acknowledgement`; `fetch` → `Excerpt`.

- [ ] **Step 1: Write the failing test**

```python
"""Every remaining converted tool answers with the shape it claims."""

import pytest


@pytest.mark.parametrize(
    ("tool_name", "args", "shape"),
    [
        ("search", {"query": "magic"}, "entity_list"),
        ("list_topics", {}, "inventory"),
        ("record_finding", {"topic_id": "t1", "text": "a finding"}, "acknowledgement"),
    ],
)
@pytest.mark.asyncio
async def test_each_tool_answers_with_its_shape(all_tools, tool_name, args, shape) -> None:
    tool = next(candidate for candidate in all_tools if candidate.name == tool_name)
    _, artifact = await tool.ainvoke(args)
    assert artifact["shape"] == shape
```

- [ ] **Step 2: Run to verify it fails** — `uv run pytest tests/infrastructure/test_remaining_tool_artifacts.py -v` → FAIL, unpack error.

- [ ] **Step 3: Implement** — same pattern as Tasks 2 and 3: add `response_format="content_and_artifact"`, keep the existing `format_*` call as the first element, build the shape from the same data it already has.

- [ ] **Step 4: Run tests** — 3 passed.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && \
git add research_team/infrastructure/agent/ tests/infrastructure/test_remaining_tool_artifacts.py && \
git commit -m "The remaining read tools answer in shapes"
```

---

### Task 5: The wire carries name and artifact, and the registry is a contract

**Files:**
- Modify: `research_team/interfaces/web/presenters.py:184-196` (`message_view`)
- Test: `tests/interfaces/test_message_view_artifacts.py`, `tests/infrastructure/test_tool_artifacts_from_real_tools.py`

**Interfaces:**
- Consumes: `SHAPES` from Task 1; every converted tool from Tasks 2–4.
- Produces: `message_view` returns two new keys, `name: str | None` and `artifact: dict | None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_tool_message_carries_its_name_and_artifact() -> None:
    """Both are already in the stored payload and were being dropped."""
    view = message_view(
        {
            "type": "tool",
            "data": {
                "content": "19 match(es) …",
                "name": "search_sources",
                "artifact": {"shape": "hit_list", "version": 1, "sources": []},
            },
        }
    )
    assert view["name"] == "search_sources"
    assert view["artifact"]["shape"] == "hit_list"


def test_a_message_written_before_artifacts_existed_carries_none() -> None:
    """The permanent path, not an error case: every historical message takes
    it, and the console must render text rather than an empty card."""
    view = message_view({"type": "tool", "data": {"content": "19 match(es) …"}})
    assert view["artifact"] is None
    assert view["content"] == "19 match(es) …"
```

And the contract test the whole design rests on:

```python
"""Real tools, real stores, real artifacts.

This is the *port with one adapter* rule from CLAUDE.md. The co-mention channel
shipped fully unit-tested from both sides and produced nothing for a whole
feature, because nothing drove the real writer into the real reader. A renderer
test fed a hand-written literal cannot see a tool that never populates its
artifact.
"""

import pytest

from research_team.application.tool_artifacts import SHAPES

PRODUCED_BY_TOOLS = {
    "hit_list", "entity_list", "excerpt", "inventory", "acknowledgement",
}
NOT_TOOL_PRODUCED = {"file_change", "delegation"}


def test_the_registry_covers_every_shape_a_tool_can_produce() -> None:
    """Fails at collection if an eighth shape is added and left unclaimed by
    either set -- documentation would not."""
    assert PRODUCED_BY_TOOLS | NOT_TOOL_PRODUCED == set(SHAPES)


@pytest.mark.parametrize("shape", sorted(PRODUCED_BY_TOOLS))
@pytest.mark.asyncio
async def test_every_shape_is_produced_by_a_real_tool_call(live_tools, shape) -> None:
    produced = set()
    for tool, args in live_tools:
        _, artifact = await tool.ainvoke(args)
        if artifact:
            produced.add(artifact["shape"])
    assert shape in produced, f"no real tool call produced a {shape} artifact"
```

- [ ] **Step 2: Run to verify they fail** — `KeyError: 'name'`.

- [ ] **Step 3: Implement**

```python
def message_view(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", {})
    return {
        "role": _ROLE_FOR_TYPE.get(payload.get("type", ""), payload.get("type", "")),
        "content": data.get("content", ""),
        # Both already sit in the stored payload -- `message_to_dict` keeps
        # every field of a `ToolMessage` -- and both were being dropped here.
        # `name` is what lets the console pair a result with its call; the
        # artifact is what lets it draw anything but the model's own string.
        "name": data.get("name"),
        "artifact": data.get("artifact"),
        "tool_calls": [...],  # unchanged
        "is_error": data.get("status") == "error",
    }
```

- [ ] **Step 4: Run tests** — all pass.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q && \
git add research_team/interfaces/web/presenters.py tests/ && \
git commit -m "Stop dropping the tool name and artifact on the way to the browser"
```

---

### Task 6: The browser parses an artifact, or does not

**Files:**
- Create: `frontend/src/domain/conversation/artifact.ts`, `frontend/src/domain/conversation/artifact.test.ts`
- Modify: `frontend/src/infrastructure/http/dto.ts`, `mappers.ts`, `frontend/src/domain/conversation/message.ts`

**Interfaces:**
- Consumes: the wire shape from Task 5.
- Produces: `type Artifact` (discriminated union on `shape`), `artifactOf(message: Message): Artifact | null`, `SHAPE_GLYPH: Record<Artifact['shape'], string>`. `Message` gains `readonly name: string | null` and `readonly artifact: unknown`.

- [ ] **Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import { artifactOf } from './artifact.ts'

const message = (artifact: unknown) => ({
  role: 'tool' as const, content: '19 match(es) …', toolCalls: [], isError: false,
  name: 'search_sources', artifact,
})

describe('artifactOf', () => {
  it('parses a hit list', () => {
    const parsed = artifactOf(message({
      shape: 'hit_list', version: 1, pattern: 'magic', total: 19, suppressed: 0,
      sources: [{ source_id: 's1', title: 'a', label: null, char_count: 100,
                  total: 2, hits: [{ start: 1, end: 5, snippet: 'x' }] }],
    }))
    expect(parsed?.shape).toBe('hit_list')
    expect(parsed?.shape === 'hit_list' && parsed.sources[0]?.hits[0]?.start).toBe(1)
  })

  it('returns null for a message written before artifacts existed', () => {
    // The permanent path. Every historical message takes it, so it is tested
    // as a path and not as an error case.
    expect(artifactOf(message(null))).toBeNull()
  })

  it('returns null for a shape it does not know', () => {
    // Distinct from the case above only in what produced it; both fall back
    // to text, which is why `version` is on the wire at all.
    expect(artifactOf(message({ shape: 'hologram', version: 1 }))).toBeNull()
  })

  it('returns null rather than throwing on a malformed artifact', () => {
    // A card that throws takes the whole transcript down with it.
    expect(artifactOf(message({ shape: 'hit_list', version: 1 }))).toBeNull()
  })
})
```

- [ ] **Step 2: Run to verify it fails** — `cd frontend && npx vitest run src/domain/conversation/artifact.test.ts` → cannot resolve `./artifact.ts`.

- [ ] **Step 3: Implement** with Zod schemas per shape and a `z.discriminatedUnion('shape', […])`, wrapped in `safeParse` so an unknown or malformed artifact yields `null`. Add `artifact: z.unknown().nullish()` and `name: z.string().nullish()` to `messageDto`, and carry both through `toMessage`.

- [ ] **Step 4: Run tests** — 4 passed.

- [ ] **Step 5: Gates and commit**

```bash
cd frontend && npm run verify && cd .. && \
git add frontend/src/domain frontend/src/infrastructure && \
git commit -m "Parse a tool artifact, or fall back to text as a first-class path"
```

---

### Task 7: The spine and the dispatcher

**Files:**
- Create: `frontend/src/presentation/session/shapes/ToolResult.tsx`, `parts.tsx`, `frontend/src/styles/stream.css`
- Modify: `frontend/src/presentation/session/ActivityFeed.tsx`, `Segments.tsx`
- Test: `ToolResult.test.tsx`, `spine.browser.test.tsx`

**Interfaces:**
- Consumes: `artifactOf`, `SHAPE_GLYPH` from Task 6.
- Produces: `<ToolResult message={Message} phase={'live' | 'settled'} />`; `<Row glyph phase>`, `<Header name arg count>`, `<Bar value max>`, `<Sparkline positions total>`, `<Expander label>`, `<Quote>` from `parts.tsx`.

**Read before writing CSS:** the "Styling constraints" section of the spec. The `Expander` is a `<button>`, and `tokens.css` gives every bare `button` an unlayered `background`, `color` and `font: inherit` that beats any Tailwind utility including the size utilities. Style it with a named class in `stream.css`.

- [ ] **Step 1: Write the failing tests**

```tsx
it('falls back to the tool text when there is no artifact', () => {
  render(<ToolResult message={{ ...toolMessage, artifact: null }} phase="settled" />)
  expect(screen.getByText(/19 match\(es\)/)).toBeInTheDocument()
})

it('renders a shape when there is an artifact', () => {
  render(<ToolResult message={hitListMessage} phase="settled" />)
  expect(screen.queryByText(/19 match\(es\) for/)).not.toBeInTheDocument()
  expect(screen.getByText('manuscriptreport.com')).toBeInTheDocument()
})
```

```tsx
// spine.browser.test.tsx — a measurement, so it is a browser test.
it('draws one edge, not four', async () => {
  const { getByTestId } = render(<ToolResult message={hitListMessage} phase="settled" />)
  const style = getComputedStyle(getByTestId('stream-gutter'))
  expect(style.borderLeftWidth).toBe('1px')
  expect(style.borderTopWidth).toBe('0px')
  expect(style.borderRightWidth).toBe('0px')
  expect(style.borderBottomWidth).toBe('0px')
})

it('gives the expander the size the class asks for', async () => {
  // tokens.css sets `font: inherit` on every bare button, unlayered, which
  // beats any utility -- including the size ones, because `font` is a
  // shorthand. Red if the expander is styled with a utility.
  const { getByRole } = render(<ToolResult message={hitListMessage} phase="settled" />)
  expect(getComputedStyle(getByRole('button')).fontSize).toBe('10px')
})
```

- [ ] **Step 2: Run to verify they fail.** Run jsdom and browser suites **separately**, never concurrently.

- [ ] **Step 3: Implement.** `ToolResult` calls `artifactOf`; on `null` it renders `activityBody(entry)`'s text exactly as today. `ActivityFeed` renders `<ToolResult phase="live">`, `Segments` renders `<ToolResult phase="settled">`. Delete the per-card `in progress — not yet recorded` div from `ActivityFeed` — phase is position now.

- [ ] **Step 4: Run both suites, one at a time.**

- [ ] **Step 5: Gates and commit**

```bash
cd frontend && npm run verify && npm run test:browser && cd .. && \
git add frontend/src && \
git commit -m "One spine, one dispatcher, and the provisional banner deleted"
```

---

### Task 8: Hit list and entity list

**Files:** Create `HitList.tsx`, `EntityList.tsx` and their `.test.tsx`; `entity-list.browser.test.tsx`.

**Interfaces:** Consumes `parts.tsx` from Task 7. Produces `<HitList artifact phase />`, `<EntityList artifact phase />`.

- [ ] **Step 1: Write the failing tests**

```tsx
it('caps at five and says how many are behind the expander', () => {
  render(<EntityList artifact={tenEntities} phase="settled" />)
  expect(screen.getAllByTestId('entity')).toHaveLength(5)
  expect(screen.getByRole('button', { name: /5 more/ })).toBeInTheDocument()
})

it('separates unlinked entities and does not label them 0', () => {
  render(<EntityList artifact={withOrphans} phase="settled" />)
  const orphan = screen.getByTestId('entity-magic')
  expect(orphan).toHaveTextContent('–')
  expect(orphan).not.toHaveTextContent('0')
})

it('sorts by relationship count', () => {
  render(<EntityList artifact={tenEntities} phase="settled" />)
  const names = screen.getAllByTestId('entity').map((n) => n.textContent)
  expect(names[0]).toContain('science fiction')
})
```

```tsx
// entity-list.browser.test.tsx
it('puts every bar on one axis', async () => {
  // A grid gives each column its own baseline, so two bars side by side are
  // not on a common scale. This asserts the property that makes the bar mean
  // anything: equal left edges, widths in proportion to the values.
  const { getAllByTestId } = render(<EntityList artifact={tenEntities} phase="settled" />)
  const bars = getAllByTestId('bar').map((n) => n.getBoundingClientRect())
  expect(new Set(bars.map((b) => Math.round(b.left))).size).toBe(1)
  expect(bars[0].width / bars[1].width).toBeCloseTo(6 / 2, 1)
})
```

- [ ] **Step 2: Run to verify they fail.**
- [ ] **Step 3: Implement** per the reference HTML: `HitList` draws a sparkline per source positioning each hit at `start / char_count`, then one representative snippet below a rule; `EntityList` sorts by count, caps at five, and drops unlinked entities below a rule with `–`.
- [ ] **Step 4: Run both suites separately.**
- [ ] **Step 5:** `npm run verify && npm run test:browser`, then commit.

---

### Task 9: Excerpt, inventory and acknowledgement

**Files:** Create `Excerpt.tsx`, `Inventory.tsx`, `Acknowledgement.tsx` and their tests.

**Interfaces:** Consumes `parts.tsx`. Produces the three components.

- [ ] **Step 1: Write the failing tests**

```tsx
it('shows which span of the document was read', () => {
  render(<Excerpt artifact={{ ...excerpt, start: 1529, end: 3872, char_count: 25784 }}
                  phase="settled" />)
  expect(screen.getByText(/1\.5k–3\.9k of 25\.8k/)).toBeInTheDocument()
  const ruler = screen.getByTestId('ruler-fill')
  expect(ruler).toHaveStyle({ width: '9.09%' })
})

it('renders an acknowledgement as one line with no expander', () => {
  render(<Acknowledgement artifact={ack} phase="settled" />)
  expect(screen.queryByRole('button')).not.toBeInTheDocument()
})

it('marks a failed acknowledgement', () => {
  render(<Acknowledgement artifact={{ ...ack, ok: false }} phase="settled" />)
  expect(screen.getByTestId('ack')).toHaveAttribute('data-ok', 'false')
})
```

- [ ] **Step 2–5:** as above — fail, implement, pass both suites, `npm run verify && npm run test:browser`, commit.

---

### Task 10: File change and delegation

**Files:** Create `FileChange.tsx`, `Delegation.tsx` and their tests. Modify `presenters.py` `event_summary` for `FileEdited` to also emit a `file_change` artifact on the timeline row.

**Interfaces:** Consumes `parts.tsx`; the `FileChange` and `Delegation` shapes from Task 1.

- [ ] **Step 1: Write the failing tests**

```tsx
it('draws the proportion of the file the edit touched', () => {
  render(<FileChange artifact={{ path: 'a.md', added: 34, removed: 9, total_lines: 212,
                                 before: 'x', after: 'y' }} phase="settled" />)
  expect(screen.getByText('+34 −9')).toBeInTheDocument()
})

it('shows workers on one wall-clock axis so a serialised fan-out looks wrong', () => {
  render(<Delegation artifact={fourWorkers} phase="settled" />)
  const bars = screen.getAllByTestId('worker-bar')
  expect(bars[0]).toHaveStyle({ left: '0%' })
  expect(bars[3]).toHaveAttribute('data-running', 'true')
})
```

- [ ] **Step 2–5:** fail, implement, both suites, commit.

---

### Task 11: Phase treatment

**Files:** Modify `stream.css`, `parts.tsx`. Create `phase.browser.test.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
it('does not change a card when its turn commits', async () => {
  // The property the whole "phase is position" decision rests on. If this is
  // red, a reader watching a turn sees every card jump as it settles.
  const live = render(<ToolResult message={hitListMessage} phase="live" />)
  const liveBox = live.getByTestId('stream-body').getBoundingClientRect()
  live.unmount()
  const settled = render(<ToolResult message={hitListMessage} phase="settled" />)
  const settledBox = settled.getByTestId('stream-body').getBoundingClientRect()

  expect(settledBox.width).toBe(liveBox.width)
  expect(settledBox.height).toBe(liveBox.height)
})

it('marks only the live edge', async () => {
  const { getByTestId } = render(<ToolResult message={hitListMessage} phase="live" />)
  expect(getByTestId('stream-glyph')).toHaveAttribute('data-phase', 'live')
})
```

- [ ] **Step 2–5:** fail, implement (pulse and accent only — no geometry may differ between phases), both suites, commit.

---

### Task 12: Verify against a real database

**Files:** No production changes expected. Create `docs/superpowers/plans/notes/2026-08-28-real-database-check.md` recording what was seen.

CLAUDE.md: a read-model or rendering change verified only against a fresh database is unverified. Every message in a real log predates artifacts, so this is the fallback path's only honest test.

- [ ] **Step 1: Make a copy that opens**

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/artifact-check.db
```

Do **not** delete `projection_checkpoints` to get it up — that replays the whole log and hides the half of any defect that matters.

- [ ] **Step 2: Serve the console against it**

```bash
cd frontend && npm run build && cd ..
AGENT_DB=/tmp/artifact-check.db uv run web.py
```

- [ ] **Step 3: Open a session that predates this work and confirm** every tool result renders as text, no card is empty, and nothing throws in the console.

- [ ] **Step 4: Run one live turn** against the configured endpoint (`192.168.1.14:8080`; do not change the configured model) and confirm the new cards draw, in flight and after commit.

- [ ] **Step 5: Write the note and commit.** Say what was measured and on what date, not what was reasoned.

---

### Task 13: Full verification and PR

- [ ] **Step 1:** `uv run ruff check .`
- [ ] **Step 2:** `uv run ruff format --check .`
- [ ] **Step 3:** `uv run pytest`
- [ ] **Step 4:** `cd frontend && npm run verify`
- [ ] **Step 5:** `cd frontend && npm run test:browser` (alone — no other vitest process)
- [ ] **Step 6:** Open the PR, with the spec's argument in the body: what the defect was, why artifacts rather than parsing, what it costs, and what was deliberately left undone.

---

## Self-Review

**Spec coverage.** Seam → Tasks 1–5. Seven shapes → Tasks 1, 8, 9, 10. Fallback as a first-class path → Tasks 5, 6, 7, 12. Spine → Task 7. Prose/machinery separation → Task 7 (`stream.css`). One row per tool use → Task 7. Lists capped at five, single axis → Task 8. Phase as position → Tasks 7 and 11. The three named tests → Tasks 5 (both contract tests) and 11. Real-database verification → Task 12. Styling constraints → Task 7, with the browser assertions that catch them.

**Gap found and closed:** the spec's `file_change` shape has no tool that produces it — file edits arrive as deep-agent builtins, not project tools. Task 10 sources it from `event_summary`/`FileEdited` instead, and Task 5's registry test splits `PRODUCED_BY_TOOLS` from `NOT_TOOL_PRODUCED` so the coverage assertion stays honest rather than asserting something false.

**Type consistency.** `as_artifact()` on every shape and every nested record; `artifactOf` in TS everywhere; `phase` is `'live' | 'settled'` in every signature; `SourceHits.total` is the pre-truncation count in both Task 1 and Task 2.

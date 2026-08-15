# Entity definitions and usages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking a graph node shows what the entity is — an LLM definition grounded in corpus passages and graph edges — and where it is talked about, as a ranked list of citable passages.

**Architecture:** Documents are chunked into redstring's `ChunkStore` (in-memory, rebuilt from `DocumentChunked` at project open, exactly as the graph store is). Usages come from BM25 over that store, queried once per name the entity is known by. Definitions are generated from those passages plus the node's edges, cached in a new `entity_definitions` read model, and marked stale by a projection on `DocumentExtracted` and `EntitiesMerged`. Citations are `(source_id, start, end)` throughout.

**Tech Stack:** Python 3.13, redstring 0.8.0, eventsource-py, FastAPI, SQLite read models, React + TanStack Query + zustand, vitest.

**Spec:** `docs/superpowers/specs/2026-08-14-entity-definitions-and-usages-design.md` — read it before Task 1. The plan argues from it and does not restate its reasoning.

## Global Constraints

- **Four gates, all of them, before any task is called done:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository, not the files you touched.
- **Never run two vitest processes at once.** If a frontend test fails, re-run it alone before investigating.
- **`tests/test_architecture.py:155-200` forbids redstring types above `infrastructure/knowledge/`.** No redstring type may appear in `research_team/application/` or `research_team/interfaces/`, including in a type annotation.
- **TDD, and prove each test red before trusting it green.** If a test would pass with its implementation reverted, say so in its docstring or replace it.
- **Comments explain why, state costs, and say when something was measured rather than reasoned.** Commit messages carry what was considered and rejected.
- **redstring is pinned `>=0.8.0,<0.9`.** Do not bump it. Everything this plan needs is in 0.8.0.
- **Citations are `(source_id: str, start: int, end: int)`** everywhere — never a `ChunkId`.
- **No new LLM model configuration.** Definition generation uses the existing extraction model via `config.model_name()`.

---

### Task 1: Chunk store construction

**Files:**
- Modify: `research_team/infrastructure/knowledge/stores.py`
- Modify: `research_team/infrastructure/config.py`
- Test: `tests/infrastructure/test_knowledge_stores.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `build_chunk_store(kind: str, *, dimension: int) -> ChunkStore | None` in `stores.py`; `config.chunk_store() -> str` reading `AGENT_CHUNK_STORE`, defaulting to `"memory"`.

Read `stores.py` in full first. `build_graph_store` and `build_vector_store` are the two shapes to match — including that an unknown kind raises `ValueError` naming it rather than falling back, and that the module docstring explains what each backing costs.

- [ ] **Step 1: Write the failing tests**

Add to `tests/infrastructure/test_knowledge_stores.py`:

```python
def test_an_unknown_chunk_store_kind_is_refused_by_name():
    """A deployment that asked for postgres must not silently get memory."""
    with pytest.raises(ValueError, match="nonsense"):
        build_chunk_store("nonsense", dimension=1536)


def test_chunk_store_none_means_the_feature_is_off():
    assert build_chunk_store("none", dimension=1536) is None


def test_a_memory_chunk_store_takes_the_dimension_it_is_given():
    """Inert under lexical-only retrieval, but wrong here means a corpus that
    cannot be embedded later without rebuilding it."""
    store = build_chunk_store("memory", dimension=1536)
    assert store is not None
    assert store.dimension == 1536
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/infrastructure/test_knowledge_stores.py -k chunk -v`
Expected: FAIL, `ImportError`/`NameError` on `build_chunk_store`.

- [ ] **Step 3: Implement**

In `stores.py`, add `InMemoryChunkStore` and `ChunkStore` to the existing `from redstring import ...` line, then:

```python
def build_chunk_store(kind: str, *, dimension: int) -> ChunkStore | None:
    """The chunk store named by `kind`, or None when `kind` is `none`.

    redstring ships two adapters and no more -- memory and postgres -- so
    `memory` here is the graph's `memory` rather than the vector store's: the
    corpus is derived from `DocumentChunked` and a lost store costs a fold at
    project open, not data. That is the whole reason chunks are event-sourced
    rather than written straight to a table.

    `dimension` is inert under the lexical-only retrieval this system does --
    nothing reads it but `semantic_candidates` and `ChunkRetriever`'s
    constructor, and neither is called. It is taken from the caller's
    configured embedding width anyway, because a corpus indexed under one
    width cannot accept vectors of another without being rebuilt, and the
    day that matters is the day someone turns the semantic channel on.
    """
    if kind == "none":
        return None
    if kind == "memory":
        return InMemoryChunkStore(dimension=dimension)
    if kind == "postgres":
        from redstring.chunks.adapters.postgres import PostgresChunkStore

        # Imported here for the same reason `PgVectorStore` is: it needs an
        # extra this repo does not pin unconditionally, and a default install
        # must not fail to import this module over a dependency it never uses.
        return await_connect_postgres_chunk_store(dimension=dimension)
    raise ValueError(
        f"unknown AGENT_CHUNK_STORE {kind!r}; expected 'none', 'memory' or 'postgres'"
    )
```

**Before writing the `postgres` branch, open `redstring/chunks/adapters/postgres.py` and check whether its constructor is `connect`, whether it is a coroutine, and what it is actually named.** `build_vector_store`'s docstring records that getting exactly this wrong shipped a coroutine object to every caller. If it is async, make `build_chunk_store` async and mirror `build_vector_store` exactly. If that costs more than it is worth for a backing nobody has asked for, **raise `ValueError` for `postgres` with a comment saying it is unwired and why** rather than writing an untested branch — and say so in the module docstring.

In `config.py`, add `chunk_store()` beside `vector_store()`, reading `AGENT_CHUNK_STORE`, defaulting to `"memory"`, with a comment on what the default costs (a fold per project open, proportional to corpus size).

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/infrastructure/test_knowledge_stores.py -k chunk -v`
Expected: PASS.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
git add research_team/infrastructure/knowledge/stores.py research_team/infrastructure/config.py tests/infrastructure/test_knowledge_stores.py
git commit
```

Commit message must say why `memory` is the default and that it is the graph's `memory`, not the vector store's.

---

### Task 2: Fold DocumentChunked at project open

**Files:**
- Modify: `research_team/infrastructure/knowledge/rebuild.py`
- Modify: `research_team/application/project_graphs.py` (wiring the chunk store through project open)
- Test: `tests/infrastructure/test_rebuild.py` (create if absent)

**Interfaces:**
- Consumes: `build_chunk_store` (Task 1).
- Produces: `rebuild_graph(store, *, feed, project_id, chunks: ChunkStore | None = None) -> int` — unchanged signature when `chunks` is None, so no existing caller breaks.

Read the spec section "The replay coupling, and how it actually fails" before starting. The short version: an unhandled event is *applied*, not rejected, so nothing you do here can break an existing project — and forgetting the projection produces an empty corpus that looks exactly like an entity with no mentions.

- [ ] **Step 1: Write the failing test**

```python
async def test_a_project_opened_from_a_log_with_chunkings_comes_up_with_chunks():
    """The assertion is retrieval, not project open.

    An assertion that the project merely opened would pass with
    `ChunkProjection` removed from the sequence -- `eventsource.replay`
    applies an event no projection handles rather than rejecting it -- so it
    would be reassurance rather than a test. Prove this red by dropping
    `chunks` from the projection list.
    """
    # Arrange: write a DocumentChunked into the log for `project_id` by
    # running `index_documents` against a throwaway store and the real feed.
    # Then open a *fresh* store and rebuild into it.
    store = InMemoryChunkStore(dimension=8)
    applied = await rebuild_graph(graph_store, feed=feed, project_id=project_id, chunks=store)

    terms = tokenize("Acme")
    candidates = await store.lexical_candidates(terms, project_id, 10)
    ranked = rank_chunks(terms, candidates, 10)

    assert applied > 0
    assert [r.chunk.text for r in ranked], "chunk corpus came up empty after replay"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/infrastructure/test_rebuild.py -v`
Expected: FAIL — `rebuild_graph` takes no `chunks` keyword.

- [ ] **Step 3: Implement**

In `rebuild.py`, import `ChunkProjection` and `ChunkStore` from `redstring`, add the keyword-only `chunks: ChunkStore | None = None`, and build the projection list:

```python
    projections: list[object] = [GraphProjection(store)]
    if chunks is not None:
        # Folded in the same pass rather than a second replay: the log is read
        # once and both read models are derived from it, so a corpus can never
        # be a different age than the graph it is cited alongside.
        projections.append(ChunkProjection(chunks))
    report = await replay(feed, projections, tenant_id=project_id, strict=True)
```

Keep the existing `ReplayFailedError` handling untouched. Then wire the chunk store through `ProjectGraphs` so the per-project store built in Task 1 is the one handed here and the one the reader later queries — one instance per project, cached and closed alongside the graph store.

- [ ] **Step 4: Run to verify it passes, then prove it red**

Run: `uv run pytest tests/infrastructure/test_rebuild.py -v` → PASS.
Then temporarily remove `projections.append(ChunkProjection(chunks))`, re-run, and confirm FAIL on the empty-corpus assertion. Restore it.

- [ ] **Step 5: Gates and commit**

Commit message states the replay semantics finding: an ignored event counts as applied, so this cannot break an old log, and omitting the projection is a silent empty corpus rather than a refusal.

---

### Task 3: Index documents into the chunk store

**Files:**
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py`
- Modify: `research_team/application/knowledge.py` (port method)
- Test: `tests/infrastructure/test_redstring_adapter.py`

**Interfaces:**
- Consumes: chunk store from Tasks 1–2.
- Produces: `KnowledgePort.index(source: SourceRef) -> None`, implemented on `RedstringKnowledge`, appending `DocumentChunked` to the project's event store.

- [ ] **Step 1: Write the failing test**

```python
async def test_indexing_a_document_writes_retrievable_passages():
    await knowledge.index(SourceRef(project_id=project_id, source_id="doc-1"))

    terms = tokenize("Acme")
    candidates = await chunk_store.lexical_candidates(terms, project_id, 10)
    assert [c for c in rank_chunks(terms, candidates, 10)]


async def test_indexing_the_same_document_twice_writes_nothing_the_second_time():
    """`record_chunking` refuses a repeat under the same signature, so a
    re-index over an unchanged corpus is free rather than duplicating every
    passage. Without the shared event store it would not be -- the repeat is
    recognised from the recorded signature, not from the store's contents."""
    await knowledge.index(SourceRef(project_id=project_id, source_id="doc-1"))
    before = await chunk_count(chunk_store, project_id)
    await knowledge.index(SourceRef(project_id=project_id, source_id="doc-1"))
    assert await chunk_count(chunk_store, project_id) == before
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -k index -v`
Expected: FAIL — no `index` method.

- [ ] **Step 3: Implement**

On `RedstringKnowledge`, add:

```python
    async def index(self, source: SourceRef) -> None:
        """Split one stored document into the chunk corpus. No model call.

        `index_documents` is passed no `embeddings`, which is what makes that
        promise hold -- its own docstring is explicit that supplying one is
        the single way it reaches a model. So this runs on the document-stored
        path rather than behind `ExtractionQueue`: there is no per-token cost
        to defer and nothing worth making durable.

        The `event_store` argument is not optional in practice. Omitted, the
        function builds an `InMemoryEventStore` per call, which suppresses a
        repeat only *within* that call -- so every re-index would rewrite
        every passage, and `documents_skipped` would read 0 forever while
        doing the opposite of what it says.
        """
        document = await self._corpus.read_document(source.source_id)
        await index_documents(
            [SourceDocument(id=source.source_id, text=document.text)],
            store=self._chunks,
            tenant_id=source.project_id,
            chunker=BoundaryPreferenceChunker(),
            event_store=self._event_store,
        )
```

`BoundaryPreferenceChunker` comes from `redstring`; redstring documents it as the chunker to pass when passages will be quoted back to a reader, which is this feature and not extraction's problem. **Confirm its constructor arguments** before instantiating — take its defaults unless a default is obviously wrong for reader-facing passages, and if you pass anything, say why in a comment.

Declare `index` on `KnowledgePort` in `application/knowledge.py` with a docstring; the port names no redstring type, only `SourceRef`.

Then call it where documents become available — the same signal that makes a document extractable. Indexing must not be conditional on extraction having run: a document worth reading is worth finding passages in, whether or not anyone paid to extract entities from it.

- [ ] **Step 4: Run to verify it passes**

- [ ] **Step 5: Gates and commit**

---

### Task 4: Every name an entity is known by

**Files:**
- Create: `research_team/infrastructure/knowledge/aliases.py`
- Test: `tests/infrastructure/test_aliases.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `async def known_names(graph: GraphStore, entity_id: UUID, tenant_id: UUID) -> list[str]` — canonical name first, then alias names, deduplicated, `None` names dropped.

This is the first caller of `AliasStore.find_aliases` in the repository.

- [ ] **Step 1: Write the failing tests**

```python
async def test_an_entity_with_no_merges_is_known_by_its_own_name():
    assert await known_names(graph, acme_id, tenant) == ["Acme Corporation"]


async def test_a_merge_chain_is_walked_to_the_end():
    """`find_aliases` returns direct absorptions only. An entity that absorbed
    an entity that had itself absorbed another loses the deepest name unless
    this recurses -- and that name is exactly the obsolete spelling an old
    document is most likely to use."""
    names = await known_names(graph, acme_id, tenant)
    assert set(names) == {"Acme Corporation", "Acme Corp", "ACME"}


async def test_an_alias_with_no_recorded_name_is_skipped():
    """`Alias.alias_name` is `str | None` because the projection folds
    `EntitiesMerged`, which carries ids and no names. A `None` here must not
    become a blank query -- `retrieve`/`rank` treat a blank as an error."""
    assert None not in await known_names(graph, acme_id, tenant)


async def test_a_cycle_in_the_alias_graph_terminates():
    """Nothing in the port's contract promises acyclicity, and a cycle here
    hangs a request rather than returning a wrong answer. Passes with the
    seen-set removed only if the fixture graph is acyclic -- this one is not."""
    assert await known_names(graph, a_id, tenant)
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

```python
async def known_names(graph, entity_id, tenant_id):
    """Every name this entity may appear under in the corpus, canonical first.

    Order is not cosmetic: the canonical name leads because the caller queries
    once per name and fuses by score, and ties broken toward the canonical
    spelling read better than ties broken arbitrarily.

    Ids are compared with `==` and never `is`. Both existing alias call sites
    carry that warning for the same reason: an adapter may hand back a rebuilt
    `UUID`, so identity comparison is false against an equal id and the walk
    silently terminates early.
    """
    seen: set[UUID] = {entity_id}
    names: list[str] = []
    entity = await graph.get_entity(entity_id, tenant_id)
    if entity is not None:
        names.append(entity.name)

    frontier = [entity_id]
    while frontier:
        current = frontier.pop()
        for alias in await graph.find_aliases(current, tenant_id):
            if any(alias.alias_entity_id == known for known in seen):
                continue
            seen.add(alias.alias_entity_id)
            frontier.append(alias.alias_entity_id)
            if alias.alias_name:
                names.append(alias.alias_name)

    return list(dict.fromkeys(names))
```

**Confirm `get_entity`'s real name and signature on the `EntityReader` port before writing this** — it may be `get_entities([id])`, in which case unpack the list and handle an absent id as `None`.

- [ ] **Step 4: Run to verify they pass, and prove the cycle test red** by removing the `seen` check — it must hang or fail, not pass.

- [ ] **Step 5: Gates and commit**

---

### Task 5: The usages port and its adapter

**Files:**
- Create: `research_team/application/usages.py`
- Create: `research_team/infrastructure/knowledge/usage_reader.py`
- Test: `tests/application/test_usages.py`, `tests/infrastructure/test_usage_reader.py`

**Interfaces:**
- Consumes: `known_names` (Task 4), chunk store (Tasks 1–3).
- Produces:

```python
@dataclass(frozen=True)
class Usage:
    source_id: str
    start: int
    end: int
    text: str
    score: float

class UsageReadPort(Protocol):
    async def usages(self, entity_id: UUID, *, limit: int = 20) -> list[Usage]: ...
```

No redstring type crosses this boundary — `tests/test_architecture.py` enforces it.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_passage_naming_the_entity_is_returned_with_its_offsets():
    usages = await reader.usages(acme_id)
    assert usages[0].source_id == "doc-1"
    assert doc_text[usages[0].start : usages[0].end] == usages[0].text


async def test_a_passage_matching_two_aliases_appears_once():
    """"Acme" and "Acme Corporation" both match the same sentence. A usages
    list that shows one passage twice reads as a bug to anyone looking at it.
    Fails with the dedup removed."""
    usages = await reader.usages(acme_id)
    keys = [(u.source_id, u.start, u.end) for u in usages]
    assert len(keys) == len(set(keys))


async def test_an_entity_with_no_mentions_returns_nothing_rather_than_raising():
    assert await reader.usages(unmentioned_id) == []


async def test_a_blank_name_never_reaches_the_ranker():
    """`rank_chunks`/`tokenize` treat a blank query as an error, and an entity
    whose only alias name is empty would otherwise raise a 500 out of a read
    endpoint. Fails if the blank filter is removed."""
    assert await reader.usages(blank_named_id) == []
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

```python
async def usages(self, entity_id, *, limit=20):
    """Passages naming this entity or any name it has been merged under.

    Lexical only, and `ChunkRetriever` is deliberately not used: its
    `__init__` requires an `EmbeddingProvider` and dimension-checks it against
    the store, so constructing one would mean carrying a fake provider in
    production wiring to satisfy a collaborator `RetrievalMode.LEXICAL` never
    calls. The four lines below are what that class's `_lexical` does, and
    every name in them is exported from the package root.

    One query per name rather than one query over a joined string: BM25 scores
    a document against the terms it was asked for, so joining "Acme" and
    "Acme Corporation" into one query would reward a passage for containing
    "Acme" twice instead of treating the two spellings as alternatives.
    """
    names = [name for name in await known_names(self._graph, entity_id, self._tenant) if name.strip()]
    best: dict[tuple[str, int, int], Usage] = {}

    for name in names:
        terms = tokenize(name)
        if not terms:
            continue
        candidates = await self._chunks.lexical_candidates(terms, self._tenant, limit)
        for ranked in rank_chunks(terms, candidates, limit):
            chunk = ranked.chunk
            key = (chunk.source_id, chunk.start_char, chunk.end_char)
            # Keep the better score when two names hit the same passage: the
            # canonical spelling usually wins, which is the ordering a reader
            # expects when the list is sorted below.
            if key not in best or ranked.score > best[key].score:
                best[key] = Usage(
                    source_id=chunk.source_id,
                    start=chunk.start_char,
                    end=chunk.end_char,
                    text=chunk.text,
                    score=ranked.score,
                )

    return sorted(best.values(), key=lambda u: u.score, reverse=True)[:limit]
```

**Note the score comparability caveat and write it into the docstring:** BM25 scores from two separate queries are not strictly comparable, because each is computed against the term statistics of its own query. Taking the max across names is a deliberate approximation — it is right about ordering far more often than it is wrong, and the alternative (a single fused ranking model) is a great deal of machinery for a list of twenty passages. Say so rather than implying the scores are commensurate.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Gates and commit**

---

### Task 6: The usages endpoint

**Files:**
- Modify: `research_team/interfaces/web/app.py` (near the graph routes, ~line 1274)
- Modify: `research_team/interfaces/web/presenters.py`
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: `UsageReadPort.usages` (Task 5).
- Produces: `GET /api/projects/{project_id}/graph/entities/{entity_id}/usages` → `{"usages": [{"source_id", "start", "end", "text", "score"}]}` via `usages_view`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_usages_returns_passages_with_offsets(client):
    response = await client.get(f"/api/projects/{project}/graph/entities/{entity}/usages")
    assert response.status_code == 200
    first = response.json()["usages"][0]
    assert first["source_id"] and first["end"] > first["start"]


async def test_usages_for_an_unknown_project_is_404(client):
    response = await client.get(f"/api/projects/{uuid4()}/graph/entities/{entity}/usages")
    assert response.status_code == 404


async def test_a_limit_above_the_cap_is_refused_rather_than_clamped(client):
    """A caller asking for 10_000 passages has misunderstood the endpoint, and
    silently handing back 100 teaches them it worked."""
    response = await client.get(
        f"/api/projects/{project}/graph/entities/{entity}/usages?limit=10000"
    )
    assert response.status_code == 422
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement**

Follow the conventions the graph routes already use: a closure on the FastAPI instance (there is no `APIRouter` in this codebase), `await _require_project(project_id)` as the first line, a per-project reader helper that raises 503 when unwired, a typed query parameter so FastAPI produces the 422, and a plain dict from a `*_view` function in `presenters.py`. Read `app.py:1248-1290` and copy that shape rather than inventing one. Define `MAX_USAGES` next to the existing `MAX_NEIGHBORHOOD_DEPTH`-style caps and comment what it is protecting.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Gates and commit**

---

### Task 7: The definition read model

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py`
- Test: `tests/infrastructure/test_read_models.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `EntityDefinitionRow`, `EntityDefinitionStore` with `get(project_id, entity_id) -> EntityDefinitionRow | None` and `put(row)`, table `entity_definitions`.

Model this on the `CorpusDocumentRow` / `CorpusStore` quartet (`read_models.py:591-1065`) — read it before writing. Row id is `uuid5(namespace, f"{project_id}:{entity_id}")`, matching `CorpusDocumentRow.row_id` at :649.

Fields: `project_id: UUID`, `entity_id: UUID`, `text: str`, `citations: str` (JSON array of `{source_id, start, end}`), `model: str`, `generated_at: str`, `stale: bool`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_definition_round_trips_with_its_citations():
    await store.put(row)
    got = await store.get(project_id, entity_id)
    assert got.text == row.text
    assert json.loads(got.citations)[0]["source_id"] == "doc-1"


async def test_a_database_written_before_definitions_existed_gains_the_table():
    """`CREATE TABLE IF NOT EXISTS` does nothing to a database that already
    exists, and every query against a missing table answers 500 while every
    test on a fresh database passes. This is the sibling of
    `test_a_database_written_before_a_field_existed_gains_its_column` and
    exists for the same shipped incident."""
    old = await open_database_without_definitions()
    await apply_schema(old)
    assert await store.get(project_id, entity_id) is None  # not a raise
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement** the row, store, and `apply_schema` registration. Add the project index the corpus store has (`idx_corpus_documents_project` at :821) — queries are always project-scoped.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Gates and commit**

---

### Task 8: Invalidation

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py`
- Test: `tests/infrastructure/test_read_models.py`

**Interfaces:**
- Consumes: `EntityDefinitionStore` (Task 7).
- Produces: `EntityDefinitionProjection` with `_on_extracted` and `_on_merged`; `EntityDefinitionRunner` with `rebuild()`.

`CorpusProjection._on_extracted` (`read_models.py:745`) is the working precedent for a local projection folding a redstring event — including that it keys on `event.tenant_id` and skips a missing row rather than raising.

- [ ] **Step 1: Write the failing tests**

```python
async def test_extraction_marks_the_touched_entities_stale():
    """Entities never gain properties incrementally -- a property change
    arrives as a whole-entity payload inside `DocumentExtracted` -- so this
    one subscription covers the entire 'more properties were added' case."""
    await projection.handle(document_extracted_naming(acme_id))
    assert (await store.get(project_id, acme_id)).stale is True


async def test_extraction_leaves_untouched_entities_alone():
    """Fails if the handler marks the whole project stale, which is the
    obvious wrong implementation and is invisible without this test."""
    await projection.handle(document_extracted_naming(other_id))
    assert (await store.get(project_id, acme_id)).stale is False


async def test_a_merge_marks_the_survivor_stale_and_deletes_the_absorbed():
    """An absorbed id is no longer clickable, so its cached definition is
    unreachable text -- and leaving it would make a `/rebuild` produce a
    different row count than steady-state operation, for no reason anyone
    could explain later."""
    await projection.handle(entities_merged(canonical=acme_id, merged=[acme_corp_id]))
    assert (await store.get(project_id, acme_id)).stale is True
    assert await store.get(project_id, acme_corp_id) is None


async def test_a_definition_for_an_entity_with_no_cached_row_is_not_an_error():
    """Matches `CorpusProjection._on_extracted`: a projection that raises on a
    row it has never seen cannot replay a log that predates it."""
    await projection.handle(document_extracted_naming(never_defined_id))
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement.** Mark, never regenerate — a bulk re-extraction touching two hundred entities would otherwise fire two hundred LLM calls for definitions nobody asked to read. Do **not** subscribe to `MergeUndone`; add a comment giving the spec's reasoning for why no case yields a wrong answer today.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Gates and commit**

---

### Task 9: Definition generation

**Files:**
- Create: `research_team/application/entity_definitions.py`
- Test: `tests/application/test_entity_definitions.py`

**Interfaces:**
- Consumes: `UsageReadPort.usages` (Task 5), the graph read port, `EntityDefinitionStore` (Task 7).
- Produces:

```python
@dataclass(frozen=True)
class Citation:
    source_id: str
    start: int
    end: int

@dataclass(frozen=True)
class Definition:
    text: str
    citations: list[Citation]
    model: str
    generated_at: str
    stale: bool

class DefinitionService:
    async def define(self, entity_id: UUID, *, force: bool = False) -> Definition: ...
```

- [ ] **Step 1: Write the failing tests**

Use a fake model that returns canned text — no live call in the suite.

```python
async def test_a_fresh_cached_definition_is_returned_without_calling_the_model():
    """The cache is the entire point; a hit that still pays for a call is the
    defect this test exists to catch. Fails if the staleness check is dropped."""
    await service.define(acme_id)
    calls = fake_model.calls
    await service.define(acme_id)
    assert fake_model.calls == calls


async def test_a_stale_definition_is_regenerated_on_the_next_call():
    await mark_stale(acme_id)
    await service.define(acme_id)
    assert fake_model.calls == 2


async def test_the_prompt_carries_the_passages_and_the_edges():
    await service.define(acme_id)
    prompt = fake_model.last_prompt
    assert "Acme supplies" in prompt   # a passage
    assert "supplies" in prompt         # an edge type


async def test_an_entity_with_no_passages_and_no_edges_is_not_sent_to_the_model():
    """There is nothing to ground a definition in, and a model asked to define
    a bare name will answer from what it already knows -- which is precisely
    the ungrounded gloss this feature exists to avoid. Fails if the guard is
    removed."""
    result = await service.define(bare_id)
    assert result is None or result.text == ""
    assert fake_model.calls == 0
```

- [ ] **Step 2: Run to verify they fail**

- [ ] **Step 3: Implement.** Gather name, type and edges from the graph read port plus top usages; build a prompt requiring every claim to be attributable to a supplied passage or a supplied edge; call the extraction model via the existing `config.model_name()` wiring; store the result with its citations. Decide and document what happens when the model returns text citing nothing — the spec's position is that an ungrounded definition is the failure mode this feature exists to prevent, so prefer refusing it over storing it, and say in a comment what a reader sees when that happens.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: Gates and commit**

---

### Task 10: The definition endpoint

**Files:**
- Modify: `research_team/interfaces/web/app.py`, `presenters.py`
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: `DefinitionService.define` (Task 9).
- Produces: `GET /api/projects/{project_id}/graph/entities/{entity_id}/definition` → `{"text", "citations": [...], "model", "generated_at", "stale"}`.

Generates synchronously — no queue. Extraction needs one because it is long and losing a queued one loses an intention (B62); a definition is seconds, idempotent, and re-triggered by the next click.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_definition_is_returned_with_its_citations(client):
    body = (await client.get(url)).json()
    assert body["text"]
    assert body["citations"][0]["source_id"]


async def test_a_stale_definition_is_still_served_and_says_so(client):
    """Blanking the panel on every re-extraction would make it flicker for
    changes that may not affect the definition at all; the old text is still
    the best answer available."""
    await mark_stale(entity)
    body = (await client.get(url)).json()
    assert body["text"] and body["stale"] is True
```

- [ ] **Step 2–5:** as Task 6 — same conventions, gates, commit.

---

### Task 11: Usages in the graph panel

**Files:**
- Modify: `frontend/src/presentation/research/GraphDetail.tsx`
- Modify: `frontend/src/application/queries/keys.ts`
- Create: `frontend/src/infrastructure/http/usages-repository.ts`
- Test: `frontend/src/presentation/research/GraphDetail.test.tsx`

**Interfaces:**
- Consumes: the usages endpoint (Task 6).
- Produces: a `usages(project, entityId)` query key; a `Usage` view type mirroring the DTO.

`keys.ts` has no graph keys today because the graph is a zustand store. Read its module docstring first — it states the rule this must follow: keys are never spelled out at call sites, because a misspelled invalidation silently does nothing.

- [ ] **Step 1: Write the failing tests** (jsdom — roles, text, and empty states, all of which jsdom judges correctly)

```tsx
it('lists a passage with the document it came from', async () => {
  render(<GraphDetail ... />)
  expect(await screen.findByText(/Acme supplies/)).toBeInTheDocument()
})

it('says nothing was found rather than showing an empty box', async () => {
  expect(await screen.findByText(/no mentions/i)).toBeInTheDocument()
})

it('keeps showing the edge list while usages are still loading', async () => {
  expect(screen.getByRole('heading', { name: /relationships/i })).toBeInTheDocument()
})
```

- [ ] **Step 2: Run to verify they fail** — `cd frontend && npx vitest run src/presentation/research/GraphDetail.test.tsx`. One vitest process at a time.

- [ ] **Step 3: Implement.** A section above the existing edge list. Each passage links to the existing source route with its offsets — `/api/projects/{id}/sources/{source_id}?start=&end=` already serves exactly that, which is the payoff of the citation decision.

- [ ] **Step 4: Run to verify they pass**

- [ ] **Step 5: `npm run verify`, then commit.** If you touched a stylesheet or a layout primitive, also run `npm run test:browser` — jsdom lays nothing out, so a computed style asserted there is not asserted at all.

---

### Task 12: The definition in the panel

**Files:**
- Modify: `frontend/src/presentation/research/GraphDetail.tsx`, `keys.ts`
- Test: `frontend/src/presentation/research/GraphDetail.test.tsx`

- [ ] **Step 1: Write the failing tests**

```tsx
it('shows the definition above the passages', async () => {
  expect(await screen.findByText(/Acme Corporation is a supplier/)).toBeInTheDocument()
})

it('keeps the old text visible while a stale definition regenerates', async () => {
  render(<GraphDetail ... definition={{ text: 'old text', stale: true }} />)
  expect(screen.getByText('old text')).toBeInTheDocument()
  expect(screen.getByText(/updating/i)).toBeInTheDocument()
})

it('does not block the passages on the definition still loading', async () => {
  expect(await screen.findByText(/Acme supplies/)).toBeInTheDocument()
})
```

- [ ] **Step 2–5:** as Task 11.

---

### Task 13: Documentation and deferred work

**Files:**
- Modify: `BACKLOG.md`, `README.md`, `CLAUDE.md`

- [ ] **Step 1: File the deferred items in `BACKLOG.md`** with enough detail to pick up: the semantic channel and that enabling it needs an embedding backfill rather than a flag flip; `MergeUndone` being unsubscribed and the condition under which that stops being safe; chunk-level provenance being recoverable by storing `ChunkId` alongside offsets; the postgres chunk-store branch if Task 1 left it unwired.

- [ ] **Step 2: Add to `CLAUDE.md`** the replay finding, which outlives this feature: an event no projection handles counts as *applied*, not rejected, so a missing projection is a silently empty read model rather than a refusal — and a test asserting "the project opened" will pass with the projection removed.

- [ ] **Step 3: Update `README.md`** with `AGENT_CHUNK_STORE` and what the default costs.

- [ ] **Step 4: All four gates, then commit.**

---

## Self-review notes

**Spec coverage.** Decision 1 → Tasks 1, 3, 5. Decision 2 → Tasks 5, 6, 9, 11. Chunk index → 1, 2, 3. Replay coupling → 2. Alias resolution → 4. Usages port → 5, 6. Definition service and cache → 7, 8, 9, 10. HTTP and panel → 6, 10, 11, 12. Testing obligations → global constraints plus Task 7's pre-existing-database test. Deferred list → 13.

**Two things a task must confirm rather than assume**, both flagged inline because guessing them is how this plan would waste a subagent's cycle: the postgres `ChunkStore` adapter's constructor name and whether it is async (Task 1), and the `EntityReader` method for fetching one entity (Task 4).

**One approximation stated rather than hidden:** BM25 scores from per-name queries are not strictly comparable, and Task 5 takes the max across names anyway. The docstring says so.

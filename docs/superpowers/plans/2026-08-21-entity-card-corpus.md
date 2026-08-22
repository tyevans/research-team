# Entity Card Corpus (Stage B) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an entity be retrieved by *describing* it -- naming its neighbours, its type, its properties -- rather than only by spelling its name.

**Architecture:** A synthetic document per entity ("a card"), assembled from graph state and indexed into its **own** chunk store, queried with BM25. Cards are derived at project open from the already-folded graph, not event-sourced: a card holds no information the graph does not, so persisting it through the log would buy nothing and cost staleness. A separate store from the quotable corpus is what makes it structurally impossible for a card to be cited as a passage.

**Tech Stack:** Python 3.13, `uv`, pytest, `redstring` (pinned to a 0.10.0 commit by PR #229), `eventsource-py`.

**Spec:** `docs/superpowers/specs/2026-08-21-retrieval-retake-design.md`, Part III.

## Global Constraints

- **Four gates:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The ruff pair runs over the whole repository. No frontend work is expected here.
- **Do not run the full `pytest` suite locally.** It takes ~10 minutes here against ~2 in CI. Run the files you touched, push, and let CI be the gate. This is a standing preference, not a shortcut.
- **`application/` and `domain/` may not import `redstring`** -- enforced by `tests/test_architecture.py`. Card assembly reads redstring entities, so the assembler lives in `infrastructure/knowledge/`.
- **redstring may only be named through its public surface.** `redstring.domain.*` is refused by `test_redstring_is_named_only_through_its_public_surface`.
- **Prove every new test red before trusting it green**, and never undo the deliberate break with `git checkout <file>` -- it discards the rest of the file's uncommitted work. Copy the file aside, or commit first.
- **An event no projection handles counts as APPLIED**, so a missing wiring yields an empty read model rather than a refusal. Every assertion here must be on *data* -- a row exists, a name is in it -- never that a call returned without raising.
- Work in the worktree `~/workspace/rt-stage-b`. Do not switch branches in `~/workspace/research-team`.

---

### Task 1: Assemble a card from graph state

Pure function first, wiring later: this is the piece whose output is judged by eye and by BM25, and it is worth being able to test without a store.

**Files:**
- Create: `research_team/infrastructure/knowledge/entity_cards.py`
- Test: `tests/infrastructure/test_entity_cards.py`

**Interfaces:**
- Consumes: `redstring.Entity` (fields `id`, `name`, `entity_type`, `description`, `properties`), `redstring.Relationship` (`source_entity_id`, `target_entity_id`, `relationship_type`).
- Produces:
  ```python
  @dataclass(frozen=True)
  class Neighbour:
      relationship_type: str
      name: str
      outgoing: bool

  def card_text(
      *,
      name: str,
      entity_type: str,
      aliases: Sequence[str],
      properties: Mapping[str, object],
      neighbours: Sequence[Neighbour],
  ) -> str: ...
  ```

- [ ] **Step 1: Write the failing test**

```python
def test_a_card_names_its_neighbours_and_their_relationship():
    """The relations block is the whole point of a card.

    stark-bench measured adding neighbour names to an indexed document at
    +22% lexical and +44% hybrid, and the mechanism it found is why the
    edge *type* is here too: queries name related entities verbatim, and BM25
    matches those names directly where a single dense vector compresses them
    away. `acquired` and `competitor_of` are what make two neighbours
    distinguishable at the same token cost.
    """
    text = card_text(
        name="Acme Corporation",
        entity_type="Organization",
        aliases=["Acme", "Acme Corp."],
        properties={"founded": "1987"},
        neighbours=[
            Neighbour(relationship_type="acquired", name="Blackwell Systems", outgoing=True),
            Neighbour(relationship_type="subsidiary_of", name="Vantage Holdings", outgoing=True),
        ],
    )

    assert "Acme Corporation" in text
    assert "Organization" in text
    assert "Acme Corp." in text
    assert "founded" in text and "1987" in text
    assert "acquired" in text and "Blackwell Systems" in text
    assert "subsidiary_of" in text and "Vantage Holdings" in text


def test_a_card_for_an_entity_with_no_neighbours_is_still_a_card():
    """The input that separates a correct assembler from a plausible one.

    A well-connected entity is what anyone would write down, and every
    candidate implementation handles it. An isolated entity is where a
    template that unconditionally emits a `- relations:` header leaves a
    dangling heading, and where a join over an empty sequence can raise.
    """
    text = card_text(
        name="Lone Entity",
        entity_type="Concept",
        aliases=[],
        properties={},
        neighbours=[],
    )

    assert "Lone Entity" in text
    assert "relations" not in text.lower()
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/infrastructure/test_entity_cards.py -v
```

Expected: FAIL, `ImportError` / `ModuleNotFoundError`.

- [ ] **Step 3: Implement `card_text`**

Emit, in order: `name  (entity_type)`; an `also known as:` line when aliases are non-empty; one `key: value` line per property; then, **only when neighbours is non-empty**, a `- relations:` block with one `  {relationship_type}  {name}` line each. Every section is omitted when its input is empty.

Write the module docstring to say what the card is *for* -- that it is indexed and BM25'd, that the neighbour names are the payload, and that it is never quoted to a reader (Task 3's isolation is what enforces that).

- [ ] **Step 4: Run to verify pass**

```
uv run pytest tests/infrastructure/test_entity_cards.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/knowledge/entity_cards.py tests/infrastructure/test_entity_cards.py
git commit -m "Assemble an entity card from graph state"
```

---

### Task 2: Build the card index for one project

**Files:**
- Modify: `research_team/infrastructure/knowledge/entity_cards.py`
- Test: `tests/infrastructure/test_entity_cards.py`

**Interfaces:**
- Consumes: `card_text` and `Neighbour` from Task 1; a redstring `GraphStore` (`find_entities`, `get_relationships_for`, `resolve_entity_ids`, `get_entities`), a `ChunkStore` (`replace_source`), and `known_names` from `research_team.infrastructure.knowledge.aliases`.
- Produces:
  ```python
  async def index_cards(
      *, graph: "GraphStore", cards: "ChunkStore", tenant_id: UUID, chunker: "Chunker"
  ) -> int: ...
  ```
  Returns the number of entities carded. Source ids are **derived** from the entity id -- `uuid5(_CARD_NAMESPACE, str(entity.id))` -- never chosen.

- [ ] **Step 1: Write the failing test**

```python
@pytest.mark.asyncio
async def test_a_carded_entity_is_found_by_a_neighbour_name(graph_with_two_linked_entities):
    """A query naming a neighbour and none of the entity's own words finds it.

    This is the capability Stage B exists for and it is unanswerable before
    this task: `search` matches names, and 'Blackwell Systems' is not one of
    'Acme Corporation'.
    """
    graph, tenant = graph_with_two_linked_entities  # Acme --acquired--> Blackwell
    cards = InMemoryChunkStore(dimension=8)

    carded = await index_cards(
        graph=graph, cards=cards, tenant_id=tenant, chunker=SlidingWindowChunker()
    )
    assert carded == 2, "both entities get a card, not just the one with an edge"

    terms = tokenize("Blackwell Systems")
    candidates = await cards.lexical_candidates(terms, tenant, 10)
    ranked = list(rank_chunks(terms, candidates, 10))

    assert ranked, "the corpus must hold something matching a neighbour name"
    assert any("Acme Corporation" in r.chunk.text for r in ranked), (
        "Acme's card must name Blackwell, which is the whole mechanism"
    )
```

- [ ] **Step 2: Run to verify failure**

Expected: FAIL on the missing `index_cards`.

- [ ] **Step 3: Implement `index_cards`**

Read every entity for the tenant; drop absorbed ones with `resolve_entity_ids` the way `RedstringKnowledge.search` does (a merge is not a delete, and a card for an absorbed entity would compete with its canonical). For each survivor: fetch its relationships in **one batched call over all ids**, not one call per entity; resolve the far endpoint's name; build `Neighbour`s; call `card_text`; chunk it; `replace_source(card_source_id(entity.id), tenant_id, chunks)`.

- [ ] **Step 4: Run to verify pass, then prove the batching**

Add a counting wrapper test in the shape of `test_search_reads_relationships_once_regardless_of_match_count` (in `tests/infrastructure/test_redstring_adapter.py`) -- one `get_relationships_for` call regardless of entity count. Prove it red by moving the call inside the loop.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "Index a card per entity, derived from the graph"
```

---

### Task 3: Give each project a card store, isolated from the corpus

**Files:**
- Modify: `research_team/application/project_graphs.py` (`open`, `chunks`, `close`)
- Modify: `research_team/composition.py` (pass a `build_card_store`)
- Test: `tests/application/test_project_graphs.py`, `tests/infrastructure/test_usage_reader.py`

**Interfaces:**
- Produces: `ProjectGraphs.cards(project_id) -> Any | None`, mirroring `chunks`.

- [ ] **Step 1: Write the failing isolation test**

```python
@pytest.mark.asyncio
async def test_a_card_never_appears_in_the_quotable_corpus(...):
    """Cards and passages live in different stores, so a citation cannot name one.

    `application/entity_definitions.py` enforces that every citation is
    `(source_id, start, end)` into a real document -- a card is synthesised
    text, so a citation into one would name a passage no source contains while
    looking exactly as checked as a real one.

    Passes trivially given two stores, which is the argument *for* two stores.
    It is written down so that a later collapse into one fails here rather than
    in a reader's citation.
    """
```

Assert that a `UsageReader` over a project whose cards mention a distinctive token returns nothing for that token.

- [ ] **Step 2: Run to verify it fails** (there is no card store yet, so the fixture cannot build one).

- [ ] **Step 3: Wire the store**

In `ProjectGraphs.open`, after `_rebuild` returns, build the card store and call `index_cards`. Cache in `self._card_stores[project_id]`; evict and close it in `close` beside the chunk store. **No projection subscribes to it** -- `eventsource`'s `ProjectionOptions` has only a `tenant_filter`, so two `ChunkProjection`s over one event store would each apply every `DocumentChunked` and both stores would hold everything. That is the crossing this design avoids by not event-sourcing cards at all; say so in the code.

- [ ] **Step 4: Run both test files, then prove the isolation test red**

Point `cards()` at the same store `chunks()` returns and watch it fail.

- [ ] **Step 5: Commit**

---

### Task 4: Refresh cards when the graph changes

A card is a snapshot of a neighbourhood. Every ingest and every consolidation moves one.

**Files:**
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py` (`ingest`, and the consolidation path)
- Test: `tests/infrastructure/test_entity_cards.py`

**Interfaces:**
- Consumes: `index_cards` from Task 2.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_merge_leaves_one_card_naming_both_neighbourhoods():
    """After consolidation the absorbed entity's card is gone and the
    canonical one names the union of both neighbourhoods.

    The input that distinguishes a correct refresh from a plausible one: a
    refresh that only re-cards *touched* entities leaves the absorbed card
    behind, and it still matches every query its name used to -- so the merge
    looks undone from the retrieval side while the graph is correct.
    """


async def test_a_new_edge_reaches_the_other_end_s_card():
    """Ingesting a document that links A to B must refresh **B's** card too,
    not only A's. The edge changes both neighbourhoods and only one of them
    is the document's subject."""
```

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement the refresh.** Start with a whole-tenant re-card after ingest and consolidation, and say in the commit that it is O(entities) per ingest and the obvious thing to narrow. Correctness first; the narrowing needs the edge-endpoint reasoning above and is easy to get subtly wrong.

- [ ] **Step 4: Run, then prove red** by narrowing the refresh to only the ingested document's own entities and watching the second test fail.

- [ ] **Step 5: Commit.**

---

### Task 5: Expose card retrieval

**Files:**
- Modify: `research_team/application/knowledge.py`, `research_team/infrastructure/knowledge/redstring_adapter.py`, `research_team/infrastructure/agent/knowledge_tools.py`
- Test: `tests/infrastructure/test_redstring_adapter.py`, `tests/infrastructure/test_knowledge_tools.py`

**Interfaces:**
- Produces: `KnowledgePort.describe(query, *, limit) -> SearchOutcome` -- a **separate method** from `search`, not a mode on it.

- [ ] **Step 1: Write the failing test** -- `describe("a company that acquired Blackwell Systems")` returns Acme, where `search` on the same string returns nothing.

- [ ] **Step 2: Run to verify failure.**

- [ ] **Step 3: Implement**, and give the agent a `graph_describe` tool beside `graph_search`. Two tools rather than one fused answer, because a model choosing between "I know the name" and "I know about it" is the choice stark-bench I.2 says matters: mixing unrelated candidates into a name lookup scored *below* returning none.

- [ ] **Step 4: Run both test files.**

- [ ] **Step 5: Commit.**

---

## Self-Review

**Spec coverage.** Part III's card contents -> Task 1. Derived-not-event-sourced -> Task 3. Source ids derived from entity id -> Task 2. Structural isolation from `UsageReader` -> Task 3. Freshness across ingest and consolidation -> Task 4. Part III's "does not rerank" is honoured: no task adds one.

**Placeholder scan.** Task 4 Step 3 deliberately specifies the *unoptimised* implementation and names the narrowing as follow-up rather than leaving it open.

**Type consistency.** `Neighbour` and `card_text` are defined in Task 1 and used under those names in Task 2. `index_cards` is defined in Task 2 and used in Tasks 3 and 4. `SearchOutcome` already exists (merged in #226) and is reused rather than redefined.

**Known gap for the executor to close rather than guess.** Task 2 needs the far endpoint's name for each relationship; confirm whether `get_entities` or a second `find_entities` pass is the cheaper read against the in-memory store before writing it, and say which in the docstring.

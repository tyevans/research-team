# Retrieval Retake (research-team) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give entity lookup a real ranking model with a fuzzy channel it does not have today, and move the quotable corpus off the chunker that loses on retrieval across three embedding models.

**Architecture:** Two independent pull requests. PR 1 adds `redstring.Retriever`'s two channels *beside* the existing substring pass in `RedstringKnowledge.search`, fuses the three, and makes a degraded embedding endpoint visible in the result rather than only in a log. PR 2 swaps `BoundaryPreferenceChunker` for `SlidingWindowChunker` in `RedstringKnowledge.index` and pins the one upstream defect that ride-along introduces. Neither touches the other's files; `Retriever` reads entities and vectors and never chunks.

**Tech Stack:** Python 3.13, `uv`, pytest, `redstring 0.9.2`, `eventsource-py`.

**Spec:** `docs/superpowers/specs/2026-08-21-retrieval-retake-design.md`

## Global Constraints

- **Four verification gates, and passing three is not passing.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository. No frontend file changes in this plan, so the frontend gate is expected to be untouched -- but run it if you touch anything under `frontend/`.
- **`application/` and `domain/` may not import `redstring`.** Enforced by `tests/test_architecture.py`; the only framework those layers may name is `eventsource`. Everything redstring-shaped lives in `infrastructure/`.
- **redstring may only be named through its public surface.** `from redstring import X` is fine; `redstring.domain.anything` is refused by `test_redstring_is_named_only_through_its_public_surface`.
- **Do not run two `vitest` processes at once**, and re-run a failing test alone before investigating it. Not expected to matter here (no frontend work), listed because it is a repository-wide rule.
- **Prove every new test red before trusting it green.** Break the implementation on purpose and watch the suite fail. A test that would pass with the change reverted must say so in its docstring.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, and say when something was measured rather than reasoned.
- Work in the worktree `~/workspace/rt-retrieval-retake` on branch `retrieval-retake`. Do not switch branches in `~/workspace/research-team`.

---

## PR 1 -- `Retriever` beside the substring scan

### Task 1: Pin what entity search can do today

The regression this whole PR risks is silent, and the existing suite cannot see it: `test_search_finds_an_ingested_entity_by_substring` uses a full entity name, which every candidate implementation matches. These tests are the ones that would go red if a later task dropped the substring channel.

**Files:**
- Modify: `tests/infrastructure/test_redstring_adapter.py` (add beside the existing search tests near line 437)

**Interfaces:**
- Consumes: the existing `build_adapter` fixture in that file, and `RedstringKnowledge.search(query, *, limit) -> list[Match]`.
- Produces: nothing later tasks import. This task's output is coverage.

- [ ] **Step 1: Write three tests for cases that pass today**

```python
async def test_search_finds_an_entity_by_an_interior_fragment(tmp_path, build_adapter):
    """`corp` finds `Acme Corporation`.

    Passes today against the substring scan. It is here because it does *not*
    pass against `redstring.Retriever`'s lexical channel, which blocks on a
    five-character name prefix and a soundex of the whole name -- neither of
    which an interior fragment shares. Measured 2026-08-21; see the spec's
    Part II table. If this goes red, the substring channel was dropped.
    """
    adapter = await build_adapter(tmp_path)
    await _ingest_named(adapter, "Acme Corporation")
    matches = await adapter.search("corp", limit=10)
    assert [match.name for match in matches] == ["Acme Corporation"]


async def test_search_finds_an_entity_by_a_short_prefix(tmp_path, build_adapter):
    """`Acme` finds `Acme Corporation`.

    Fails against `Retriever` alone: the query's prefix key is `p:acme` and
    the entity's is `p:acme ` -- five characters including the space -- and
    the soundexes differ (`A250` against `A252`). Measured 2026-08-21.
    """
    adapter = await build_adapter(tmp_path)
    await _ingest_named(adapter, "Acme Corporation")
    matches = await adapter.search("Acme", limit=10)
    assert [match.name for match in matches] == ["Acme Corporation"]


async def test_search_finds_an_entity_by_a_reordered_name(tmp_path, build_adapter):
    """`Corporation Acme` finds `Acme Corporation`.

    An earlier draft of the spec claimed reordered names as a gain from
    `Retriever`. They are a loss -- the reordering changes the prefix key and
    the soundex both. This is the substring channel's case, not the fused
    one's.
    """
    adapter = await build_adapter(tmp_path)
    await _ingest_named(adapter, "Acme Corporation")
    matches = await adapter.search("Corporation Acme", limit=10)
    assert [match.name for match in matches] == ["Acme Corporation"]
```

Read `test_search_finds_an_ingested_entity_by_substring` (around line 437) first and copy however it seeds an entity. If it seeds inline rather than through a helper, write `_ingest_named(adapter, name)` as a module-level helper in that file doing exactly what that test does, and leave the existing test calling its own code -- do not refactor the existing test in this task.

- [ ] **Step 2: Run them and confirm they pass**

```
uv run pytest tests/infrastructure/test_redstring_adapter.py -k "interior_fragment or short_prefix or reordered_name" -v
```

Expected: 3 passed. They are characterising current behaviour, so green is correct here. If any fails, stop -- the substring scan does not do what this plan assumes and the rest of PR 1 needs rethinking.

- [ ] **Step 3: Prove they can go red**

Temporarily edit `RedstringKnowledge.search` in `research_team/infrastructure/knowledge/redstring_adapter.py` to change `if needle not in entity.name.lower():` to `if needle != entity.name.lower():`, then re-run the command from Step 2.

Expected: 3 failed. **Revert the edit immediately** (`git checkout research_team/infrastructure/knowledge/redstring_adapter.py`) and re-run to confirm 3 passed again.

- [ ] **Step 4: Commit**

```bash
git add tests/infrastructure/test_redstring_adapter.py
git commit -m "Pin the three search cases a fused retriever would silently lose

Interior fragment, short prefix and reordered name all pass against the
substring scan and all fail against redstring.Retriever's lexical channel,
which blocks on a five-character prefix plus a soundex. The existing search
test uses a full name, which both implementations match, so nothing in the
suite could have caught the loss. Proved red by tightening the substring
test to equality."
```

---

### Task 2: Add the fused channels beside the scan

**Files:**
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py` (`RedstringKnowledge.search`, around line 938)
- Test: `tests/infrastructure/test_redstring_adapter.py`

**Interfaces:**
- Consumes: `self._store` (`GraphStore`), `self._embeddings` (`EmbeddingProvider | None`), `self._vectors` (`VectorStore | None`), and `self._embedding_pair() -> tuple[EmbeddingProvider | None, VectorStore | None]`, all existing fields/methods on `RedstringKnowledge`.
- Produces: `RedstringKnowledge.search(query, *, limit) -> list[Match]` -- unchanged signature and return type. Task 3 changes the return type; this task deliberately does not, so the two are separately reviewable.

- [ ] **Step 1: Write the failing test for the new capability**

```python
async def test_search_finds_an_entity_despite_a_misspelling(tmp_path, build_adapter):
    """`Akme Corporation` finds `Acme Corporation`.

    This is the whole capability PR 1 adds. A substring scan cannot reach it
    at any threshold -- the strings share no substring longer than
    ` Corporation` -- so it fails with this task reverted, which is the point.
    It works through `Retriever`'s soundex blocking key: `Akme` and `Acme`
    both soundex to `A250`.
    """
    adapter = await build_adapter(tmp_path)
    await _ingest_named(adapter, "Acme Corporation")
    matches = await adapter.search("Akme Corporation", limit=10)
    assert [match.name for match in matches] == ["Acme Corporation"]
```

- [ ] **Step 2: Run it to verify it fails**

```
uv run pytest tests/infrastructure/test_redstring_adapter.py::test_search_finds_an_entity_despite_a_misspelling -v
```

Expected: FAIL -- `assert [] == ['Acme Corporation']`.

- [ ] **Step 3: Implement the fused search**

In `research_team/infrastructure/knowledge/redstring_adapter.py`, add to the imports at the top (the `from redstring import (...)` block):

```python
    Retriever,
    RetrievalMode,
```

Replace the body of `search` (keeping its `limit < 1` and blank-query guards exactly as they are) with:

```python
    async def search(self, query: str, *, limit: int = 10) -> list[Match]:
        """Entities matching `query`, best first.

        Three channels, unioned: a substring test over the tenant's names, and
        `Retriever`'s lexical (blocking keys plus Jaro-Winkler) and semantic
        (name embeddings) channels.

        **The substring channel is not redundant and is not legacy.**
        Measured 2026-08-21 against a three-entity store: `Retriever` matches
        a misspelling the substring scan cannot reach, and misses an interior
        fragment (`corp`), a short prefix (`Acme`) and a reordered name, all
        of which the scan finds. Neither dominates, so both run. Tasks 1 and 2
        of this PR carry one test per case in that table.

        Order is `Retriever`'s fused ranking first -- it is the only channel
        with a real score -- then substring-only hits in name order. A hit
        found by both appears once, at its `Retriever` rank.

        `Retriever` is skipped entirely when `_embedding_pair` has latched
        `(None, None)`; see `search_mode` for how a caller learns that
        happened rather than silently receiving substring hits only.
        """
```

Then, inside the existing `async with tenant_scope(self._project_id):` block, keep the substring loop exactly as it is but collect into an ordered dict keyed by `entity.id`, and before it add:

```python
                embeddings, vectors = await self._embedding_pair()
                ranked: list[UUID] = []
                if embeddings is not None and vectors is not None:
                    retriever = Retriever(
                        embeddings=embeddings, vectors=vectors, graph=self._store
                    )
                    result = await retriever.retrieve(
                        query, self._project_id, k=limit, mode=RetrievalMode.HYBRID
                    )
                    ranked = [scored.entity.id for scored in result.matches]
```

Merge so that `ranked` ids come first (skipping any whose canonical id differs from itself, using the same `canonical` filter the substring loop already applies), then substring-only ids, then truncate to `limit`.

Replace the per-match `get_relationships_for([entity.id], ...)` with **one** call over the final id list:

```python
                edges = await self._store.get_relationships_for(final_ids, self._project_id)
                counts: dict[UUID, int] = {entity_id: 0 for entity_id in final_ids}
                for edge in edges:
                    for endpoint in (edge.source_entity_id, edge.target_entity_id):
                        if endpoint in counts:
                            counts[endpoint] += 1
```

Confirm the attribute names on the relationship object before writing that loop -- read `redstring.Relationship`'s fields rather than trusting the two names above, and fix them if they differ.

- [ ] **Step 4: Run the new test and the pinned three**

```
uv run pytest tests/infrastructure/test_redstring_adapter.py -k "search" -v
```

Expected: all pass, including the three from Task 1. If a Task 1 test fails, the merge dropped the substring channel -- fix the merge, do not weaken the test.

- [ ] **Step 5: Prove the batched count is actually batched**

```python
async def test_search_reads_relationships_once_regardless_of_match_count(tmp_path, build_adapter):
    """One `get_relationships_for` call, not one per match.

    Fails with this task reverted, where the call sat inside the match loop.
    Counted through a wrapper rather than asserted on timing, because a
    per-match call is correct-looking and only differs in cost.
    """
    adapter = await build_adapter(tmp_path)
    for name in ("Acme Corporation", "Acme Holdings", "Acme Labs"):
        await _ingest_named(adapter, name)

    calls = 0
    original = adapter._store.get_relationships_for

    async def counting(*args, **kwargs):
        nonlocal calls
        calls += 1
        return await original(*args, **kwargs)

    adapter._store.get_relationships_for = counting
    matches = await adapter.search("Acme", limit=10)
    assert len(matches) == 3
    assert calls == 1
```

Run it, confirm PASS, then confirm it fails if you move the count back inside the loop.

- [ ] **Step 6: Run the Python gates**

```
uv run ruff check . && uv run ruff format --check . && uv run pytest tests/infrastructure/test_redstring_adapter.py -v
```

Expected: clean, all pass.

- [ ] **Step 7: Commit**

```bash
git add research_team/infrastructure/knowledge/redstring_adapter.py tests/infrastructure/test_redstring_adapter.py
git commit -m "Search fuses Retriever's two channels with the substring scan

Adds redstring.Retriever beside the substring pass rather than instead of it.
Measured 2026-08-21: Retriever matches a misspelling the scan cannot reach
and misses an interior fragment, a short prefix and a reordered name, which
the scan finds. Neither dominates, so both run and the union is ranked by
Retriever's fusion with substring-only hits after.

The semantic channel costs nothing new: build_graph already embeds every
extracted entity for consolidation scoring, and Retriever reads those same
vectors.

Also collapses the per-match get_relationships_for into one batched call.
That was a straight defect -- N round trips to answer one question -- and it
is pinned by a counting wrapper rather than left to review."
```

---

### Task 3: Make a degraded retrieval mode visible in the result

**Files:**
- Modify: `research_team/application/knowledge.py` (`Match` is at line 246; add beside it)
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py` (`search`)
- Modify: `research_team/infrastructure/agent/knowledge_tools.py:180` (the `graph_search` tool) and its `format_matches`
- Test: `tests/infrastructure/test_redstring_adapter.py`, `tests/infrastructure/test_knowledge_tools.py`

**Interfaces:**
- Consumes: `Match` from `research_team.application.knowledge`.
- Produces:
  ```python
  class SearchMode(StrEnum):
      FUSED = "fused"      # substring + Retriever's lexical and semantic channels
      SUBSTRING = "substring"  # Retriever unavailable; substring channel only

  @dataclass(frozen=True)
  class SearchOutcome:
      matches: tuple[Match, ...]
      mode: SearchMode
  ```
  `KnowledgePort.search` returns `SearchOutcome`, not `list[Match]`. This is a breaking change to the port and is intended.

- [ ] **Step 1: Write the failing test**

```python
async def test_search_reports_substring_mode_when_embeddings_are_unavailable(
    tmp_path, build_adapter
):
    """A dead embedding endpoint degrades search and says so.

    `_embedding_pair` latches `(None, None)` on a failed probe, which is the
    right trade for consolidation -- losing an optional scoring feature beats
    discarding an extracted document -- and the wrong one for retrieval, where
    it silently removes two of three channels.

    This asserts the degradation is legible from the *result*. It fails with
    this task reverted, where the only trace was a log line at warning.
    """
    adapter = await build_adapter(tmp_path)
    await _ingest_named(adapter, "Acme Corporation")

    async def unavailable():
        return (None, None)

    adapter._embedding_pair = unavailable

    outcome = await adapter.search("Acme", limit=10)
    assert outcome.mode is SearchMode.SUBSTRING
    assert [match.name for match in outcome.matches] == ["Acme Corporation"]


async def test_search_reports_fused_mode_when_embeddings_work(tmp_path, build_adapter):
    """The healthy case names itself, so the degraded one is not the only signal.

    Without this, `mode` could be hardcoded to SUBSTRING and the test above
    would still pass.
    """
    adapter = await build_adapter(tmp_path)
    await _ingest_named(adapter, "Acme Corporation")
    outcome = await adapter.search("Acme", limit=10)
    assert outcome.mode is SearchMode.FUSED
```

- [ ] **Step 2: Run to verify failure**

```
uv run pytest tests/infrastructure/test_redstring_adapter.py -k "reports_substring_mode or reports_fused_mode" -v
```

Expected: FAIL with `AttributeError: 'list' object has no attribute 'mode'`.

- [ ] **Step 3: Add the types to the application layer**

In `research_team/application/knowledge.py`, beside `Match` (line 246):

```python
class SearchMode(StrEnum):
    """Which channels actually ran for one search.

    A plain enum in this layer's own vocabulary rather than redstring's
    `RetrievalMode`: `application/` may not import redstring
    (`tests/test_architecture.py`), and the two do not mean the same thing
    anyway -- this counts the substring channel, which redstring has no
    concept of.
    """

    FUSED = "fused"
    SUBSTRING = "substring"


@dataclass(frozen=True)
class SearchOutcome:
    """What a search returned, and which channels produced it.

    `mode` exists because the degradation it reports is otherwise invisible:
    `_embedding_pair` latches `(None, None)` on a bad endpoint and search
    quietly becomes a substring scan, with plausible-looking results and a
    warning in a log nobody reads. That is the shape of every real bug the
    stark-bench campaign found, and the cheapest defence is a field a test
    can assert on.

    Deliberately not an exception. A dead embedding endpoint should degrade
    entity lookup, not break it -- the same trade `_embedding_pair` makes for
    consolidation, and the right one.
    """

    matches: tuple[Match, ...]
    mode: SearchMode
```

Add `from enum import StrEnum` to that module's imports if it is not already there. Update `KnowledgePort.search`'s signature and docstring to return `SearchOutcome`.

- [ ] **Step 4: Return it from the adapter**

Wrap the adapter's return in `SearchOutcome(matches=tuple(matches), mode=mode)`, where `mode` is `SearchMode.FUSED` when the `Retriever` branch ran and `SearchMode.SUBSTRING` when `_embedding_pair` returned `(None, None)`.

- [ ] **Step 5: Update the agent tool**

In `research_team/infrastructure/agent/knowledge_tools.py`, `graph_search` currently does:

```python
            matches = await knowledge.search(query, limit=limit)
        except KnowledgeError as error:
            return f"Could not search the graph: {error}"
        return format_matches(matches)
```

Change to:

```python
            outcome = await knowledge.search(query, limit=limit)
        except KnowledgeError as error:
            return f"Could not search the graph: {error}"
        return format_matches(outcome)
```

and change `format_matches` to take the `SearchOutcome`, appending one line when `outcome.mode is SearchMode.SUBSTRING`:

```
(Name matching only -- the embedding endpoint is unavailable, so
misspellings will not be found.)
```

The agent is told, because an agent that searches `Akme` and gets nothing should be able to tell "no such entity" from "that channel is off".

- [ ] **Step 6: Run everything that touches search**

```
uv run pytest tests/infrastructure/test_redstring_adapter.py tests/infrastructure/test_knowledge_tools.py tests/test_architecture.py -v
```

Expected: all pass. `test_architecture.py` is in the list because Step 3 added a type to `application/` -- if you reached for `RetrievalMode` there, it fails, which is the rule doing its job.

- [ ] **Step 7: Find every other caller**

```
grep -rn "\.search(" research_team/ tests/ --include=*.py | grep -v "_FENCE\|re\.search"
```

Update each to the new return type. Then run the full Python suite:

```
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Expected: all green. The full suite is warranted here because the port signature changed.

- [ ] **Step 8: Commit**

```bash
git add -A
git commit -m "search reports which channels ran, so a dead endpoint is visible

KnowledgePort.search returns SearchOutcome (matches plus mode) rather than a
bare list. Breaking, and intended.

_embedding_pair latches (None, None) when the embedding probe fails, which is
correct for consolidation -- losing a third scoring feature beats discarding
an extracted document -- and wrong for retrieval, where it silently removes
two of three channels and leaves plausible substring hits behind. stark-bench
spent three explanations on exactly this shape before anyone read the field
that had been in every report from the beginning.

Not an exception: degrading is still the right behaviour. What changes is
that a test can assert on it and the agent is told, so 'no such entity' and
'that channel is off' stop looking identical."
```

---

## PR 2 -- the chunker switch

Start this from a clean branch off `main` if PR 1 is still in review; the two touch different files and are deliberately independent.

### Task 4: Pin the redundant tail chunk, red

**Files:**
- Create: `tests/infrastructure/test_chunking_defects.py`

**Interfaces:**
- Consumes: `RedstringKnowledge.index(source)` and the `build_adapter` fixture pattern from `tests/infrastructure/test_redstring_adapter.py`.
- Produces: nothing. This is a standing record of an upstream defect.

- [ ] **Step 1: Write the test, expecting it to fail**

```python
"""Defects in redstring's chunking that this repository indexes around.

Each test here fails today and names the upstream change that turns it green.
They are not xfail: an xfail that starts passing is a footnote, and these
should be a failing suite that makes someone look.
"""


async def test_no_indexed_chunk_is_wholly_contained_in_another(tmp_path, build_adapter):
    """A document longer than the window yields one redundant tail chunk.

    `SlidingWindowChunker` emits a final window `(len - overlap, len)` even
    when the previous chunk already reached `len`, so the last chunk is wholly
    contained in the one before it.

    **Measured 2026-08-21 against redstring 0.9.2**, at 1000/500 across
    lengths from 450 to 4,500 characters: exactly one redundant chunk, always
    the last, for every document longer than the window. Documents at or under
    the window size are unaffected.

    Two consequences here. `UsageReader` deduplicates on
    `(source_id, start_char, end_char)` and the two spans differ, so a reader
    is shown two overlapping passages, one a suffix of the other. And BM25
    counts the tail's terms twice, giving tail passages a second draw that
    mid-document passages do not get.

    **Expected to fail until redstring's `SlidingWindowChunker` stops
    emitting that chunk** -- the fix is to break out of the loop once a chunk
    reaches the end of the text. Filed as `B-SLIDING-REDUNDANT-1` in
    stark-bench; not in redstring's own backlog as of 2026-08-21.
    """
    adapter = await build_adapter(tmp_path)
    text = "The quick brown fox jumps over the lazy dog. " * 60  # 2,700 chars
    source_id = "tail-chunk-probe"
    await adapter.record(SourceRef(source_id=source_id, text=text))

    chunks = await adapter._chunks.get_by_source(source_id, adapter._project_id)
    spans = sorted((chunk.start_char, chunk.end_char) for chunk in chunks)
    contained = [
        (inner, outer)
        for inner in spans
        for outer in spans
        if inner != outer
        and outer[0] <= inner[0]
        and inner[1] <= outer[1]
    ]
    assert contained == [], f"chunks wholly inside another: {contained}"
```

Check `RedstringKnowledge`'s actual public method for storing-and-indexing a document before writing `adapter.record(...)` -- `_store_document` calls `index` directly, so there is a public entry point; use it rather than calling `index` privately. Check `ChunkReader.get_by_source`'s real signature too.

- [ ] **Step 2: Run it and confirm it fails**

```
uv run pytest tests/infrastructure/test_chunking_defects.py -v
```

Expected: **FAIL**, listing one contained span pair. If it passes, the corpus is still on `BoundaryPreferenceChunker` (Task 5 has not run) -- that is fine and expected at this point in the plan only if you have reordered the tasks. Do not "fix" it by changing the assertion.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/infrastructure/test_chunking_defects.py
git commit -m "Pin redstring's redundant tail chunk as a failing test

Measured across 450-4500 characters at 1000/500: exactly one redundant chunk,
always the last, for every document longer than the window. The final chunk
is (len-overlap, len) while the penultimate already reaches len.

Deliberately a failing test rather than xfail. An xfail that starts passing
is a footnote; a red test is something someone has to look at, and the whole
point is that the day upstream lands is visible rather than inferred."
```

Note: this leaves the suite red. That is the intent of "switch now, fix upstream in parallel", and the docstring is what makes the redness legible. If CI must be green to merge, mark it `xfail(strict=True)` instead and say in the commit that strictness is what preserves the signal.

---

### Task 5: Switch the corpus chunker

**Files:**
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py` (`RedstringKnowledge.index`, around line 709)
- Test: `tests/infrastructure/test_redstring_adapter.py`

**Interfaces:**
- Consumes: `MarkdownTableChunker` from `research_team.infrastructure.knowledge.markdown_table_chunker`, `SlidingWindowChunker` from `redstring`.
- Produces: no signature change.

- [ ] **Step 1: Write the failing test**

```python
async def test_the_quotable_corpus_is_chunked_small_enough_to_rank(tmp_path, build_adapter):
    """A long document yields several chunks, not one or two.

    BM25 discounts a term matched inside a long document and does not discount
    it inside a short one, and `aggregation: max` lets a source take its best
    chunk -- so chunk size is a retrieval parameter, not a storage detail.
    stark-bench measured whole-document against sliding-1000-500 on the same
    corpus and model: +0.071 dense, +0.072 lexical, +0.070 hybrid, with the
    gain 1.7x larger on the longest third of documents.

    Fails with the switch reverted: `BoundaryPreferenceChunker` at its
    defaults produces 3,000-character chunks, so a 2,700-character document is
    one chunk.
    """
    adapter = await build_adapter(tmp_path)
    text = "The quick brown fox jumps over the lazy dog. " * 60  # 2,700 chars
    source_id = "chunk-size-probe"
    await adapter.record(SourceRef(source_id=source_id, text=text))

    chunks = await adapter._chunks.get_by_source(source_id, adapter._project_id)
    assert len(chunks) >= 4
    assert max(len(chunk.text) for chunk in chunks) <= 1_100
```

- [ ] **Step 2: Run to verify it fails**

```
uv run pytest tests/infrastructure/test_redstring_adapter.py::test_the_quotable_corpus_is_chunked_small_enough_to_rank -v
```

Expected: FAIL -- one chunk of 2,700 characters.

- [ ] **Step 3: Make the switch**

In `redstring_adapter.py`, add `SlidingWindowChunker` to the `from redstring import (...)` block if absent, and change the `index` call:

```python
            chunker=MarkdownTableChunker(
                SlidingWindowChunker(default_chunk_size=1000, default_overlap=500)
            ),
```

Then rewrite the paragraph of `index`'s docstring that currently justifies `BoundaryPreferenceChunker`:

```
        `SlidingWindowChunker` at 1000/500, not `BoundaryPreferenceChunker`.
        Upstream documents the latter for passages that will be quoted back to
        a reader, which is what this corpus is for -- and it loses on
        retrieval, consistently. stark-bench found it **last on dense
        retrieval across three embedding models**, with sliding-1000-500
        ahead of it on every channel in both corpora where both ran.

        The quotability argument is weaker than it looks:
        `SlidingWindowChunker` defaults to `respect_sentence_boundaries=True`
        and `respect_paragraph_boundaries=True`, and they work -- the first
        chunk of a 2,700-character document at size 1000 ends at 990, not
        1000. Both chunkers snap to sentences; they differ in size and
        overlap, which is exactly what BM25's length normalisation cares
        about.

        **The cost, measured 2026-08-21:** a document longer than the window
        gets one redundant tail chunk, wholly inside the previous one, which
        `UsageReader`'s offset dedup cannot collapse. See
        `tests/infrastructure/test_chunking_defects.py`, which fails until
        redstring fixes it.
```

- [ ] **Step 4: Run the new test and the defect test**

```
uv run pytest tests/infrastructure/test_redstring_adapter.py::test_the_quotable_corpus_is_chunked_small_enough_to_rank tests/infrastructure/test_chunking_defects.py -v
```

Expected: the chunk-size test PASSES; the defect test now FAILS (it was passing before the switch, because `BoundaryPreferenceChunker` does not produce a contained chunk). That inversion is the honest record of what this PR costs.

- [ ] **Step 5: Run the whole Python suite**

```
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

Expected: green apart from `test_chunking_defects.py`. Any *other* failure is a real regression from re-chunking -- most likely a test asserting a specific chunk count or a specific quoted passage. Fix those tests to the new chunking rather than reverting; re-chunking is expected and `chunking_signature` handles the re-index automatically.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "Chunk the quotable corpus with sliding windows, not boundary preference

stark-bench found BoundaryPreferenceChunker last on dense retrieval across
three embedding models, with sliding-1000-500 ahead on every channel in both
corpora where both ran. Three models agreeing points at the chunker rather
than at an interaction with one embedding model.

The quotability argument that chose it does not survive measurement:
SlidingWindowChunker defaults to respecting sentence and paragraph boundaries
and does -- the first chunk of a 2700-character document ends at 990. Both
snap to sentences. They differ in size, which is what BM25's length
normalisation cares about.

What this costs, measured rather than assumed: one redundant tail chunk per
document longer than the window, which UsageReader's offset dedup cannot
collapse, so a reader sees one duplicate passage. test_chunking_defects.py
inverts from green to red on this commit and that is the honest record.

Existing corpora re-index on the next index call -- chunking_signature is
chunker_type plus a digest of the settings and both halves change."
```

---

## Self-Review

**Spec coverage.** Part II (Stage A) -> Tasks 1-3. Part IV (chunker switch, one pinned defect) -> Tasks 4-5. Part V's test list: entity lookup gains a case -> Task 2 Step 1; loses no case -> Task 1; degraded mode visible -> Task 3. Part III (Stage B, cards) is **deliberately unplanned** -- the spec says it waits until PRs 1 and 2 land so it is not measured against a baseline that moved. Part VI (Stage C) is sketched, not designed, and has no tasks by intent.

**Known gaps an executor must close rather than guess.** Three places above say "check the real signature first": `Relationship`'s endpoint field names (Task 2 Step 3), `RedstringKnowledge`'s public store-and-index entry point and `ChunkReader.get_by_source`'s signature (Task 4 Step 1). These are named rather than invented because a plausible wrong name is worse than an instruction to look.

**Type consistency.** `SearchOutcome` and `SearchMode` are defined in Task 3 Step 3 and used in Task 3 Steps 1, 4 and 5 under those exact names. `Match` is unchanged throughout. Tasks 1 and 2 use `list[Match]`, which is correct for their point in the sequence -- Task 3 is the one that changes it, and says so in its Interfaces block.

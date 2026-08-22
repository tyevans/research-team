# Making the co-mention channel real

Specification for the repair `docs/design/co-mention-channel-findings.md`
motivates. That document is the brief and is not repeated here; every
measurement cited below is from it unless this file says otherwise.

Everything asserted here about the tree was read on 2026-08-22 in
`/home/ty/workspace/wt-durable-vectors` on branch `durable-vectors`. Where a
claim could not be checked, it says so rather than guessing.

## 0. Five facts the design rests on, each checked

These were not obvious from the findings document and two of them change what
is possible.

**F1. `build_graph` is called with neither `chunks=` nor `event_store=`.**
`redstring_adapter.py:494-511` passes `document, provider, store, tenant_id,
domain, embedding_provider, vector_store, concurrency, chunker` and nothing
else. The findings document records the missing `chunks=`; the missing
`event_store=` is the more consequential half.

**F2. Without `event_store=`, extraction's chunking is unreachable to us.**
`build_graph` still calls `aggregate.record_chunking(...)` unconditionally
(`composition/build_graph.py`, after `pipeline.record`), but `_persist` is a
no-op when no repository was built, and `GraphBuildReport` exposes only
`chunks_written` — **not the `DocumentChunked` event**. So the per-chunk
entity links are computed on every ingest today and discarded inside the
library. There is no way for this repository to append that event itself
without either passing `event_store=` or an upstream change. This is the
pivot of section A.

**F3. The two chunkings do not suppress each other, but the later one wins the
store.** `index_documents` composes the signature
`f"{chunker_type}:{digest}"` (`composition/index_documents.py:188`);
the pipeline composes `f"{chunker_type}:{digest}:{model_version}"`
(`extraction/pipeline.py:523`). `Document.record_chunking` keys on that string,
so both are recorded. But `ChunkProjection` applies each with
`replace_source`, which is last-write-wins per `(tenant, source_id)`. Ingest
order is `_store_document` → `index` → `build_graph`, and log order matches, so
**extraction's chunking would win both live and on replay.**

**F4. Chunk `entity_ids` are pre-consolidation ids.** They are read off
`map_extraction`'s return inside the pipeline loop
(`extraction/pipeline.py:487`), before `merge_extractions` and long before
`Consolidator.resolve`. Nothing ever rewrites them. The graph read returns
canonical entities only (`graph_reader.py:269`, `_without_aliases`), so
`ChunkCoMentions`' `& wanted` silently drops every link to an absorbed entity.
On the findings document's own corpus that is 633 extracted against 545
canonical — **at least 14% of links dropped before any pair is formed**, and
more than that in truth, because a merge removes the pair as well as the id.
Nothing in the tree resolves them.

**F5. `ChunkStore.get_by_entity` has exactly one caller in this repository:
`ChunkCoMentions`.** `UsageReader` finds passages by BM25 over names, not by
entity id. So the entity-link half of the chunk corpus is used by one
untested class and nothing else — which is why nobody noticed it was empty.

## A. How entity↔passage linkage gets recorded

### The three candidates, against the code

**(a) Extraction owns the corpus** — pass `chunks=graphs.chunks(project)` and
`event_store=` to `build_graph`. Smallest diff. Costs, in order of size:

1. **The retrieval corpus changes granularity from 1000/500 to 2000/200.**
   `index` chunks at `SlidingWindowChunker(1000, 500)`; the extraction chunker
   is `SlidingWindowChunker(default_chunk_size=config.extraction_chunk_size())`
   with redstring's default overlap, which is **200** (read from
   `chunkers/sliding_window_chunker.py`'s `__init__` docstring). By F3 the
   extraction chunking replaces it. `index`'s own docstring records
   stark-bench measuring `sliding-1000-500` ahead of the alternative on every
   channel in both corpora across three embedding models; that measurement is
   about a chunker rather than about a size, so it does not directly predict
   the loss — but nothing measures 2000/200, and the change is a silent
   regression in every quote, citation and `usages` result.
2. Every quoted passage doubles in length. `entity_definitions`' citation
   contract still holds (real `source_id`, real offsets), so this is a quality
   change, not a correctness one.
3. Documents stored but never extracted (the `link_source` path,
   `_store_document` with a later extraction failure) keep `index`'s chunking,
   so the corpus holds two granularities depending on a document's history.
   Not wrong; not explicable to a reader either.

**(b) A second chunk store**, on the `_card_stores` precedent. The comment
there argues against a source-id convention and *for* a second store, and the
argument transfers. Its stated blocker does not: that comment says two
`ChunkProjection`s over one event store would both apply every
`DocumentChunked` because `ProjectionOptions` offers only a `tenant_filter`.
That is true of `eventsource`'s options, and irrelevant here, because
`rebuild_graph` constructs its projection list by hand and `EmbeddingsForModel`
is already a projection in this repository that filters `EntitiesEmbedded` by
`source_id` and model. The same shape filters `DocumentChunked`.

**(c) Different source ids** — extraction writes under `f"{source_id}#x"`.
Rejected on the `_card_stores` comment's own ground: `entity_definitions.py`
promises every citation is `(source_id, start, end)` into a *real* document,
and this puts passages in the corpus whose `source_id` names nothing. It also
doubles every BM25 result, since both copies of the text are indexed and
`UsageReader` would rank them against each other.

### Decision

**Take (b): a second, per-project chunk store holding the extraction
chunking, fed live by `build_graph` and on replay by a filtering projection.**

Concretely:

1. `RedstringKnowledge.__init__` gains `co_mentions: ChunkStore | None = None`,
   alongside `chunks` and `cards`, defaulting to `None` (off) exactly as those
   do.
2. `ingest` passes `event_store=self._event_store` and
   `chunks=self._co_mentions` to `build_graph`.
3. `ProjectGraphs` gains `_co_mention_stores`, built by the same
   `build_chunk_store` factory as `_chunk_stores` and `_card_stores`, exposed
   as `co_mentions(project_id)`, closed in `close`/`close_all`.
4. `rebuild_graph` gains a `co_mentions: ChunkStore | None = None` parameter
   and appends a new projection for it.
5. `composition.py` passes `graphs.co_mentions(target_project_id)` into the
   adapter, beside the existing `chunks=` and `cards=`.
6. `interfaces/web/app.py::_co_mentions` reads
   `graphs.co_mentions(project_id)` rather than `graphs.chunks(project_id)`,
   keeping the `graphs.open` first ordering and its 503.

**The two filtering projections, and how they discriminate.** Once
`event_store=` is passed, extraction's `DocumentChunked` is on the log, and by
F3 the *existing* `ChunkProjection` in `rebuild_graph` would apply it and
replace the retrieval corpus with the 2000/200 chunking on every project open
and every `/rebuild`. That is candidate (a)'s cost arriving through the back
door, silently, on the replay path only. So both projections must filter:

- The retrieval corpus applies a `DocumentChunked` **only when no chunk in it
  carries entity links**.
- The co-mention store applies one **only when at least one chunk does**.

Discriminate on the presence of links, **not on the signature string.**
Parsing `f"{type}:{digest}:{model}"` looks like the intended discriminator and
is unsafe here: `MarkdownTableChunker.chunker_type` is
`"markdown_table(sliding_window)"` (no colon today, but a delegate name is not
ours to constrain) and a model id may contain a colon — the Ollama `name:tag`
convention is the obvious case, and `provider.model` is what lands in the
signature. Counting colons would then route an extraction event to the
retrieval corpus, which is exactly the failure the filter exists to prevent.

The link test is also *more* correct than the signature test in the case that
matters: `index_documents` omits `entity_ids_by_index` entirely
(`extraction/corpus.py:67`, and its docstring says so), so its chunks are
always unlinked, and a re-`index` after an extraction must not wipe the
co-mention store for that source. The link test gives that for free. The
degenerate case — an extraction that found no entities anywhere in a document
— produces an all-unlinked event that is routed to the retrieval corpus; it
carries the extraction chunking, so it would replace the retrieval corpus for
that one document. **This is a real hole in the rule and it is accepted**: a
document from which nothing was extracted has no co-mentions either way, the
damage is one document's chunk sizes, and the alternative is the fragile
string parse. Say so in the projection's docstring; do not leave it for
someone to find.

### What (b) costs

- **The corpus text is held twice in memory.** Default is `AGENT_CHUNK_STORE=
  memory`, so a project's passages now occupy roughly 2× (3× counting cards,
  which already duplicate). Nothing measures the current figure; an
  implementer should record the process RSS before and after on the findings
  document's five-article corpus and put the number in the commit message.
- A leaner store holding only `(source_id, chunk_index, entity_ids)` would
  avoid that and would remove the "a citation into a synthetic passage" risk
  entirely. It is rejected as the first version because `build_graph`'s
  `chunks=` is typed `ChunkStore | None` and `ChunkProjection` calls
  `replace_source`; satisfying that with a partial object is possible (there
  is no mypy gate — the four CI gates are ruff check, ruff format, pytest and
  `npm run verify`) but it trades a checked port for an unchecked duck. Note
  it in `BACKLOG.md` rather than doing it now.
- Three chunk stores per project is one more thing to close, and
  `ProjectGraphs.close` is the only place that can leak them.

### The `event_store=` ripples, which are the expensive part

Passing `event_store=` is required by F2 and is not free. Each of these must
be handled in the same change:

1. **`ingest` must stop appending `built.event` itself.**
   `redstring_adapter.py:541-545` appends to
   `document_stream(tenant_id, source_id)` with `ExpectedVersion.any_()`.
   `build_graph`'s `_persist` appends to the same stream via
   `document_repository(event_store)`. Leaving both is a duplicated
   `DocumentExtracted`, which `GraphProjection` would apply twice — idempotent
   on upserts, and not on anything that counts.
2. **`built.event is None` becomes reachable.** Today `build_graph` builds a
   fresh aggregate per call, so `record_extraction` never refuses. With a log
   it refuses a second extraction of one document under the same
   `model_version`. `ingest` already has that branch and returns a zero
   report, so no new code — but the *behaviour* changes: re-ingesting an
   unchanged document under an unchanged model stops re-extracting and stops
   costing model calls. That is an improvement and it is also a trap; see
   section E.
3. **Two `EntitiesEmbedded` for the document channel.** `ingest` already
   passes `embedding_provider` and `vector_store` to `build_graph`, so with a
   log `_embed_entities` will now append the event the aggregate builds — and
   `_record_embeddings`' `recover_document_embeddings` appends a second one,
   directly to the store, bypassing the aggregate's refusal. Duplicate vectors
   are idempotent at `upsert_many`, so nothing breaks; the log gains a
   redundant event per ingest and `recover_document_embeddings` becomes dead
   weight. **The implementer should delete the document-channel half of
   `_record_embeddings` and let `build_graph` own it**, keeping only the card
   channel, and must re-run `tests/infrastructure/test_durable_vectors.py`
   with that removed rather than assuming its assertions still hold — several
   of them assert on the log and will now be satisfied by a different writer.
   *This is the single largest risk in the change and it is not fully
   analysed here: I read `_embed_entities`' call site but not its body.*
4. **Concurrency.** `ExpectedVersion.any_()` becomes the repository's own
   expected-version save. Two ingests of one `source_id` in flight together
   would now conflict where they previously did not. No call site in the tree
   does that; `ExtractionQueue` serialises. Not addressed further.

## B. Whether the co-mention constants survive

**They cannot be known until the channel runs, and the honest answer is to
change neither in this change.** Tuning them now would tune against arithmetic
rather than against a corpus, which is what produced the present values.

What can be said from the code, and is worth writing into the commit message
because it predicts the outcome:

- Extraction chunks at 2000 characters — roughly 300 words. The findings
  document measured 132 entities from one document at that size. A passage
  therefore names something like 5–15 of them, giving 10–105 pairs, so each
  pair receives `0.5 / pairs` ≈ **0.005 to 0.05**.
- Against `RELATION_WEIGHT = 1.0` and a semantic edge worth up to
  `EMBEDDING_WEIGHT = 0.6`, a single co-mention is 20× to 200× weaker than an
  assertion. Overlap is only 200/2000, so a pair is rarely counted more than
  twice.
- **So the likely outcome of this repair is that the channel comes alive and
  still changes almost nothing** — and that looks identical, from the outside,
  to the defect being unfixed. An implementer who lands this and sees the area
  counts barely move must not read that as failure to wire it.

`MAX_PASSAGE_ENTITIES = 25` is a *relevance* guard against contents pages, and
its value is a function of chunk size, which nothing records. At 2000
characters a genuine index page will still exceed 25; at 1000 it might not.

**The measurement that settles both.** With the channel live, on the findings
document's five-article corpus, report:

1. The distribution of `len(members)` per counted passage (min, p50, p90, p99,
   max). Set `MAX_PASSAGE_ENTITIES` at p99 rather than at a round number, and
   record the distribution beside the constant.
2. **The decisive statistic: total co-mention weight summed over the
   adjacency, against total relation weight.** If co-mentions are under ~5% of
   the graph's mass, the channel is decorative whatever the area counts look
   like, and `CO_MENTION_BUDGET` should rise until it is not.
3. Areas / placed / dropped at `CO_MENTION_BUDGET` ∈ {0.5, 2.0, 8.0} and
   `MAX_PASSAGE_ENTITIES` ∈ {25, ∞}, on the graph-only baseline (31 / 437 /
   108) with the semantic channel **off**, so the arms isolate one signal.

Purity was 1.000 in every arm of the findings document's grid and so cannot
rank these either. A discriminating metric is needed and none exists yet; the
cheapest candidate is the **cross-article edge rate** — the fraction of
adjacency weight joining entities whose source documents differ — because the
five-article corpus has a known two-subject split and a channel that raises
placement by gluing Rome to plant biology is not an improvement. Whoever takes
the measurement should build that metric first; without it the grid is
uninterpretable in the same way the findings document's already was.

## C. Whether the semantic-edge design should change now

**Yes, eventually: move to CSLS with a budget. Not in this change.**

The findings measured CSLS ahead of raw cosine at every matched budget (250:
483 placed / 62 dropped against 473 / 72; 500: 519 / 26 against 489 / 56;
1000: 534 / 11 against 508 / 37), with hubness collapsing from max in-degree
38 and 26 orphans under cosine to 15 and 0 under CSLS. And the shipped
absolute floor admits 0.60% of pairs corpus-wide against 5.07% and 6.56%
inside the two subsets — a 10× density swing from one constant inside one
corpus, which is the definition of a constant that will not survive contact
with a different corpus.

Three reasons to sequence it after the co-mention repair rather than with it:

1. **Both changes move the same numbers.** Landing them together makes the
   grid unattributable, which is the same mistake as the original tuning.
2. **The co-mention channel may reduce how much the semantic channel is
   needed.** How the implementer checks this rather than assuming it: after
   the repair, re-run the findings document's grid with a fourth baseline row
   — *graph + co-mentions, no semantic* — and compare it to `+ CSLS @500`. If
   the co-mention row's placed/dropped approaches the CSLS row's, the right
   move is to **shrink the semantic budget**, not to improve its selection
   rule; the two channels are then substituting for each other and the
   cheaper, log-derived one should lead. If the co-mention row sits near the
   graph-alone baseline (31 / 437 / 108), the semantic channel is carrying the
   feature and CSLS is worth the work.
3. Purity cannot rank the arms, so the cross-article metric from section B has
   to exist before any of this is decidable.

**What moving to CSLS actually costs, which the findings do not say.**
Replacing the floor with a budget deletes `MIN_EMBEDDING_SCORE`, and
`_semantic_edges`' weight map is *defined against it*: it rescales
`[MIN_EMBEDDING_SCORE, 1.0]` onto `[0, EMBEDDING_WEIGHT]`, and
`test_a_pair_at_the_floor_contributes_almost_nothing` pins that. With a budget
there is no floor to map from, and the three obvious replacements are not
equivalent — rescale over the admitted set's own min and max (corpus-relative,
so the weakest admitted edge always weighs zero even when it is excellent),
map rank-within-budget onto the range (ignores how good the match is), or map
the CSLS score itself (unbounded above and below, needs its own clamp). Pick
one and say why; this is real design work and an implementer will otherwise
discover it mid-change.

`EMBEDDING_NEIGHBOURS` should be **removed rather than retuned** under a
budget. The findings measured it nearly inert (k = 3/5/8 giving 476/475/475
placed) precisely because the floor binds instead; a global budget makes k not
the knob at all, and leaving a constant that no longer decides anything is how
the next person tunes the wrong thing.

## D. The tests

The root cause is that `ChunkCoMentions` has no test and the projection's
tests drive stubs, so the port and its only adapter were each verified alone.
Every test below names the plausible implementation it must fail against; a
test that only fails against an obviously broken one does not count.

### D1. `tests/infrastructure/test_co_mentions.py` — new file

The missing integration test. Use the `build_adapter` fixture
(`tests/infrastructure/conftest.py`), which drives a real `SQLiteEventStore`,
a real `InMemoryGraphStore` and a fake LLM provider through the real `ingest`.
Note that the fixture passes no `chunks=` today, so every test here must pass
real stores through `**knowledge_kwargs`.

1. **`test_an_ingest_leaves_entity_links_in_the_co_mention_store`** — ingest a
   document whose fake extraction returns ≥2 entities, then assert
   `get_by_entity(<one entity>, project)` returns a chunk whose `entity_ids`
   holds ≥2 ids. *Fails against:* today's build (`chunks=` never passed), and
   against a build that passes `chunks=` but not `event_store=` **only if the
   assertion is taken after a rebuild** — see D2. Assert on the ids, never on
   "the store is non-empty": `index` fills the retrieval store with unlinked
   chunks and a non-emptiness assertion passes on the current build.
2. **`test_the_retrieval_corpus_keeps_its_own_chunking`** — after an ingest,
   assert the retrieval store's chunks for that source are the 1000/500 split
   and not the extraction split. Pin it on a measurable: chunk *count*, or the
   `chunking_method` in `metadata`. *Fails against:* the plausible-and-tempting
   implementation — candidate (a), passing `chunks=graphs.chunks(...)` — which
   is what an implementer reaching for the smallest diff will write.
3. **`test_a_reindex_after_extraction_does_not_empty_the_co_mention_store`** —
   ingest, then call `index` again on the same source, then assert the links
   are still there. *Fails against:* an unfiltered second `ChunkProjection`,
   and against any implementation that routes on the signature's colon count
   without also routing on links.
4. **`test_a_co_mention_survives_consolidation`** — ingest two documents that
   name one entity under two spellings so consolidation merges them, then
   assert `ChunkCoMentions.passages(<canonical ids from the graph read>)`
   returns a passage naming the *survivor*. *Fails against:* the obvious
   implementation, which is the shipped one — F4's raw `& wanted`, where the
   absorbed id is simply dropped. This is the test that forces alias
   resolution into `ChunkCoMentions`, and it is the one most likely to be
   skipped, because on a corpus with no merges the shipped code looks correct.

### D2. `test_co_mentions_survive_a_rebuild`

In `tests/infrastructure/test_knowledge_rebuild.py`, or the new file. Ingest,
then fold a **fresh** co-mention store from the log with `rebuild_graph` and
assert the links are present in it. *Fails against:* passing `chunks=` without
`event_store=` — which works perfectly live and loses everything on reopen,
and is the single most likely wrong implementation of this spec, because every
live assertion passes.

Per CLAUDE.md's read-model rule: at least one of these must start from a store
the arrange phase has *not* filled through the code path under test. D2 is
that test by construction, since it folds a store the ingest never touched.

### D3. `tests/application/test_area_projection.py` — one addition

`test_the_projection_changes_when_passages_are_added` — the same graph with
and without a non-trivial passage set must not produce byte-identical
projections. *Fails against:* the whole class of defect this spec exists for,
which is what the findings measured (31 / 437 / 108 both ways). The existing
tests drive `_co_mention_edges` directly and cannot see it.

### D4. `ChunkCoMentions` unit tests

Against a real `InMemoryChunkStore` seeded with `StoredChunk`s, not a stub.

- **`test_a_passage_naming_one_known_entity_is_not_a_co_mention`** — *fails
  against:* dropping the `len(named) >= 2` guard, which produces empty
  frozensets that `_co_mention_edges` then silently skips, so nothing else
  catches it.
- **`test_one_passage_reached_through_six_entities_is_counted_once`** — *fails
  against:* keying the dedup on the chunk's content-addressed `id` instead of
  `(source_id, chunk_index)` — plausible, and wrong for a document that
  repeats a passage verbatim.
- **`test_entities_outside_the_graph_read_are_dropped_from_the_pair_count`** —
  *fails against:* intersecting downstream in `_co_mention_edges` rather than
  in the adapter, which inflates the divisor and weakens every real pair. The
  docstring already claims this; nothing tests it.

### D5. What must NOT be written

An assertion that `passages()` returned without raising, or that the chunk
store is non-empty, or that a curriculum request answered 200. All three pass
against the current, dead build. CLAUDE.md's Events section makes the general
form of this point about missing projections; it applies verbatim here.

## E. Migration and breaking changes

There is no data to preserve. Pre-release; blowing away projects is fine.

What breaks, plainly:

1. **Every existing project's co-mention channel stays empty.** Its log holds
   no extraction `DocumentChunked` — the event was never persisted (F2) — so
   folding a co-mention store from it produces nothing. No amount of
   `/rebuild` fixes this.
2. **Re-ingesting in place will not fix it either, and this is the trap.** By
   ripple 2 of section A, once `event_store=` is passed, `record_extraction`
   refuses a second extraction of a document already extracted under the same
   `model_version` — and old logs *do* carry those `DocumentExtracted` events,
   appended by the adapter. So `remember_page` on an existing document returns
   a zero report and writes nothing.
3. **Therefore: the repair is to delete the project and ingest again.** Say
   this in the release note in exactly those words. Changing the model id also
   works and is not worth documenting as a workaround.
4. `tests/infrastructure/test_durable_vectors.py` will need revisiting rather
   than merely re-running, because the writer of the document-channel
   `EntitiesEmbedded` changes (ripple 3).
5. No frontend change. `DerivedFromLine` already renders "*N* shared passages"
   and has been printing 0; it will start printing a number.

## F. What else should connect to this and does not

Licence taken, per the brief. Two are findings; the rest are shapes to check.

**F-i. `ChunkStore.get_by_entity` has one caller and no other consumer** (F5).
The entity-link half of redstring's chunk corpus is, in this repository, a
feature with exactly one untested user. Anything else that wants "which
passages named this entity" — `GraphDetail`'s passage list, `usages`,
`entity_definitions`' evidence — goes through BM25 over names instead, which
is a *different answer*: it finds passages that spell the name, not passages
extraction attributed to the entity. Once the links are real, those surfaces
have a better source available and are not using it. Worth a BACKLOG entry;
out of scope here.

**F-ii. Nothing in the tree resolves chunk `entity_ids` through the alias
graph** (F4). This spec fixes it inside `ChunkCoMentions`, which is the
narrowest possible place. That is deliberate — a wider fix would rewrite
stored chunks on merge, which is a projection this repository does not have —
but it means the *next* consumer of `get_by_entity` will hit the same defect,
in the same silent way. If F-i is ever taken up, the resolution belongs in a
shared reader rather than copied.

**F-iii. Ports with one adapter and no integration test — the same shape as
this defect.** I did not audit for these systematically and am not asserting
they are broken; they are where I would look next, in order:

- `CoMentionPort` / `ChunkCoMentions` — the known case.
- `SemanticPort` / `VectorNeighbours` — the same construction (built in one
  web route, driven by literal tuples in `test_area_projection.py`). Its
  measurements in the findings document prove it *runs*, so it is not dead;
  whether anything tests the adapter against the port is unchecked.
- `TimelineReadPort` / `ProjectTimelineReader` — the temporal channel measured
  at 0.3% in CLAUDE.md's Extraction section is a nearby instance of "the
  feature succeeds and produces nothing".

A cheap and general guard, worth more than any of the above individually:
**a test that asserts, for each of the projection's two optional channels,
that the shipped adapter over a realistically-seeded store returns something
non-empty.** The co-mention channel was dead for the life of the feature and
was found by accident.

# Retrieval: adopting redstring's classes, and indexing the graph as text

Design, 2026-08-21. Prompted by the `stark-bench` campaign of 2026-08-19/21,
whose findings are the evidence for most of what follows. Numbers attributed
to that campaign were measured **there**, on PRIME, against a
`qwen3-embedding-0.6b` Q8_0 GGUF served by llama.cpp. Directions transfer;
magnitudes do not, and nothing below should be quoted as a prediction about
this corpus.

Everything marked *measured here* was taken against this repository's
installed `redstring 0.9.2` on 2026-08-21 while writing this document.

## What this is for

Three retrieval surfaces exist in this system and none of them uses the
redstring class built for it. One is a substring scan, one is a hand-rolled
copy of a redstring method's internals, and the third -- retrieving an entity
by describing it rather than naming it -- does not exist at all.

This document covers three stages, `A -> B -> C`. They are independently
useful and deliberately ordered so that each is informed by the last.

## Part 0 -- Four measurements taken while designing this

These are recorded first because two of them killed an earlier draft of this
design, and a reader who does not have them will re-propose it.

### `Retriever` matches names, on both channels

`redstring.Retriever` is documented as *"Ranked entity retrieval, fusing a
semantic and a lexical channel"*, which reads like the thing this design
wants. It is not.

* Its lexical channel is
  `graph.find_by_blocking_keys(query_blocking_keys(query))` followed by
  `lexical_score(query, entity)` -- blocking keys over the entity **name**.
* Its semantic channel searches the vector store, and
  `build_graph._embed_entities` writes those vectors as
  `provider.embed([entity.name for entity in entities])` -- **bare names**.
  No type, no properties, no relations.

So `Retriever` answers *"find the entity called X"* well and *"find the
entity that does X"* not at all. The first draft of this design proposed
enriching entity text with a relations block and letting `Retriever` see it.
There is nowhere for that text to go. This is why Part 2 exists as its own
stage rather than as a paragraph inside Part 1.

### `ChunkProjection` cannot be scoped to a source

`ChunkProjection` handles every `DocumentChunked` and calls
`replace_source`. Its only configuration is `eventsource`'s
`ProjectionOptions`, whose fields are `checkpoint_repo`, `dlq_repo`,
`enable_tracing`, `retry_policy`, `tracer` and `tenant_filter` -- no source
filter of any kind.

Two `ChunkProjection`s over one event store therefore each apply *every*
chunking event, and both stores end up holding everything. That is precisely
the crossing that isolating a card corpus is meant to prevent, so an
event-sourced card corpus would need either a second event store or a
custom projection. Part 2 avoids both by not event-sourcing cards.

### `SlidingWindowChunker` emits a wholly-redundant tail chunk

*Measured here.* `SlidingWindowChunker(default_chunk_size=1000,
default_overlap=500)` over 2,700 characters returns six chunks:

```
0    990    990
490  1485   995
985  1980   995
1480 2475   995
1975 2700   725
2200 2700   500
```

The last chunk is **wholly contained in the one before it**. This is
`stark-bench`'s `B-SLIDING-REDUNDANT-1`, open upstream, and present in the
version this repository installs.

It lands on us twice. `UsageReader` deduplicates on
`(source_id, start_char, end_char)`, and `1975 != 2200`, so it will not
collapse them -- a reader sees two overlapping passages, one a suffix of the
other, on the tail of every document longer than the window. And BM25 counts
the tail's terms in two chunks, so `aggregation: max` gives tail passages a
second draw that mid-document passages do not get.

### Chunk ids collapse on repetitive text, and our table corpus is the worst case

*Measured here.* Two hundred identical markdown table rows, chunked at
1000/500, return **ten chunks carrying two distinct texts**. The same text
appears at `(0,1000)`, `(500,1500)`, `(1000,2000)`, `(1500,2500)`,
`(2000,3000)` and `(2500,3500)`.

Chunk ids are content-addressed on `(source, text)` with no `start_char`, so
those nine windows collapse to one row on upsert. This is `stark-bench`'s
harness bug 3 -- *"189 chunks silently deduplicated"* -- reproducing on
exactly the corpus shape `MarkdownTableChunker` exists to serve. A long
uniform table indexes as roughly one chunk instead of ten, and `UsageReader`
can only ever cite one offset for content that recurs throughout it.

Nothing raises. The corpus simply holds fewer rows than the chunker emitted.

**`BoundaryPreferenceChunker` does not have this problem** -- the same input
gives two chunks with two distinct texts, at `(0,3000)` and `(2800,5000)`.
Both defects above are *introduced* by moving to small overlapping windows,
and Part 3 accounts for that honestly rather than presenting the chunker
switch as free.

## Part I -- The three surfaces

| surface | today | after |
|---|---|---|
| entity by **name** | substring scan over a page of entities, plus one `get_relationships_for` per hit | `Retriever` at `RetrievalMode.HYBRID` |
| entity by **description** | does not exist | BM25 over a derived entity-card corpus |
| **passage** | hand-rolled `tokenize` / `lexical_candidates` / `rank_chunks`; corpus chunked with `BoundaryPreferenceChunker` | same calls, corpus chunked with `SlidingWindowChunker`; `ChunkRetriever` only at Stage C |

The claim this design rests on: these are **three distinct tasks**, and two
of them are currently served by one substring scan and one hand-rolled BM25
that share no ranking model between them. Separating them is what lets each
use the class redstring already ships -- which is also the answer to "use
redstring more holistically", since `Retriever`, `ChunkRetriever` and
`RetrievalMode` are all exports this repository currently works around.

For scale: redstring exports 153 public names and this repository imports
about 25 of them.

**The passage surface keeps its hand-rolled calls for now, and that is not an
oversight to correct later.** `ChunkRetriever.__init__` requires an
`EmbeddingProvider` and dimension-checks it at construction, so adopting it
before chunk embeddings exist would mean carrying a provider through
production wiring purely to satisfy a collaborator that
`RetrievalMode.LEXICAL` never calls -- which is the trade `UsageReader`'s own
docstring already considered and rejected, correctly. Stage A changes what
that surface *reads* (a corpus chunked differently); Stage C is what changes
what it *calls*.

## Part II -- Stage A: adopt `Retriever` for entity lookup

`RedstringKnowledge.search` (`redstring_adapter.py:938`) filters with
`needle not in entity.name.lower()` over a page of the tenant's entities and
issues a `get_relationships_for` per surviving match. Its own docstring calls
it *"the first thing to revisit behind Neo4j"*.

Replace it with `Retriever.retrieve(query, tenant_id, k=limit, mode=HYBRID)`.
All three collaborators are already fields on the adapter: `self._embeddings`,
`self._vectors`, `self._store`.

What this buys, in order of how much it matters:

* **Fuzzy name matching.** Blocking keys match a misspelled or reordered name
  that a substring test rejects outright.
* **A semantic channel we already pay for.** `build_graph` embeds every
  extracted entity for consolidation scoring. Those vectors are written,
  stored, and read by exactly one consumer today. `Retriever` reads the same
  ones. The dense channel for entity lookup costs nothing new.
* **RRF fusion with `overfetch`.** `Retriever`'s own docstring explains why
  the default is 3 rather than 1: the candidates that decide a fused ordering
  are the ones just past each channel's cutoff, and asking each channel for
  exactly `k` makes them invisible.
* **Type filtering**, applied before truncation.
* **Deletion.** The substring loop, the per-hit relationship fetch and the
  canonical-id filter go away.

### The degradation this introduces, and why it must be loud

`_embedding_pair` probes the embedding endpoint once, lazily, and **latches
`(None, None)` on failure** -- logging at warning and letting consolidation
fall back to two features. That is a deliberate and correct trade for
consolidation: the alternative throws away an extracted document to lose an
optional third scoring feature.

It is not a correct trade for retrieval. Once `search` depends on
`Retriever`, a mistyped embedding model name silently turns fused retrieval
into whatever the lexical channel alone returns, with nothing raising and a
warning in a log nobody reads.

This is the shape of every real bug `stark-bench` found. Its report is
unambiguous: *"Every real bug in this project has been silent. None raised an
exception at the point of failure; each surfaced because a number looked
wrong."* Two of its rerank arms ran against a chat peer answering `502 Bad
Gateway`, fell back to retrieval order exactly as designed, and wrote
plausible scores; the field that would have caught it,
`llm_calls_per_query`, had been in every report from the beginning and
nothing read it.

So the requirement is that **a degraded retrieval mode is observable from
the result, not only from the log**: `search` returns the mode it actually
ran in alongside its matches, and a caller that asked for `HYBRID` and was
served `LEXICAL` can see that without reading a log line.

Deliberately *not* an exception. A dead embedding endpoint should degrade
entity lookup, not break it -- that is the same trade `_embedding_pair` makes
for consolidation and it is the right one. What changes is that the
degradation stops being invisible: a test can assert on it, and the console
and the agent can be told they are looking at one channel rather than two.

## Part III -- Stage B: the entity-card corpus

This is the delivery of the `stark-bench` finding that prompted the work.

### What the finding is

Two arms, same model, same chunking, differing only in whether the indexed
document carries a `- relations:` block naming the node's neighbours:

| agent | no relations | relations | change |
|---|---|---|---|
| dense | 0.16684 | 0.18269 | +0.016 |
| lexical | 0.20479 | 0.24913 | **+0.044 (+22%)** |
| hybrid | 0.19207 | 0.27711 | **+0.085 (+44%)** |

The mechanism was not predicted and is the part that transfers: PRIME's
queries name related entities verbatim, and those names appear in the
answer's own document **only** in the relations version. BM25 matches them
directly; a single dense vector compresses them away. Nearly the whole gain
arrives through the lexical channel.

The corollary for architecture: **a knowledge graph's edges are worth more as
text in the index than as a traversal at query time.** `stark-bench`'s
agentic arm, which traverses at query time, cost ~7.46 model calls per query
and was the worst arm measured on both corpora where it ran.

### The card

One synthetic document per entity, assembled from graph state:

```
Acme Corporation  (Organization)
also known as: Acme, Acme Corp.
founded: 1987
headquarters: Portland

- relations:
  acquired  Blackwell Systems
  subsidiary_of  Vantage Holdings
  competitor_of  Northwind Industries
```

The edge **type** sits beside the neighbour name because it costs the same
tokens and is what makes `acquired` and `competitor_of` discriminable to
BM25. Aliases are included because a merged entity's absorbed names are how a
reader is most likely to refer to it.

Cards are short by construction, so the length-normalisation effect
`stark-bench` measured (whole-document to `sliding-1000-500`: +0.071 dense,
+0.072 lexical, +0.070 hybrid) arrives without tuning a chunker for it.

### Cards are derived, not event-sourced

A card contains no information that is not already in the graph. It is an
assembly, not a generation -- no model call. Persisting it through the event
log would buy nothing and cost two things: staleness across restart, and the
projection-crossing problem of Part 0.

So the card index is **rebuilt from the graph at project open**, after the
graph replay, the way `graph_reader` synthesises ontology class nodes on
read. It is updated incrementally for affected entities after each ingest and
each consolidation. Its store is a separate `ChunkStore` instance written
only by the card builder calling `replace_source` directly.

Source ids are derived from the entity id, never chosen by a model. That
gives per-entity replacement for free, and a merged-away entity's card is
removed by replacing its source with an empty chunk list.

### Why the isolation is structural rather than a filter

Cards must never be reachable from `UsageReader`.
`application/entity_definitions.py` is emphatic that citations are
`(source_id, start, end)` into real documents, and enforces in code the parts
of that rule a prompt cannot. A card is synthesised text. A citation into one
would name a passage that no source document contains, while looking exactly
as checked as a real one -- which is the failure that module exists to
prevent.

Filtering by a source-id convention at read time would work, and is the kind
of thing that silently stops working. Because no projection writes the card
store, there is no event either store can mis-handle: a usage query cannot
reach a card because the card store is not the store it holds.

### What Stage B does not do

It does not rerank. `stark-bench` measured reranking as the largest single
gain in the whole campaign (hybrid 0.28214 to 0.46323 at `fetch=40`), and it
also measured that **a reranker shown eight arbitrarily-chosen neighbour
names scores 0.030 below one shown no relations at all**, while the same
eight chosen by BM25 gains 0.054 -- a swing of 0.083 attributable to
selection alone, roughly eighty times that campaign's LLM noise floor. A
reranker is worth building here, and it is worth building after there is
something to select from and a way to tell whether the selection helped.

## Part IV -- The chunker switch

`RedstringKnowledge.index` chunks the quotable corpus with
`MarkdownTableChunker(BoundaryPreferenceChunker())`. Its docstring's reason
is sound as far as it goes: redstring documents that chunker for passages
that will be quoted back to a reader.

It loses on retrieval, consistently. `stark-bench` I.5 found it **last on
dense retrieval across three embedding models**, and `sliding-1000-500` beat
it on every channel in both corpora where both ran (Nemotron dense 0.2125
against 0.1845; `qwen-mini` hybrid 0.4079 against 0.3883, lexical 0.3804
against 0.3662). Three models agreeing points at the chunker rather than at
an interaction with one embedding model.

Switch to `SlidingWindowChunker`, keeping `MarkdownTableChunker` around it.

### The quotability objection is weaker than it looks

*Measured here.* `SlidingWindowChunker.__init__` defaults are
`respect_sentence_boundaries=True, respect_paragraph_boundaries=True`, and
they work: the first chunk of a 2,700-character document at size 1000 is
`0-990`, not `0-1000`. Sliding windows snap to sentence boundaries too. The
difference against `BoundaryPreferenceChunker` is overlap and size, not
whether a quoted passage begins mid-sentence.

### Two upstream defects ride along, and are pinned here

Both were measured in Part 0. Both are `redstring`'s and cannot be fixed in
this repository. The decision is to **switch now and fix upstream in
parallel**, which means this repository carries a test for each so that the
day upstream lands is visible rather than inferred:

1. **The redundant tail chunk.** A test asserting that no chunk of an indexed
   document is wholly contained in another. It fails today. When upstream
   fixes `B-SLIDING-REDUNDANT-1` it goes green, and until then it is the
   record of a known defect rather than an unexplained duplicate in the UI.
2. **The content-addressed id collapse.** A test that indexes a long uniform
   table and asserts the corpus holds as many chunks as the chunker emitted.
   It fails today. The upstream fix is `start_char` in the chunk id
   derivation -- the same class of defect as redstring PR #64 and PR #71,
   both of which `stark-bench` found and redstring fixed.

Each test must be proved red before it is trusted, per this repository's
convention, and each docstring says which upstream change turns it green.

The interim cost, stated plainly so nobody rediscovers it as a mystery: a
long uniform table under-indexes, and the tail of every document longer than
the window yields one duplicate passage in the usages list.

## Part V -- Testing

The general rule this design is most exposed to is `CLAUDE.md`'s: an event no
projection handles counts as APPLIED, so a missing wiring produces an empty
read model rather than a refusal, and an assertion that a request *succeeded*
passes with the feature removed entirely.

Every test here therefore asserts on **data**, never on the absence of an
exception:

* **Entity lookup.** A query that a substring scan cannot answer -- a
  misspelling, or a reordered name -- returns the entity. This fails with
  Stage A reverted, which is the point.
* **Degraded mode is visible.** With the embedding probe forced to fail, a
  `HYBRID` request reports that it ran `LEXICAL`. Proved by breaking the
  probe on purpose.
* **Descriptive retrieval.** A query naming two of an entity's neighbours and
  none of its own words retrieves that entity. This is the Stage B result in
  one assertion, and it is unanswerable today.
* **Cards never leak into usages.** A `usages` call returns no card text. It
  passes trivially given the two-store design, which is the argument for that
  design; it is written down so that a later collapse into one store fails
  here rather than in a citation.
* **Cards track the graph.** After a consolidation merges two entities, the
  absorbed entity's card is gone and the canonical entity's card names the
  union of both neighbourhoods.
* **The two upstream defects**, as Part IV describes, each proved red first.

A note carried from `stark-bench` II.6 that applies directly to the last
group: a test whose inputs and whose code's branches are chosen by the same
person in the same hour tends to sample the cases that code already handles.
For the card builder, the input that distinguishes a correct implementation
from a plausible one is an entity with **no** relations and an entity whose
neighbour was merged away -- not a well-connected example.

## Part VI -- Stage C, sketched

Not designed here. Recorded so the ordering is legible:

Turn on the chunk semantic channel -- embed chunks at index time, retrieve
passages at `RetrievalMode.HYBRID`, and give `build_chunk_store` the
`postgres` branch it currently refuses by name so the corpus outlives the
process. That refusal is deliberate and its docstring is worth re-reading
before writing the branch: the last unexercised backend branch in that module
shipped an un-awaited coroutine to every caller.

This is what makes `dimension` stop being inert. It is last because it is the
most infrastructure per unit of evidence, and because Stage B will have said
whether the lexical channel alone already answers descriptive queries well
enough.

## Part VII -- What this deliberately does not do

* **No query-time graph traversal.** `stark-bench`'s agentic arm cost ~7.46
  model calls per query to be the worst arm measured. The graph's retrieval
  value showed up as text in the index.
* **No embedding-based selector.** Both embedding selectors lost to plain
  BM25, and lost to each other by less than the measured noise floor.
* **No benchmark harness.** Explicitly out of scope by decision. The one
  piece of that discipline kept is Part II's requirement that a degraded
  retrieval mode be observable from the result -- not because a benchmark
  would be unwelcome, but because that single field is what separates "the
  feature is off" from "the feature is working" and costs one assertion.

## Part VIII -- Delivery

Four pull requests, two per repository. The split is for attributability:
each of these changes what retrieval returns, and landing two together means
neither can be credited or blamed on its own. That is not a hypothetical
concern -- `stark-bench` I.3 spent three measurements and two wrong published
conclusions on a comparison whose arms differed in a second variable nobody
had noticed.

### research-team

**PR 1 -- `Retriever` for entity lookup (Stage A).** Replaces
`RedstringKnowledge.search`'s substring scan. Touches the adapter, the
`KnowledgePort` result shape (it gains the mode actually used), and the
agent's search tool. Does not touch the corpus, so it is independent of PR 2
in both directions: `Retriever` reads entities and vectors, never chunks.

**PR 2 -- the chunker switch.** `SlidingWindowChunker` in place of
`BoundaryPreferenceChunker` in `RedstringKnowledge.index`, plus the two
red-first tests pinning the upstream defects. Changes `chunking_signature`,
so existing corpora re-index on the next `index` call rather than needing a
migration.

Stage B (the card corpus) is a third PR and is not planned until these two
have landed, for the reason above: it changes what entity retrieval returns,
and it should not be measured against a baseline that moved underneath it.

### redstring

**PR 3 -- the redundant tail chunk.** `SlidingWindowChunker` emits a final
window wholly contained in the previous one whenever `overlap > 0` and the
document is longer than the window. Self-contained, no id or storage
implications, and the smaller of the two.

**PR 4 -- `start_char` in the chunk id derivation.** The riskier one, and
deliberately second. Chunk ids are content-addressed on `(source, text)`, so
adding `start_char` **changes every existing chunk id**. For any consumer
with a persisted chunk store that is a full re-index, not a migration --
which is affordable here (this repository's chunk store is in-memory and
rebuilt by replay) and may not be elsewhere. The PR should say so in its
description rather than leaving a downstream consumer to discover it.

Sequencing between the repositories is deliberately none. research-team PR 2
lands against the defects, not after their fix, and its two tests are what
make the upstream landing visible when it happens.

## Provenance

Measured in this repository on 2026-08-21 against `redstring 0.9.2`: the
sliding-window tail chunk, the repetitive-text id collapse,
`BoundaryPreferenceChunker`'s behaviour on the same input, the sentence-
boundary defaults, `Retriever`'s two channels, `_embed_entities` embedding
names only, and `ProjectionOptions`' fields.

Carried from `stark-bench`'s campaign of 2026-08-19/21 and **not** re-measured
here: every mrr, hit@ and recall figure, the three-model chunker result, and
the reranker selection swing.

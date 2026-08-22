# The co-mention channel does not run

Measured 2026-08-22 against a real model (`qwen3.8-27b-64k-txt` for extraction,
`qwen3-embedding-0.6b` at 1024 dimensions), five Wikipedia articles, 633
entities extracted, 545 canonical after consolidation.

This document is the input to a spec. It records what was measured and what is
still undecided; it does not prescribe a design.

## 1. The defect

`application/area_projection.py` takes co-mention edges as one of its two
signals, and `docs/design/learning-areas-and-paths.md` §2 describes them as
the density supplement that makes clustering work. **They are always empty.**

Evidence, end to end on a real ingest:

- 36 chunks stored for one document; **0 carry any `entity_ids`**.
- `ChunkCoMentions.passages()` over the real folded store returns **0 passages**.
- Projecting with and without those passages gives byte-identical results:
  31 areas, 437 placed, 108 dropped, both ways.

Cause, three facts each checked by grep rather than assumed:

1. `build_graph` is never passed `chunks=`. Zero call sites in the tree.
   Extraction is therefore the only thing that knows which entities came from
   which passage, and it is never given anywhere to record that.
2. The chunk store is filled solely by `RedstringKnowledge.index`, which calls
   `index_documents` on the raw text. That path runs before extraction and has
   no entity knowledge, so every `StoredChunk` it writes has `entity_ids: []`.
3. `ChunkCoMentions` is constructed in exactly one place, the web route in
   `interfaces/web/app.py`. **No test constructs it.** The two test modules
   that mention co-mentions (`tests/application/test_curriculum.py`,
   `tests/application/test_area_projection.py`) drive a stub port or literal
   `frozenset`s, so the port and its only adapter were each verified alone and
   never against each other.

The tell was on screen throughout: `DerivedFromLine` renders "*N* shared
passages" and has been printing **0** on every projection since the feature
shipped in #234.

## 2. What the fix collides with

`index` chunks at `SlidingWindowChunker(default_chunk_size=1000, default_overlap=500)`
for retrieval. Extraction chunks at `MarkdownTableChunker(SlidingWindowChunker(
default_chunk_size=config.extraction_chunk_size()))`, currently 2000 with
redstring's own overlap.

Passing `chunks=` to `build_graph` makes redstring write entity-linked chunks
under the *extraction* chunking. Both paths write `DocumentChunked` for the
same `source_id`, the projection folds them with `replace_source`, and that is
last-write-wins — so extraction's chunking would take over the corpus that
every quote and citation is drawn from, replacing a retrieval granularity that
was chosen deliberately.

`application/entity_definitions.py` requires every citation to be
`(source_id, start, end)` into a real document, so whatever is decided here has
to keep that true.

The repository has already solved a structurally identical problem once: entity
cards live in a **second** chunk store (`ProjectGraphs._card_stores`) rather
than sharing one with a source-id convention, and the comment there argues the
separation has to survive somebody not knowing about it.

## 3. Measurements that bear on the design

All against the 545-entity graph, matched edge budgets, uniform weight, so the
comparison isolates edge *selection*. Purity is measured against known ground
truth (three Roman articles, two plant-biology articles); it was **1.000 in
every arm**, so it rules out junk wiring but cannot rank the arms.

```
  graph alone                       31 areas  437 placed  108 dropped
  + cosine @250                     32 areas  473 placed   72 dropped
  + CSLS   @250                     38 areas  483 placed   62 dropped
  + cosine @500                     28 areas  489 placed   56 dropped
  + CSLS   @500                     30 areas  519 placed   26 dropped
  + cosine @1000                    22 areas  508 placed   37 dropped
  + CSLS   @1000                    21 areas  534 placed   11 dropped
  + shipped (cosine, floor 0.83)    31 areas  505 placed   40 dropped
```

Other measured facts:

- **The absolute similarity floor is not portable.** The same 0.83 admits
  0.60% of pairs corpus-wide, 5.07% within the Roman subset, 6.56% within the
  biology subset. A 10x swing in edge density from one constant, inside one
  corpus.
- **Anisotropy** (norm of the mean unit vector) is 0.554. The distribution is
  not squashed: p1 0.541, p50 0.646, p99 0.812.
- **Hubness under raw cosine is severe**: max k-NN in-degree 38 against an
  expected 5, and 26 entities are nobody's neighbour. Centring halves it
  (19 / 15). CSLS is best (15 / 0).
- **`EMBEDDING_NEIGHBOURS` is nearly inert** at the shipped floor: k = 3, 5, 8
  give 476 / 475 / 475 placed. The floor binds, not k.
- **Dissolution is real.** With no floor the graph collapses to 11 areas at
  k=5 and 7 at k=8.
- The projection is **deterministic** across runs under every arm tested.

## 4. Chunk size affects extraction quality, and the boundary is not written down

`config.extraction_chunk_size`'s docstring records that smaller chunks extract
more, which is true. Measured here on one document, holding everything else
fixed:

| chunker | entities | rels/entity | mean words in a name | clause-like names | no relationship |
|---|---|---|---|---|---|
| 3000, default overlap | 116 | 0.95 | 2.27 | 10% | 9% |
| 2000, default overlap (shipped) | 132 | 0.92 | — | — | — |
| 1000 / 500 overlap | 262 | 0.88 | 5.48 | 37% | 25% |

At 1000/500 the extra entities are largely sentence fragments: names go from
two words to five and a half, the `fact` type grows from 7 to 76, and a quarter
of entities connect to nothing. "More" and "better" separate somewhere between
2000 and 1000, and nothing in the tree says so.

## 5. Constraints

- Four CI gates: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pytest`, and `cd frontend && npm run verify`.
- **No data needs preserving.** Pre-release; there is no corpus worth
  migrating, and breaking changes to events, schemas and contracts are
  explicitly welcome. Blowing away existing projects is acceptable.
- `CLAUDE.md`'s conventions on comments and commit messages apply, in
  particular: say what was measured rather than reasoned, and name what a test
  would fail on.
- A test must fail against the *plausible alternative* implementation, not only
  against a broken one.

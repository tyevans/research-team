# The curriculum's problem is below the clustering

Measured 2026-08-22 against a running server (`qwen3.8-27b-64k-txt` extracting,
`qwen3-embedding-0.6b` at 1024), two Wikipedia articles ingested through the
real routes: 228 entities, 227 relationships, 18 co-mention passages, 321
semantic edges, 13 areas.

Input to two pieces of work. Records what was measured; prescribes nothing.

## 1. The clustering is fine. Its input is not.

A day was spent measuring the clustering layer to three decimal places --
purity 1.000 in every arm, cross-subject 0.00% in every arm, placement
saturated at 561 of 562. Every one of those metrics scores the graph below
**perfectly**, and the graph has three separate areas for Julius Caesar and
learning areas named after sentences.

The metrics are not wrong. They measure whether the clustering faithfully
grouped what it was given, and it did. Nothing measures whether what it was
given was worth grouping.

## 2. Propositions are entities, because the schema asks for them

`infrastructure/knowledge/schemas/research_corpus.yaml` declares:

```yaml
- id: fact
  description: A verifiable factual statement the text asserts
  examples:
    - "Tollers carry a narrow founding gene pool"
```

The example is a sentence. The model is complying, not failing. Measured
entities of this shape, all isolated (degree 0):

- `The word chloroplast is derived from the Greek words chloros (green) and plastes (the one who forms)`
- `Chloroplasts are only found in plants, algae, and some species of the amoeboid Paulinella`
- `Secondary and tertiary chloroplast lineages`

`fact` is 8 of 228 entities here, so it is not the whole of the dust -- but it
is the part that is *by design*, and an area anchored on one is named after a
proposition. One of the 13 areas is
`observation-that-chloroplasts-resemble-cyanobacteria`, 11 entities.

**The cluster there is good and the name is bad.** Eleven entities about the
resemblance between chloroplasts and cyanobacteria is the evidence for
endosymbiotic theory -- a real learning area. `_to_area` names an area after
its highest-centrality member, and `LearningArea.title` is `None` on every area
ever produced, so a slug derived from one entity's name carries the whole
burden of naming a topic.

The tension to resolve rather than assume away: `fact` entities are plausibly
right for a *research corpus*, which is what this schema is for. The curriculum
is a second consumer of the same graph with different needs.

## 3. Consolidation leaves three Caesars

Three of the 13 areas are one man -- `caesar` (55 entities), `julius-caesar`
(29), `gaius-julius-caesar` (27). The clustering is right: they are separate
nodes with separate neighbourhoods.

The entities, with their extracted types:

```
'Caesar'                     concept
'Julius Caesar'              person
'Gaius Julius Caesar'        person
"Caesar's father"            person
"Caesar's civil war"         event
"Caesar's remarriage to Pompeia"      event
"Caesar's election to the praetorship" event
```

Two distinct failures hide here and they want different fixes:

- **`Caesar` is typed `concept` while the other two are `person`.** Whether a
  cross-type pair can merge at all is unchecked; if it cannot, this is an
  extraction-typing problem wearing a consolidation costume.
- **`Julius Caesar` and `Gaius Julius Caesar` are both `person` and did not
  merge.** That is a genuine consolidation miss, on a containment pair, with
  three-feature scoring and an adjudicator available.

`config.vector_store`'s docstring argues the embedding feature exists so that
identically-named cross-document duplicates clear `LOW_SIMILARITY` 0.75. This
is that shape, on a real model, and it did not fire.

## 4. 16% of the graph is dust

37 of 228 entities have **no edge at all**; 92 more have exactly one. So 57%
of the graph has degree <= 1. The isolated set is roughly one third
propositions (§2) and two thirds ordinary entities extraction never connected
-- `glaucophytes`, `Kleptoplasty`, `Civil war`, `grain dole`.

**And the curriculum now places them.** The co-mention and semantic channels
took entities dropped from 105 to 7, which was reported as a win. On this
evidence part of that win is placing sentences into topic areas. An entity the
graph cannot connect was *correctly* dropped; rescuing it is only an
improvement if it is a thing worth learning.

Placement was the only available metric and it was allowed to stand in for
quality. It should not be optimised further without something that can tell a
rescue from a mistake.

## 5. Constraints for whoever works on this

- **Do not start a web server and do not run extraction or embedding jobs.**
  One llama-swap endpoint serves this machine and it holds one model at a
  time; two processes on different models make it thrash, which is how the
  last hour was lost. A server is already running on port 8931 against
  `course.db` if a live graph is needed -- read it, do not start another.
- Four CI gates: `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pytest`, `cd frontend && npm run verify`.
- No data to preserve. Pre-release; breaking changes welcome.
- A test must fail against the plausible alternative implementation, not only
  against a broken one.

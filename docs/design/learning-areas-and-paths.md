# Learning areas, learning paths, and the courses that come out of them

A project accumulates a knowledge graph and a corpus. Nothing folds either
into a statement about *what there is to learn here*. This is that fold:
entities and their relationships become **areas**, areas become ordered
**paths**, and a path's areas become **courses** — real markdown files with
lessons, assessments and resolved widgets, written into the project.

`docs/direction.md` states the organising observation this is an instance of:
"the log records what happened and almost nothing projects what it means."
Every design choice below is downstream of taking that literally.

## 1. What we cluster, and what we deliberately do not

**We cluster the knowledge graph, and embeddings join what the graph leaves
apart.** The graph is the substrate; the embedding channel is a second signal
weighted below it. This section used to argue for the graph *instead of*
embeddings on four grounds, and the argument has since been revised: one of
the four was simply wrong, one has been fixed rather than lived with, and one
was overstated. What is left is a reason for the ordering, not for the
exclusion.

### The one that was wrong

The original text said:

> **redstring embeds `entity.name` and nothing else.** [...] Clustering those
> vectors clusters *spellings*.

**That is nonsense, and it is worth being blunt about because it is the kind
of nonsense that sounds like rigour.** An embedding is not a string. Encoding
meaning is the entire reason embeddings exist: `glass` and `cup` share no
substring and sit close together in any competent embedding space, which is
exactly the pairing a curriculum wants and a string comparison can never
find. The measurement the original quoted — that under a real model an exact
duplicate and `University of York` / `University of Cork` land about 0.011
apart — says the *name* is a thin input, not that the *vector* is a spelling.

The real objection is narrower and does survive: a bare name carries no type,
no properties, no neighbourhood. So the fix is enrichment rather than
avoidance. This project now embeds each entity's **card** — the same text
`entity_cards` assembles for BM25, carrying name, type, properties and named
relations — through `infrastructure/knowledge/entity_embeddings.py`. One
assembly feeds both, so the text a query matches lexically and the text a
vector encodes cannot drift apart.

### The one that was true and has been fixed

> **There are no vectors to read back on a default install.**

True when written, and it was a defect rather than a constraint. redstring
computed a vector per entity on every ingest, folded it into the store, and
returned a *count* instead of the `EntitiesEmbedded` event it had built; the
ingest path appended the `DocumentExtracted` beside it and let the rest go.
Measured against a copy of the real database on 2026-08-22: **zero
`EntitiesEmbedded` rows in a log holding 8 `DocumentExtracted` and 772
`EntitiesMerged`.** Every vector the system ever paid for died with its
process.

Both channels are now on the log and folded at project open by
`EmbeddingsForModel`, so a vector store is derived from the log exactly as the
graph and the corpus already were.

### The one that was overstated

> **`VectorStore` has no enumeration.**

Its method list was accurate and the conclusion was not. There is no "give me
every vector", but every id worth asking about is already in hand — they come
from the graph — so enumeration by key is a `get` per entity against an
in-memory dict. `semantic_neighbours.py` does precisely that, and the reason
it does the k-nearest arithmetic itself is unrelated: `search` per entity is
quadratic in Python and measured at 13.9s for 500 entities, against 0.056s
for the same work as one matrix multiply.

### The one that still decides the ordering

**The graph is derived from the log; a re-embedding is not.** A graph store is
rebuilt by folding at project open, so a projection over it is reproducible
years later. Vectors are now folded too — but they were *produced* by a model
call, and nothing re-embeds on the open path, deliberately: `rebuild_graph`
must not depend on a live endpoint or a project reopened years from now would
not open. So a vector encodes the neighbourhood its entity had when it was
extracted, and refreshing it is something a person asks for
(`POST /projects/{id}/embeddings`).

That is why a semantic edge is weighted below an asserted relationship rather
than above it, and admitted only above a similarity floor: a relationship is
something a model read and stated about a document, and a semantic edge is a
hypothesis no document ever made. The graph decides the shape; embeddings
close the gaps in it. §4 has the weights.

## 2. The graph we actually cluster

> **This section described a channel that did not run, from #234 until
> 2026-08-22.** Co-mention edges were always empty: the adapter read entity
> links off stored chunks, and the only writer of chunks is `index_documents`,
> which runs before extraction and knows no entities — so every chunk carried
> `entity_ids: []`. Measured over a real ingest: 36 chunks, 0 linked, 0
> passages, and a projection byte-identical with the channel present and
> absent. `docs/design/co-mention-channel-findings.md` has the measurement and
> `docs/design/co-mention-repair-spec.md` the repair. The table below is now
> true; it was aspirational for one release.
>
> Two things the repair changed that this section had wrong. The links reach
> the log through `event_store=` alone — `build_graph` records the chunking
> whether or not it is given a chunk store — so they are folded into a
> `CoMentionIndex` holding `(source_id, chunk_index) -> entity ids` and no
> text. And stored links are **pre-consolidation** ids that nothing rewrites,
> so reading them against a canonical graph silently dropped every merged
> entity until `RecordedCoMentions` began resolving them through the alias
> graph.


Extracted relationships alone are too sparse. A corpus of 2,000 entities may
carry a few hundred relationships, leaving most entities isolated — and an
isolated entity is its own singleton community, which turns the projection
into a list. So the clustering graph is built from **two** edge sources,
weighted differently because they mean different things:

| Source | Weight | Why |
|---|---|---|
| An extracted `GraphRelationship` | `RELATION_WEIGHT` = 1.0 | A model read a document and asserted these two things are connected. That is the strongest evidence available. |
| Co-mention in one *passage* | `CO_MENTION_BUDGET / pairs` | Two entities named in one paragraph are about the same thing more often than not. Weak individually, decisive in aggregate. |

**Passages, not documents**, and the grain matters more than it looks. Two
entities in one paragraph are evidence about the same subject; two entities in
one fifty-page document are evidence that the document is long. The corpus
already stores chunks and already rebuilds them by folding `DocumentChunked`,
so the tighter grain is also the one that costs nothing extra and replays
identically.

Each passage contributes **`CO_MENTION_BUDGET` in total**, divided among its
pairs. Without that normalisation a single long passage dominates: pairs grow
quadratically where relationships grow linearly, so twenty entities in one
chunk is 190 unit edges against a project that may hold only a few hundred
stated relationships in all. The graph would then be a projection of *passage
length*, and the longest paragraph in the corpus would become the curriculum.
Dividing by the pair count makes every passage contribute the same total
influence regardless of how much of it there is: a passage is one voice.

A second guard sits above it. `MAX_PASSAGE_ENTITIES` drops a passage naming
more than twenty-five entities entirely, and it is a *relevance* guard rather
than a performance one — a passage listing forty entities is a contents page,
an index or a glossary, and the "these belong together" inference it licenses
is false, because everything in the project appears in it. Normalisation stops
such a passage dominating by volume; it cannot stop it wiring the whole graph
into one blob at low weight, which is exactly what a curriculum must not be.


Both edge sets are symmetric and summed into one undirected weighted graph.
Direction is not lost: it is read separately in §3, off the original
relationships, because direction answers a different question (what comes
first) from the one clustering answers (what belongs together).

## 3. Deterministic community detection

**No new dependency.** `numpy`, `networkx`, `scipy` and `scikit-learn` are
all absent from this project's tree (checked, not assumed). Adding one for
~150 lines of graph arithmetic would be the largest dependency in the project
for the smallest reason, and the thing we need most from the algorithm —
determinism — is the thing a general library gives away first.

The algorithm is **greedy modularity maximisation** (Clauset–Newman–Moore):
start with every entity in its own community, repeatedly merge the pair of
communities whose merger raises modularity most, stop when no merge helps.

It is chosen over label propagation for one reason: **label propagation is
not deterministic and cannot easily be made so.** Its result depends on visit
order, and pinning the order pins the result to an arbitrary choice that
nobody can defend and that changes the moment an entity is added. Greedy
modularity has a deterministic answer given a deterministic tie-break, and
that is what this implements: **ties in ΔQ break on the pair of community
keys, which are entity ids.** So the same graph produces the same areas on
every machine, on every run, forever — which is what makes it safe to store
the result as a fact and what makes a regression test possible at all.

The cost is honest and stated: CNM is O(n² log n) in the worst case against
label propagation's near-linear, and `MAX_CLUSTERED_ENTITIES` refuses a graph
above the ceiling rather than running for minutes. A refusal a person can see
beats a projection that silently takes the whole request budget.

**Two post-passes, both of which exist because the raw output is not what a
curriculum wants:**

- *Singletons are absorbed, not shipped.* An entity with no surviving edge is
  attached to the community holding its strongest neighbour, and dropped from
  the projection entirely if it has no neighbour at all. A "learning area"
  with one member is not an area, and shipping fifty of them buries the eight
  real ones.
- *Oversized communities are split.* Modularity is happy to produce one
  community holding 60% of the graph. `MAX_AREA_FRACTION` re-runs the pass on
  that community's induced subgraph. This is bounded to one recursion, and
  the reason is that unbounded recursion on a genuinely homogeneous cluster
  splits it into arbitrary halves forever; one pass catches the "two subjects
  got glued" case, which is the one that happens.

## 4. Where embeddings come in

**Built, and not as the tie-break this section used to describe.** The design
here was a bounded nudge to ΔQ — embeddings adjusting a merge decision
modularity had already almost made, capped so that "a restart that loses every
vector changes the areas at the margin and never wholesale". That cap existed
to survive a specific defect: vectors did not survive a restart (§1). Once
they do, buying safety by making the signal too weak to matter is paying for
insurance against a fire that has been put out.

So embeddings are a **second kind of edge in the same graph**, not a
correction applied to the clustering of the first kind. Each entity's k
nearest neighbours in card-embedding space become weighted edges, and
modularity runs over relationships, co-mentions and those together.

| constant | value | why |
|---|---|---|
| `EMBEDDING_WEIGHT` | 0.6 | Below `RELATION_WEIGHT` (1.0), above one passage's whole `CO_MENTION_BUDGET` (0.5). A model asserted a relationship; a passage put two names near each other; an embedding says two things look like one subject and no document ever said so. |
| `EMBEDDING_NEIGHBOURS` | 5 | Similarity is dense — every entity has a nearest neighbour. Unbounded, 500 entities is 125,000 non-zero edges and modularity over a near-complete graph has no communities to find. Sparsity is the condition the method depends on. |
| `MIN_EMBEDDING_SCORE` | 0.83 | On redstring's `(1 + cosine) / 2` scale, so a cosine of about 0.66. Without a floor the sparsest corner of a graph gets the same five edges as the densest, which is where k-nearest-neighbour invents structure. |

**The weight is rescaled, not multiplied.** `EMBEDDING_WEIGHT * score` is the
tempting form and it is nearly flat over the range that occurs: real card
similarities sit near the top of the scale, so a pair that scraped past the
floor would get about four fifths the weight of a perfect match. The floor is
mapped to zero instead, so an edge admitted by a hair contributes by a hair.
`test_a_pair_at_the_floor_contributes_almost_nothing` is what separates the
two.

**What this changes that the nudge could not.** An entity with no relationship
and no co-mention is invisible to the graph — `_absorb_small` drops it,
correctly, because on the graph alone there is nothing to say about where it
belongs. A semantic edge places it. That is the `glass`/`cup` case.

**And it is worth six entities, not the fifty-four this section used to
imply.** §4a has the measurement. Every number quoted for this channel before
2026-08-22 was taken against a projection with the co-mention channel *dead*
(§2), which is a baseline no running system has. Against the repaired
baseline the semantic channel takes 555 placed to 561. It is a real gain and a
small one, and the sentence above is true of six entities.

**Absence stays ordinary.** Embeddings are off on some installs, absent on any
project ingested before they were durable, and missing when a provider's
endpoint was down. All three arrive as an empty sequence and the projection is
correct without them. What must *not* be silent is which of the two runs a
reader is looking at, so `used_embeddings` and `semantic_count` ride on every
curriculum response and are rendered — `used_embeddings` follows the edges
actually drawn, not the configuration, because a run handed a thousand pairs
that all fell below the floor used embeddings in no sense a reader cares about.

## 4a. What the three channels are actually worth

Measured 2026-08-22 against a real model — `qwen3.8-27b-64k-txt` extracting,
`qwen3-embedding-0.6b` at 1024 dimensions — over five Wikipedia articles
(three Roman, two plant-biology), 663 entities extracted, 562 canonical, 43
co-mention passages, 824 semantic edges at the shipped selector.

| arm | areas | placed | dropped |
|---|---|---|---|
| graph alone | 25 | 457 | 105 |
| graph + co-mentions | 23 | 555 | 7 |
| graph + semantic | 26 | 518 | 44 |
| graph + both (ships) | 23 | 561 | 1 |

**Mass is a bad predictor of impact, and this is the number to remember.** By
adjacency weight the three channels are relations 82.3%, semantic 14.8%,
co-mentions **2.9%** — and the 2.9% channel rescues 98 entities where the
14.8% one rescues 61. The arithmetic was predicted correctly beforehand (≤3.7%
from 43 passages against 564 relationships) and the *inference* drawn from it —
that so little mass could not move the clustering — was wrong.

The reason is placement, not quantity. An isolated entity needs exactly one
edge to become placeable, and co-mention weight lands on precisely the
entities the relationship graph missed. Relation mass piles up between hubs
that were already connected and changes nothing about who gets an area.
**Anyone tuning `CO_MENTION_BUDGET` by watching total weight is watching the
wrong number.**

`MAX_PASSAGE_ENTITIES = 25` is live and close to binding: the median passage
names 19 entities, the largest names 47, and 3 of 43 passages are excluded.
That constant could not be known until the channel ran, and now can be.

### Selectors, re-measured against the repaired baseline

With only 7 entities left to place, no selector can win on placement. They are
separable on damage instead — whether they glue areas together.

| arm | edges | areas | placed | cross-subject |
|---|---|---|---|---|
| no semantic | 0 | 23 | 555 | 0.00% |
| shipped (cosine + floor) | 824 | 23 | 561 | 0.00% |
| cosine @500 | 500 | 28 | 560 | 0.00% |
| CSLS @500 | 500 | **32** | 561 | 0.00% |
| CSLS @1000 | 1000 | 15 | 561 | 0.00% |

CSLS reaches the ceiling with 500 edges where the shipped selector needs 824,
and holds 32 areas against 23 — less gluing for fewer edges. It is **not**
adopted here: it buys zero entities, and whether 32 areas beats 23 is a
question this corpus cannot answer. See `BACKLOG.md`.

**Two metrics that failed to discriminate, recorded so nobody rebuilds them.**
Area purity against the known two-subject split is 1.000 in every arm. The
cross-subject edge rate — proposed specifically because purity could not rank
the arms — is 0.00% in every arm, including 1000-edge CSLS. Rome and plant
biology are far enough apart that no selector ever crosses, which speaks well
of the embedding and makes this corpus useless for ranking. **A corpus of
closely-related subjects is what a future comparison needs**, and building one
is prerequisite to any further tuning here.

## 5. From areas to paths

An area is a set. A path is an order, and the order is derived, not invented.

Three signals combine into a directed prerequisite score between every
ordered pair of areas (A → B meaning "A before B"):

1. **Referential asymmetry.** Count the extracted relationships running from
   A's entities to B's entities and back. If A's members are cited by B's
   much more than the reverse, A is foundational to B. This is the strongest
   signal and carries the largest weight.
2. **Temporal precedence.** Where both areas carry dated entities, the area
   whose median extent is earlier comes first. Weak on its own — chronology
   is not pedagogy — and useful as a tie-break in historical corpora, where
   it is often exactly right.
3. **Definitional breadth.** An area whose entities appear across many source
   documents is more likely to be foundational vocabulary than one confined to
   a single document. Breadth precedes depth.

The result is a weighted digraph over areas. It will contain cycles, because
real subject matter is mutually referential. **Cycles are broken by dropping
the weakest edge in the cycle, and the drop is recorded on the path as a
`contested` marker** rather than hidden — an ordering that had to break a
genuine mutual dependency is exactly the ordering a human should look at, and
silently producing a clean topological order would destroy the one piece of
information worth surfacing.

The topological order is then stabilised by area id, so two runs over the same
graph produce the same path.

**A project yields more than one path.** The default path covers every area
in prerequisite order. Additional paths are cut from the same digraph by
following the prerequisite closure of a chosen destination area — "what do I
need to know to understand *this*" — which is the shape a person actually
wants and which falls out of the graph we already built for free.

## 6. Applying Understanding by Design

`workflows/ubd.py` already encodes UbD's three-stage shape and its two
deliberate departures. It terminates at a unit plan, deliberately: "UbD has no
production or delivery half at all… it assumes a teacher who will do the
producing."

We are that teacher. So the course authoring here is UbD **through Stage 3 and
then past it**, and the fact that it goes past it is a departure recorded
here rather than a silent extension of the preset:

- **Stage 1 — Desired results.** Per area: enduring understandings, essential
  questions, and the knowledge/skills split. Grounded in the area's anchor
  entities, which are the ones the graph says are central rather than the
  ones a model finds interesting.
- **Stage 2 — Evidence.** Assessment items authored as the component blocks
  `application/components.py` already validates — `mcq`, `cloze`,
  `flashcards`, `checklist`. Every one of them is graded server-side with the
  answer key withheld from the learner projection, so an assessment written
  here is a real assessment and not a printed quiz.
- **Stage 3 — Learning plan.** The lessons themselves, in order, each one a
  markdown file.

**Backward design is enforced structurally, not requested politely.** The
authoring pass generates Stage 1, then Stage 2 *given only Stage 1*, then
Stage 3 *given Stage 1 and 2*. A model asked for all three at once writes
lessons first and reverse-engineers the understandings to match, which is
exactly the failure UbD exists to prevent. Three calls cost more than one and
buy the methodology actually being applied.

## 7. What a course looks like on disk

Markdown files, written into the project's virtual filesystem under the
existing `/course` convention, carrying the frontmatter
`application/artifacts.py` already parses:

```
/course/paths/<path-slug>.md              the path: its areas, its order, its contested edges
/course/areas/<area-slug>/unit.md         UbD stages 1 and 2 for that area
/course/areas/<area-slug>/lesson-01.md    Stage 3, one file per lesson
/course/areas/<area-slug>/lesson-02.md
```

They are ordinary markdown. A person can read, diff and edit them, and the
component fences render live in the console because that is what
`LessonDocument` already does with any markdown artifact. **Nothing new is
invented on the rendering side** — the ten component types already exist and
already resolve against this project's own graph, so a lesson can carry a
`graph` widget showing the area it is teaching, a `timeline` of its dated
entities, a `definition` pulled from the entity's own definition pass, and an
`evidence` block citing the source passage. That is the payoff of clustering
the graph rather than a vector space: the course is *wired to the material it
came from* rather than merely written about it.

## 8. The UX

Two new facets, `area` and `path`, alongside the existing eleven. `Selection`
already carries an id for every plain facet, so the routing grammar needs no
change beyond the constants.

**They share one tab, and that is a correction rather than the plan.** The
first arrangement gave each its own tab in MATERIAL and broke the strip. So
there is one **Curriculum** tab, and a radio group inside the pane chooses the
reading — writing the facet rather than local state, so which reading somebody
is looking at survives a reload and can be sent to a colleague, which is the
whole argument for `path` being a facet at all.

Three measured consequences, all recorded for whoever adds the twelfth tab:

- Two tabs needed **837px** of strip against MATERIAL's **646px** floor, and
  `project-stacked.browser.test.tsx` found two clipped controls in the narrow
  band.
- With one tab the strip needs **780.703125px**, so the floor moved **646 ->
  784**. That leaves ~50px of clearance in the wide band where 646 had ~300: a
  twelfth tab does not fit without shorter labels or a wider breakpoint.
- `.tabs` gained `overflow-x: auto`. `project-stacked.browser.test.tsx` had
  predicted this edit and deliberately left the choice open between wrapping
  and accepting the clip. Wrapping was rejected because a wrapped tab row is
  *taller*, so every tab strip in the console would change height at some
  width; a scroller is inert until the content does not fit, which is every
  existing use of `.tabs`.

Three surfaces, in the order a person meets them:

1. **The area map.** What this project turned out to be about: areas as
   cards, each naming its anchor entities. Its job is to be *falsifiable at a
   glance* — a reader who knows the subject can see immediately that two areas
   should be one, and the projection is worth nothing if they cannot. That is
   why a card leads with entity names rather than with a generated title: a
   plausible title fits a wrong cluster perfectly.
2. **The path.** Areas in prerequisite order, with the reason for each step
   readable and contested edges lifted to the top. Not a graph drawing: the
   question a person has is "why is this second", and a force-directed picture
   cannot answer it while an ordered list with rationale can — and stays
   readable at forty areas.
3. **The course.** The generated files, in the reader that already renders
   them. Each authoring run writes into its **own** session's workspace, so
   the run frame carries a session id per finished area and the panel links
   them; without that the files are reachable only by finding the session in
   the fork tree, which is to say not reachable.

**Reading is automatic; writing is not**, and an earlier draft of this section
had that backwards. It said "a person asks for areas to be projected", which
would mean a button and a poll in front of a pure function — the projection is
recomputed per request behind a cache keyed on the graph's counts, so a plain
GET is both cheaper and simpler than the machinery that would let somebody
trigger it.

What *is* explicit is authoring, and for the reason the earlier draft gave
about projection: it costs three model turns per area, and a run started
without somebody asking would commit a local model to twenty minutes. Nothing
re-projects and nothing re-authors on extraction, so a curriculum somebody is
halfway through is never rewritten underneath them.


### The embedding refresh, and why it is a button

`EmbeddingRefresh` sits above the map and says which of the two runs the
reader is looking at — clustered on the graph alone, or with *n* links found
by meaning — with the action right beside the diagnosis rather than filed
under settings.

It is a button and not an automatic pass because of §1's last point: nothing
re-embeds on the open path, so that a project reopened years from now does not
need a live endpoint. That makes staleness a permanent, ordinary state rather
than a transient one, and a permanent state a reader cannot see is the failure
this whole document keeps circling.

Three outcomes are kept distinct, because collapsing them is how a person
loses an afternoon: the build has no embedding wiring (503), embeddings are
configured but off or the project is empty (202, `embedded: 0`, rendered as
"nothing was embedded" rather than as success), and the endpoint is there and
refused (502, with the provider's own message). A bare "done" over the middle
one is a lie.

## 9. What this does not do

- **It does not re-project when the graph changes.** The result is a snapshot
  with the entity count it was built from recorded on it, so a stale
  projection is visible as stale rather than merely wrong.
- **It does not grade a path.** No score says whether a curriculum is good.
  That is a judgement, `application/checks.py` is where judgements live, and
  inventing a weaker second copy here would be the copy the UI used —
  `application/course.py`'s docstring makes this argument already and it
  applies unchanged.
- **It does not touch topic seeding.** Topics are questions the agent is
  investigating; areas are what the answers turned out to cluster into. They
  are different objects at different ends of the pipeline and merging them
  would lose both.

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

**We cluster the knowledge graph. We do not cluster the embeddings.** This is
the load-bearing decision and it went the opposite way from the obvious one,
so the reasoning is recorded in full.

The obvious design is k-means over entity vectors. Four facts, each checked in
this repository rather than assumed, rule it out:

1. **There are no vectors to read back on a default install.**
   `infrastructure/knowledge/stores.py` says it plainly: "A vector store lost
   with the process is *gone*: this project never appends `EntitiesEmbedded`,
   so there is nothing for a replay to fold." The default is `memory`. A
   feature keyed to vectors would work in the session that extracted and be
   empty after a restart — the exact silent-empty failure `CLAUDE.md` warns
   about under *Events*, where nothing raises and the endpoint answers 200
   with nothing in it.

2. **`VectorStore` has no enumeration.** Its methods are `get`, `search`,
   `upsert`, `upsert_many`, `delete`, `delete_by_tenant`, `dimension`
   (checked against the installed redstring, not the docs). You can ask for
   one vector by id, or for the k nearest to a probe. There is no "give me
   every vector", which is what any clustering pass needs. Reconstructing one
   by `get`-ing per entity id is possible and is a call per entity against a
   store that may not have the entity at all.

3. **redstring embeds `entity.name` and nothing else.** `config.vector_store`
   records this and the measurement behind it: the embedding feature is "a
   blurrier second measurement of the string the name feature already
   measured", and under a real model an exact duplicate and `University of
   York` / `University of Cork` land about 0.011 apart. Clustering those
   vectors clusters *spellings*. "Battle of Actium" and "Battle of Philippi"
   would land together because both are battles named alike, while "Actium"
   and "Octavian" — the same subject matter — would not. For consolidation
   that blurriness is a feature. For projecting learning areas it is
   precisely the wrong signal.

4. **The graph is derived from the log and the vectors are not.** A graph
   store is rebuilt by folding at project open, so a projection over it is
   reproducible years later — which is the property the whole system is built
   to have. A projection over vectors is reproducible only if the embedding
   endpoint still exists and still returns the same numbers.

So the signal is the graph, and embeddings become an *optional refinement*
(§4) rather than the substrate.

## 2. The graph we actually cluster

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

## 4. Where embeddings do come in

**Not built, and this section is the design for when it is.** `AreaProjection`
carries `used_embeddings` and the field crosses the wire on every curriculum
response, so the seam exists and answers `false` honestly. It is deliberately
*not* rendered: a line on screen saying "no embeddings were used" on every
projection forever is noise, and the moment it can be `true` is the moment it
becomes worth a reader's attention. Saying so here rather
than describing the plan in the present tense: a design document that reads as
though a feature shipped is the one that stops anyone building it.

The shape, when it is built: not the substrate — a **tie-break available when
it is real**. When a live vector store holds vectors for both endpoints of a
candidate merge, the cosine similarity of the two communities' centroids
adjusts ΔQ by at most `EMBEDDING_NUDGE`. The bound is the whole design: the
projection with
embeddings present and the projection with them absent differ only where
modularity was already close to indifferent, so **a restart that loses every
vector changes the areas at the margin and never wholesale**. A person cannot
be handed a different curriculum because a process bounced.

This is off unless the store both exists and answers, and its presence is
reported in the projection so a reader can tell which of the two runs they
are looking at.

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

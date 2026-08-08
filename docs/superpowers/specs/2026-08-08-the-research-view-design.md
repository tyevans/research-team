# The research view

Everything the research side of this system knows is currently reachable only by
an agent. Topics exist as a full aggregate with eleven commands and an
eight-trigger attention model, and have **zero HTTP surface** -- `list_topics` and
`open_topic` are agent tools and nothing else. The knowledge graph has one read
method, `search`, which returns entry points and is documented as "not traversal".
Documents are the exception: `GET /api/projects/{id}/sources` already lists them
and already serves citable spans.

So a person can watch research happen -- the course page does that well since
"Watching the work" -- but cannot *look at what it produced* except by asking an
agent to tell them.

This design adds a page for reading that state. A new top-level route,
`#/research/:projectId`, with four regions: topics, seeding, documents, graph.

It is the piece the previous spec deferred by name:

> **A browsable graph.** Read methods on `KnowledgePort` (`entities`, `neighbors`,
> `merges`) and a view over them are a separate piece of work, deliberately
> deferred. They read state rather than watch work and share no code with anything
> here.

That division still holds, and it is why this is a sibling route rather than a
tab on the course page. The course page watches work in flight; every frame it
renders is provisional and vanishes on restart. This page reads durable state.
Two different questions, two different lifetimes, two different pages.

## What this is not

**A new domain concept.** No new aggregate, no new event, no new command.
Everything here is read-side composition over ports that already exist, plus
three commands the `Topic` aggregate already implements and nobody has ever been
able to call.

**A second way to run research.** Seeding opens topics. It does not investigate
them. `AutoResearchDriver` remains the only thing that works a queue, and this
page links to the course page rather than reimplementing its controls.

**An agent-facing close.** `application/topics.py` documents closing as human-only
and `TopicPort` deliberately omits it. This design honours that: closing gets an
HTTP route and a dialog, and no tool.

---

# Part A -- topics

## The surface

```
TOPICS                                             12 open · 3 need attention

▲ How does spacing interval affect retention?      investigating · 4 sources
    never investigated · low coverage
  Why does massed practice feel more effective?    open · 0 sources
  Does the effect hold for motor skills?           answered · 9 sources · 2 findings
```

Attention triggers are rendered under the question that carries them. They are
computed on read and never stored -- `topic_attention.py` is explicit about that
-- so the page asks for them with the list rather than caching them.

## Reading

New `TopicReadPort` in `application/topic_read.py`, project-bound at construction
in the same way `CorpusReadPort` is:

```python
class TopicReadPort(Protocol):
    async def list_topics(self) -> list[TopicView]: ...
    async def read_topic(self, topic_id: UUID) -> TopicDetail | None: ...
```

`TopicView` is `TopicSummary` plus the topic's `TopicAttention`. `TopicDetail`
adds sub-questions, linked sources, findings, and contests -- everything the
aggregate holds that a reader would want and the summary drops.

Routes: `GET /api/projects/{id}/topics`, `GET /api/projects/{id}/topics/{tid}`.

**Why a second port rather than widening `TopicPort`.** `TopicPort` is the agent's
vocabulary; its four methods are four tools. Adding read shapes there would put
methods on an interface whose whole meaning is "what the model can do", and the
next reader would reasonably wire them into tools. A separate port keeps the
agent surface a closed set.

## Managing

Three commands the aggregate already implements, exposed for the first time:

| Route | Command |
|---|---|
| `POST .../topics/{tid}/status` | `SetTopicStatus(to_status, justification)` |
| `POST .../topics/{tid}/sub-questions` | `AddSubQuestion(text)` |
| `POST .../topics/{tid}/sub-questions/{n}/resolve` | `ResolveSubQuestion(n, answer)` |

`SetTopicStatus` requires a justification in the domain, so the route requires it
too -- a required body field, rejected blank with 422, and a required textarea in
the dialog. A status change with an empty reason is the thing the aggregate went
out of its way to make impossible, and the transport should not quietly supply a
default to get past it.

The question text stays immutable. There is no rename route, because there is no
rename command, and inventing one would mean an audit trail in which a recorded
finding can end up attached to a question nobody ever asked.

Status is not restricted to forward transitions: `decide` rejects only
`to_status == state.status`, so reopening an answered topic is legal, and the
dialog offers it.

## What does not change

`MAX_OPEN_TOPICS = 50` still caps live topics, and still caps them at the
aggregate. The page reports the cap when it is hit; it does not enforce it.

---

# Part B -- seeding

## The surface

A subject field above the topic list. Type "spaced repetition and memory
consolidation", press seed, and topics arrive in the list as they open.

## The mechanism

`POST /api/projects/{id}/topics/seed` with `{subject, max_topics}` returns 202.
Progress arrives on the existing SSE feed.

Underneath it is **one `TurnSupervisor` turn** with a seeding system prompt, run
through the attachment that already binds `open_topic` to the project. There is
no new agent, no new tool, and no new loop.

**Why one turn rather than a round-per-turn run.** `auto_research.py` argues for
round-per-turn because investigation is long, failure-prone, and unbounded.
Seeding is none of those: it is one bounded burst of naming, it either produces
topics or does not, and a failure that discards the whole thing loses seconds. The
atomicity that makes a long run worthless makes a short one clean.

## The prompt's rule

The user's instruction, stated in the prompt as the decision procedure:

> Open a set of broad, orthogonal topics covering this subject. Work from your own
> knowledge. Call `web_search` **only** if you cannot confidently name a varied set
> for this subject -- if the subject is unfamiliar, or if the topics you can name
> all cluster in one corner of it.

Search being absent is the normal case, not a degraded one. With no
`AGENT_SEARXNG_URL` set, no search tool is registered at all, and the agent
proceeds from knowledge -- which is the path this rule prefers anyway. The
condition is written as "if you cannot", not "if search is available", so the
prompt reads identically in both deployments.

`fetch` is untouched and still floors at `ask`. Seeding never needs it.

## Reporting

The turn's `open_topic` calls already append to the log, and the page already
holds a live feed. So arrivals need no new channel: the topic list invalidates on
the relevant log frames and the new topics appear. Seeding's own lifecycle
(running / done / failed) is provisional state on the same footing as extraction
frames, and follows the pattern `ExtractionActivity` established -- an in-memory
per-project channel plus a catch-up route, `GET .../topics/seed`, since
unpositioned frames cannot replay through `Last-Event-ID`.

---

# Part C -- documents

Almost nothing to build. `GET /api/projects/{id}/sources` lists `DocumentRecord`s
and `.../sources/{sid}?start&end` reads text with offsets clamped by `quote()`.

The page adds a virtualized list over that -- `@tanstack/react-virtual`, ~7 kB
gzip -- and a reader pane. Dropped documents stay in the listing with their
`dropped_reason` shown rather than being filtered out, because the corpus keeps
them deliberately and a browser that hides them would misreport what the project
holds.

Sorting and filtering are a `useMemo` over an array. No table library.

---

# Part D -- the graph

## The surface

A force-directed canvas. Search or filter by entity type to get entry points,
click a node to focus it, expand to pull in its neighborhood.

## Reading

The `GraphStore` protocol already has everything this needs and none of it is
reachable:

```python
find_entities(tenant_id, *, name=None, entity_type=None, limit=None, after=None)
neighbors(entity_id, tenant_id, *, depth=1, relationship_types=None)
get_relationships_for(entity_ids, tenant_id, *, direction='both', ...)
```

New `GraphReadPort` in `application/graph_read.py`, project-bound, wrapping those
three:

```python
class GraphReadPort(Protocol):
    async def find_entities(self, *, name=None, entity_type=None,
                            limit=100, after=None) -> EntityPage: ...
    async def neighborhood(self, entity_id, *, depth=1) -> Neighborhood: ...
```

`Neighborhood` carries both entities and the relationships among them, resolved
in one call via `get_relationships_for` over the returned set -- so the client
never has to issue N calls to learn how a returned neighborhood is wired.

Routes: `GET .../graph/entities`, `GET .../graph/entities/{eid}/neighborhood?depth=`.

**Depth is capped at 2** and the cap is enforced server-side. `neighbors` at depth
3 on a well-connected entity can return most of the graph, and a page that can ask
for it will eventually ask for it by accident.

**Why this is not on `KnowledgePort`.** That port is the agent's graph vocabulary
-- `ingest`, `search`, `undo_merge` -- and the same argument as `TopicPort`
applies. Traversal is a reader's operation. It also takes a `tenant_id` that the
project binding supplies, and threading that through the agent-facing port would
expose a parameter no tool should ever set.

## Rendering

`react-force-graph-2d`, Canvas 2D over d3-force, ~62 kB gzip.

It is a real React component -- `graphData`, `onNodeClick`, `nodeCanvasObject`,
imperative `zoomToFit` via ref -- which matters because the alternatives'
React bindings are dead (`react-cytoscapejs` last published 2022, peer
`react: >=15`) and would each mean an imperative adapter we write, own and test.
Sigma is smaller and streams better but is WebGL-only with no canvas fallback.
Cytoscape is the one to revisit if graph *algorithms* -- centrality, pathfinding
-- ever become product features rather than setup code.

**It is lazy-loaded into its own `graph-` chunk.** The console must not pay 62 kB
to render a session transcript. `React.lazy` at the pane boundary, `manualChunks`
in `vite.config.ts` to keep it out of `vendor-`.

`check-size.mjs` gets a `graph-` budget of 62 and a total raised from 180 to 242,
in the same commit that adds the dependency, with a message saying what was
bought. That file asks for exactly this and catches exactly its absence.

**Settling.** Appending nodes one at a time reheats the simulation on every
arrival and the graph never stops moving. Expansion batches its arrivals into one
`graphData` update, and nodes the user has focused are pinned with `fx`/`fy`.

---

# The frontend

New `src/presentation/research/`, mirroring `course/`. One `Route` variant in
`routing/routes.ts` with `parseRoute`/`researchHref`, one case in `CurrentView` in
`app/App.tsx`, one `styles/research.css` defining no colour of its own.

Pure logic goes in `domain/`, testable without rendering:

- `domain/research/topic.ts` -- `TopicView`, attention severity ordering, the
  predicate behind "needs attention", legal status transitions.
- `domain/knowledge/graph.ts` -- `GraphView` and `expand(view, neighborhood)`, the
  fold that merges an arriving neighborhood into the displayed graph without
  duplicating nodes or losing positions.

`expand` is the one with real subtlety and gets the same treatment `applyNote`
got: merge by id, keep existing node object identity so d3 retains `x`/`y`, and
use `??` rather than `||` so a genuine `0` survives.

Wire spellings stay confined to `infrastructure/http/mappers.ts`. New repositories
follow `HttpExtractionRepository`: `HttpTopicRepository`, `HttpGraphRepository`,
registered in `app/container.ts`.

# Testing

Red/green throughout, one vertical slice at a time.

Python: domain-level tests on each new port against an in-memory graph store and
a real event store, then route tests over the composed app. The three topic
commands get tests for the justification requirement specifically -- blank
justification rejected at the route, not merely at the aggregate.

TypeScript: `domain/` folds tested as pure functions; panes tested with
`@testing-library/react` following `ExtractionPane.test.tsx`; the force-graph
component itself is mocked at the module boundary, since asserting on canvas
pixels tests the library rather than our code.

# Order

Each slice is independently shippable and ends green.

1. `TopicReadPort` + list/detail routes + topics pane -- the largest gap, and the
   only one that is useful entirely on its own.
2. Topic management: three routes, the justification dialog.
3. Documents: virtualized list + reader over routes that already exist.
4. `GraphReadPort` + routes, tested with no UI at all.
5. The graph pane, the dependency, the budget bump.
6. Seeding, last -- it writes, and it is worth having the read surface that shows
   its output already working before turning it on.

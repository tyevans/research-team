# Data-bound components

Every component registered today is *self-contained*: `flashcards`, `mcq`,
`cloze` and `checklist` carry all their data in the YAML the model typed. That
is the right shape for an assessment item, whose content is authored. It is the
wrong shape for the corpus, which the model can only describe in prose no matter
how much of it the project already holds.

This adds a second class -- **resolved** components, which carry a *reference*
and fetch their data in the browser. The model writes what it means; the widget
shows what the project actually knows.

Five types: `definition`, `evidence`, `graph`, `timeline`, `compare`.

## 1. The problem that shapes everything else

**Entity ids are opaque UUIDs and a model cannot know them.**
`graph_reader.py:54` takes `entity_id=str(entity.id)` straight from redstring's
store. Nothing derives them from a name, and no uuid5 namespace covers entities
(the namespaces at `read_models.py:618,1465,1832` are for corpus, definition,
ontology and check rows). So an authoring model has no way to write a correct
`entity_id:` unless it is handed one.

The only name-facing route is `GET /graph/entities?name=`, and it is a
**substring, case-insensitive filter in Python** (`graph_reader.py:314`,
deliberately *not* the store's exact `find_entities(name=...)`, per the comment
at :283-297). So a name is a *search*, not a resolve: "Constantine" may match
one entity, five, or none.

Three ways out were considered:

- **Resolve at parse time on the server.** Rejected. `parse_document` is pure
  and synchronous, has no graph handle, and is called from the SSE hot path and
  from tests that construct no project. Giving it I/O would make every existing
  component's parse fallible for the benefit of five new ones.
- **Give the ask agent a lookup tool so it writes real ids.** Rejected for now.
  It is exact, and it is a whole extra round-trip per widget on the authoring
  turn, on a surface that streams. It also fails closed in the worst way: a
  model that cannot get an id writes no widget at all, and nobody sees why.
  Worth revisiting once the widgets earn their keep.
- **Reference by name, resolve in the browser, and make ambiguity a rendered
  state.** Chosen.

**The consequence is a design rule, not an implementation detail: a resolved
component has four render states, and "ambiguous" is a first-class one.**

| State | Cause | Renders |
|---|---|---|
| resolved | exactly one match | the widget |
| ambiguous | 2+ matches | the reference, plus a picker listing candidates with their `entity_type` |
| missing | 0 matches | the reference as plain text, with a quiet "not in this project's graph" note |
| unavailable | 503 / no project in scope | the reference as plain text, nothing else |

`missing` and `unavailable` must degrade to *readable prose*, never to an error
panel. A model writing about an entity the extraction pipeline has not reached
yet is normal, not a defect, and an answer that renders a red box for it is
worse than one that renders a word.

`entity_id:` remains accepted on every reference as an escape hatch, because a
human editing a lesson file *can* copy one out of the console, and because it is
the only way to pin a genuinely ambiguous name.

## 2. Registry changes

`ComponentType` gains one field:

```python
resolved: bool = False
"""This component carries a reference and fetches its data in the browser.

Structurally it is the inverse of `gradeable`: nothing is withheld (there is
no answer key -- the data is the project's own), nothing is graded, and the
YAML body is a *query*, not content. The flag exists so the projection, the
prompt and the client can all tell the two classes apart without a name list.
"""
```

Resolved components set `withheld=()` and `gradeable=False`. `project()` passes
their body through unchanged in both views: there is nothing to strip, and the
author/learner distinction is meaningless for a reference. This is worth
asserting in a test, because "the learner projection is identity" is exactly the
kind of property that silently stops holding when someone adds a `strip`.

Validation stays pure and shape-only. **The registry cannot check that a
referenced entity exists**, and must not pretend to: `validation_report` runs on
the server at parse time with no graph, so a name that matches nothing is a
*render* state, not a parse error. Stated here because the natural instinct is
to add an existence check to the validator, and it cannot be written honestly.

`ASK_COMPONENT_TYPES` (`ask_components.py:24`) gains all five. Unlike
`checklist`, they are wanted in an ask -- an ask is precisely where a reader
asks about the corpus.

Prompt guidance (`craft`) for each type has one job beyond syntax: **tell the
model to write the entity name exactly as the prose does**, and that a widget
whose reference misses renders as nothing. The failure mode this format produces
is a model inventing a tidy canonical name ("Constantine I") for an entity the
extraction stored as it appeared ("Constantine").

## 3. The client contract

`RENDERERS` (`LessonDocument.tsx:82`) currently hands each renderer
`{block, attempts}`. Resolved components need the project, so the signature
becomes `{block, attempts, projectId?}` and `LessonDocument` threads its
existing optional `projectId` through.

`projectId` is optional for the reason already written at
`LessonDocument.tsx:48`: a lesson file is read from a session, which has no
project in scope. **A resolved component with no `projectId` renders the
`unavailable` state.** That is a real case -- a course file can contain a
`definition` widget and be read outside any project -- and it degrades to prose,
which is the same answer as every other failure here.

Two pieces of shared machinery, both new, both in
`frontend/src/presentation/lesson/`:

- **`useEntityReference(projectId, ref)`** (`application/lesson/`) -- takes
  `{entity?: string, entity_id?: string}`, returns a discriminated union over
  the four states above. `entity_id` short-circuits the search. Backed by
  TanStack Query (the repositories are already there: `graph-repository.ts:8`
  `search`/`neighborhood`, `definitions-repository.ts:8`). Deliberately *not*
  the Zustand graph store (`graph-store.ts:85`) -- that store is per-project
  console state with selection and expansion in it, and a widget wants a cached
  read, not a share in someone else's cursor.
- **`<ResolvedFrame>`** -- renders the ambiguous/missing/unavailable states
  uniformly so five widgets cannot drift into five different ways of saying
  "not found", and yields to a child render prop once resolved.

Because these mount inside an ask turn, a QueryClient and the DI container must
be in scope there. `AskTurnWidgets` already mounts under both; a browser test
pins it, because the failure if it is not is a thrown hook, which takes the
whole answer down rather than one block.

## 4. The five components

### `definition`

```component:definition
entity: Nicene Christianity
```

The smallest one, and first for that reason: `useDefinition` already exists
(`use-definition.ts:27`) and `GET .../definition` is synchronous with a
documented `text: null` for "undefinable" rather than a 404 (`app.py:2447`).
Renders the definition text plus its citations, which are `{source_id, start,
end}` and therefore expand through the same source machinery `evidence` needs.

`text: null` is a fifth state, distinct from `missing`: the entity exists and
the project cannot define it. It renders as the name with a note saying so. Not
folded into `missing`, because the two say opposite things about the corpus.

### `evidence`

```component:evidence
claim: |
  Theodosius made Nicene Christianity the state religion in AD 380.
sources:
  - source: <source_id>
    start: 4120
    end: 4380
```

Claim beside the actual passages it rests on. `GET /sources/{sid}?start&end`
takes the range and clamps rather than 422s (`app.py:1635`), returning the
offsets it actually served -- so the widget shows the excerpt the reader can
check, and a bad range degrades to a nearby one rather than an error.

This is the one that most changes what an ask *is*, and it is also the one whose
reference the model is most able to get right, because source ids are already in
its context via `[[src:...]]`. It therefore takes ids directly, with no name
resolution: `references.ts` already proves the model handles this shape.

Cost, stated plainly: a model can write a `claim` the excerpt does not support.
The widget makes that *visible* rather than preventing it, which is the whole
point -- prose can do the same thing today and nothing shows the reader.

### `graph`

```component:graph
entity: Constantine
depth: 1
```

The neighbourhood subgraph. `GET .../neighborhood?depth=` 404s on an unknown id
and 422s past `MAX_NEIGHBORHOOD_DEPTH` (`app.py:2364`), so `depth` is validated
in the registry against the same bound rather than discovered at fetch time.

Reuses `GraphCanvas` (`GraphCanvas.tsx:52`, `{view, selected, onNodeClick}`,
memoized and self-measuring) rather than `GraphBrowser`, whose props are a
console's worth of search and filter state. The neighborhood response has to
pass through `mappers.ts`/`graph.ts` to become a `GraphView`.

Sizing is the open risk: `GraphCanvas` measures its container via ResizeObserver
and a markdown flow gives it no height. The widget sets an explicit aspect-ratio
box, and this needs a **browser test**, not a jsdom one -- per CLAUDE.md, a
measurement is exactly what jsdom cannot judge.

### `timeline`

```component:timeline
entity_type: Person
from: "0300-01-01"
to: "0400-01-01"
```

**Not entity-scoped, and the syntax must not imply it is.**
`GET /timeline` takes `entity_type`, `from`, `to`, `limit` and has *no* topic or
entity filter (`app.py:2629`). So this component filters by type and range only.
Writing `entity:` here would be a field that silently does nothing, which is
worse than the capability being absent.

Reuses `TimelineCanvas` (`TimelineCanvas.tsx:89`, `{bands, selected, onSelect}`,
pure SVG with its own zoom/pan). `timeline-repository.ts:8` currently passes
only `entityType` through and must be widened to carry `from`/`to`/`limit`.

The response carries `undated_count` and `truncated`; both are rendered. A
timeline that quietly drops two thirds of its bands is the read-model failure
this project has already had once, and the counts are the only thing that shows
it.

### `compare`

```component:compare
entities: [Diocletian, Constantine]
rows:
  - label: Reign
  - label: Religious policy
```

**Columns are author-declared, and this is a constraint discovered, not a
choice.** The natural design fills a table from per-type properties, and
`GET /ontology` (`app.py:2535`) does not have them: a class's `members` are
`{name, ordinal}` strings, with no attribute schema anywhere. There is nothing
to derive columns from.

So `compare` resolves each named entity (linking it, and showing its
`entity_type`), and the model writes the row labels and cell prose itself. The
resolution is what it adds over a markdown table: every column head is a real
entity or is visibly not one.

Lowest value of the five and last in order for that reason. It is included
because the resolution machinery is already paid for by the other four.

## 5. Testing

Per CLAUDE.md's four gates, and one line that matters more than the rest:
`research_team/interfaces/web/static` is a committed build artefact, so every
frontend change here ends with `cd frontend && npm run build` and a commit of
the rebuilt `assets/`.

- **Python**: registry shape per type; `project()` is identity for resolved
  types in both views; `validation_report` accepts a reference that cannot
  possibly exist (the honest assertion -- see §2); `ASK_COMPONENT_TYPES`
  includes all five; the generated `component_reference` renders each example.
- **jsdom**: each of the four (five, for `definition`) render states, from a
  faked repository. Roles, text and links.
- **Browser** (`*.browser.test.tsx`, `npm run test:browser`): the `graph` and
  `timeline` widgets have a non-zero measured height inside a markdown flow.
  This is the assertion jsdom writes as a comment, and the reason the suite
  exists.
- **The fixture trap** (CLAUDE.md, "Read models"): at least one test per widget
  must start from a project the fixture has *not* already opened, or a dropped
  `graphs.open` is invisible -- which is precisely how the definitions work shipped
  a once-per-project 503.

## 6. Out of scope, deliberately

- **Inline components.** `widget-horizons.md` §5.2 records that only block-level
  fences exist. A `definition` widget wants to be inline more than any other
  type here, and making it so is a markdown-pipeline change, not a widget.
- **`explorer`** (a reader-reparameterisable query) -- needs a safe query
  surface that does not exist. Its own spec.
- **`socratic`** -- decided to be its own experience rather than a widget, and
  it needs per-occurrence state that no ask has (BACKLOG B33).
- **Recording attempts.** Resolved components are not gradeable; nothing posts.

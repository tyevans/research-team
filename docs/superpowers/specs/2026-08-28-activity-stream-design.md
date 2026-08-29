# The activity stream as a document

Every tool result in the console renders as the string the model reads. That
string is written for a model — dense, addressed, and deliberately unpunctuated
— and putting it on screen unchanged produces the wall of text this design
replaces. This document specifies what the stream renders instead, where the
data for it comes from, and what holds the two halves together.

## The defect, stated exactly

`ActivityFeed.tsx` is 26 lines. Every provisional entry renders as
`<div className="provisional-body">{activityBody(entry)}</div>`, and
`activityBody` returns one flat string. `Conversation`/`Segments` do the
equivalent for committed messages. So a `search_sources` answer — 19 matches,
each with a source id, a character range and a snippet — arrives as a paragraph
in which the reader cannot find a match boundary, and the ranges that make each
hit quotable are indistinguishable from the prose around them.

None of that is a rendering bug. `format_matches` in `corpus_tools.py` builds
exactly one line per hit and the newlines survive to the browser; the console
collapses them, and would still have nothing to lay out if it did not. The
information the reader needs — which document holds the weight, where in it,
which entities came back unlinked — is not absent from the string. It is
present and unaddressable, because a string is not a structure.

Three consequences worth naming, because each is a defect the current rendering
cannot show:

- `0 relationship(s)` on a `graph_search` result means an entity the graph knows
  by name and has connected to nothing. It is the most actionable fact the tool
  returns and it is invisible in the paragraph.
- `read_source` reports `@1529-3872 of 25784`. An agent quoting 9% of a document
  from near its start is making a materially different claim than one that read
  the whole thing, and nothing on screen distinguishes them.
- `IN PROGRESS — NOT YET RECORDED` is printed on every provisional card. Repeated
  once per card it stops being read at all, which is the opposite of what a
  provisional marker is for.

## The seam: tool artifacts

Structure comes from the tools themselves, as a second return value.

LangChain's `ToolMessage` carries `artifact` and `name` alongside `content`, and
this project stores messages as `message_to_dict(...)` whole (`messages.py`), so
an artifact is persisted, replayed and broadcast with no new event type and no
schema change. `activity.py` announces `note.payload` entire; `message_view` in
`presenters.py` currently drops both fields on the floor.

Each converted tool becomes `response_format="content_and_artifact"` and returns
`(existing_string, artifact)`. **The strings do not change.** The model's input
is byte-identical after this work, so no prompt, checkpoint, eval or extraction
behaviour moves — the artifact is additive and invisible to the agent.

### Rejected: parsing the strings

The obvious cheap alternative is to parse `format_matches`' output in the client
or the presenter. It is rejected for the reason CLAUDE.md already documents three
times under *Checkpoints over model output*: an assertion over text formatted
elsewhere is half a contract, and the half that goes missing goes missing
silently. Here the failure would be a tool adjusting its wording and every card
of that shape rendering empty, with four green gates. The artifact is the tool
handing over what it already computed, so there is nothing to guess at.

The cost of artifacts, stated: every converted tool's return type changes, and
messages written before this work carry no artifact. Both are handled by the
fallback below, which is needed regardless.

### Shape, not tool

Seventeen tools map onto **seven shapes**. A shape is a visual grammar the reader
learns once:

| Shape | Tools |
|---|---|
| `hit_list` | `search_sources`, `search` |
| `entity_list` | `graph_search`, `graph_describe` |
| `excerpt` | `read_source`, `fetch` |
| `inventory` | `list_sources`, `list_topics`, `open_topic` |
| `acknowledgement` | `remember`, `remember_page`, `record_finding`, `record_gap`, `link_source`, `unmerge` |
| `file_change` | `write_file`, `edit_file` |
| `delegation` | `ask_agent`, subagent fan-out |

Per-tool renderers were rejected: seventeen novelties do not compose into a
document, a new tool would inherit nothing, and seventeen renderers must be kept
in step with seventeen formatters — the maintenance shape that has already gone
wrong here for checkpoints.

### Wire format

`research_team/application/tool_artifacts.py`, new. A frozen dataclass per shape,
each with `as_artifact() -> dict`, each dict carrying `shape` and `version: 1`.

```python
{"shape": "hit_list", "version": 1,
 "pattern": "magic", "total": 19, "shown": 19, "suppressed": 0,
 "sources": [{"source_id": "…", "title": "manuscriptreport.com",
              "label": "types of fictional genres", "char_count": 25784,
              "hits": [{"start": 1529, "end": 1694, "snippet": "…"}]}]}
```

The other six are specified in the implementation plan. Three rules hold across
all of them:

- **Every field the renderer draws is on the artifact.** A renderer that has to
  recompute something from the string has re-created the seam this removes.
- **Positions travel as offsets and totals, never as percentages.** The bar
  widths are the renderer's business, and a percentage on the wire cannot be
  turned back into the range a citation needs.
- **`version` is present from the first commit.** Not because a migration is
  planned — the project is pre-release and breaks data freely — but so that a
  reader of an old event can tell "no artifact" from "an artifact I do not
  understand", which are different fallbacks.

### The fallback is a first-class path

`artifactOf(message)` returns the parsed union or `null`. `null` renders today's
text, unchanged. This is not degradation handling bolted on; it is the permanent
path for every historical message, every unconverted tool, and every tool a
future contributor adds and forgets. It must therefore be tested as a path, not
as an error case.

## What it renders

The reference is `docs/superpowers/specs/assets/2026-08-28-activity-stream-reference.html`,
approved 2026-08-28. Read it alongside this section.

### The spine

One vertical rule down the stream, a glyph per row, the body indented behind it.
The glyph for a shape is the same glyph its call carried, so a call and its
result read as a pair while scrolling.

The spine replaces per-card borders. A border around content already indented
behind a rule draws the same boundary twice, and the doubled chrome is most of
what makes the current feed feel heavy.

### Prose and machinery are typographically separate

Conversation prose is serif, full width. Tool traffic is monospace, indented
behind the spine, smaller. This is the load-bearing decision of the whole design:
it lets a reader follow the actual answer straight down the page and let the
machinery blur. Today the two are identical, which is why a turn with nine tool
calls reads as nine paragraphs of noise with an answer somewhere in it.

### One tool use is one row

Header line: `tool_name · argument · count`. The call and its result are one row,
not two. The argument shown is the source's **title**, resolved from the artifact
— `manuscriptreport.com · types of fictional genres`, not
`manuscriptreport-com-blog-types-of-fictional-genres-42e281d8`. The raw id stays
available on the expander and in the DOM `title`, because it is what a bug report
needs.

### Lists stay lists, capped at five

Every list is one item per line with a shared three-column alignment: name, bar,
value.

**A multi-column grid was tried and rejected**, and the reason belongs in the
code: in a grid each column carries its own bar baseline, so two bars side by
side are *not* on a common scale, and the layout invites a comparison that is
wrong. A single column puts every bar on one axis, which is the only reason to
draw a bar at all.

The height a single column costs is bought back with a cap of five items and an
expander. The cap does a second job: a 40-match result cannot bury the reply
beneath it.

### Density earns its ink

- `hit_list` — a sparkline per source showing *where* in that document the
  matches fell, then a count. One representative snippet below the rule. The
  card answers "where does this live in my corpus" before "what does it say".
- `entity_list` — sorted by relationship count, bar per entity. **Unlinked
  entities sit below a rule with `–` rather than `0`**, because the current
  rendering makes the graph's most actionable gap the least visible thing on it.
- `excerpt` — an inline ruler showing which span of the document was read,
  against its full length, with the range in the header.
- `acknowledgement` — one line, no chrome, no expander. These are the stream's
  punctuation. Giving a write the same weight as a search result is what makes a
  feed read as noise.
- `file_change` — proportion of the file touched as a bar, then the actual
  before/after. Today it is a summary string with each side cut to 30 characters.
- `delegation` — wall-clock bars per worker against the turn, so a fan-out that
  silently serialised looks wrong at a glance.

### Phase is position, not a banner

`IN PROGRESS — NOT YET RECORDED` is deleted as a per-card label. Provisional
state is carried by the live edge: a pulse on the row's glyph, a warmer border,
and a shimmer where prose is still arriving. Everything above the live edge is
settled by virtue of being above it.

The three phases and what differs:

| Phase | Treatment |
|---|---|
| In flight | Pulse on the glyph, warm accent, shimmer under streaming prose. Counts may be partial. |
| Committed | Settled. Identical layout to in-flight — this is what stops a card from visibly changing as the turn commits. |
| Historical (scrubbed) | Identical to committed. The scrub position is the pane's state, already shown by `ScrubBar`; repeating it per row would be the banner defect again. |

The in-flight and committed renderings must be **the same component with a
`phase` prop**, not two components that agree. Two components that agree are two
components that will stop agreeing.

## Structure

```
research_team/application/tool_artifacts.py     new — dataclasses + as_artifact()
research_team/infrastructure/agent/
    corpus_tools.py, knowledge_tools.py,        return (text, artifact)
    search.py, topic_tools.py, fetch.py
research_team/interfaces/web/presenters.py      message_view passes name + artifact

frontend/src/domain/conversation/artifact.ts    new — parse to a discriminated union
frontend/src/presentation/session/shapes/       new — one component per shape
    ToolResult.tsx                              dispatcher: (message, phase)
    HitList.tsx EntityList.tsx Excerpt.tsx
    Inventory.tsx Acknowledgement.tsx
    FileChange.tsx Delegation.tsx
frontend/src/styles/stream.css                  new — spine, phases, shapes
```

`ActivityFeed` and `Segments` both render through `ToolResult`. Neither knows a
shape.

### Styling constraints this repo has already paid for

Read `CLAUDE.md` before writing a line of CSS here. Three of its entries bear
directly on this work:

- **Unlayered element selectors in `tokens.css` beat every utility.** `button`,
  `input`, `textarea` and `select` carry an unlayered background, colour and
  `font: inherit`. The expanders in these cards are `<button>`s. A `text-xs` or
  `bg-transparent` utility on them is inert, and it looks exactly like one that
  worked. `control-defaults.browser.test.tsx` is the standing measurement.
- **`border-solid` beside a directional width draws three unwanted sides**, and
  `border-0 border` is a conflict rather than a fix. The spine is a directional
  border; get it right the first time.
- **jsdom lays nothing out.** Every assertion in this design that is a
  measurement — the spine reaching between rows, a bar's width tracking its
  value, the live edge differing from a settled row, an expander's real computed
  size — belongs in a `.browser.test.tsx`. A jsdom test asserting these is a
  comment with a green tick beside it.

## Verification

Four gates, all of them: `ruff check .`, `ruff format --check .`, `pytest`, and
`cd frontend && npm run verify`. Plus `npm run test:browser`, which is not a gate
and is mandatory here — this design's correctness is substantially computed
styles and measurements.

Three tests carry the design, and each exists because of a failure this
repository has already had:

1. **`test_every_artifact_shape_is_produced_by_a_real_tool_call`** — parametrised
   over the shape registry, drives the *real* tool against a *real* seeded
   corpus/graph, and asserts a non-empty artifact of the expected shape. This is
   the *port with one adapter* rule: the co-mention channel shipped, was fully
   unit-tested from both sides, and produced nothing for a whole feature because
   nothing drove the real writer into the real reader. A renderer test fed a
   hand-written literal cannot detect a tool that never populates its artifact.

2. **`test_the_shape_registry_covers_every_artifact_producing_tool`** — derives
   coverage by introspection, so an eighth shape or a newly-converted tool fails
   at collection rather than rendering as a permanent fallback nobody notices. A
   hand-written list is documentation; the test is the contract.

3. **`a-card-does-not-change-when-its-turn-commits.browser.test.tsx`** — renders
   one artifact in both phases and asserts the layout geometry is identical.
   This is the property the whole "phase is position" decision rests on, and it
   is a measurement, so it is a browser test.

Two further requirements, both from CLAUDE.md:

- **Run it against a database that predates this change.** Use
  `python -m research_team.infrastructure.persistence.local_copy`. Old messages
  have no artifact; the fallback path must be seen working over real history, not
  only over a fixture.
- **Prove each test red before trusting it green**, and where a test would pass
  with the change reverted, say so in its docstring instead of leaving it as
  reassurance.

## Deliberately not in scope

- Clicking a hit to open `read_source` at its offsets. The artifact carries the
  offsets, so this becomes possible; it is a separate change with its own
  navigation questions.
- Changing what any tool returns to the model.
- The remaining console reworks on the roadmap.

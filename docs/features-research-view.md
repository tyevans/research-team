# The research view: an exhaustive feature index

Read out of a clean worktree at `origin/main` = `5a5a7cf` ("Move what-is-running
into the nav bar (#86)"). Every claim below was read out of the code, not the
docs; where an in-tree comment and the code disagree, that is called out
explicitly under **Comment vs code**.

> **Historical, 2026-08-27 (B147).** This is a survey taken at a named commit,
> and the workflow system it surveys has since been removed entirely: presets,
> stages, stage artifacts, the check library and every surface that drew them.
> Banner rather than rewrite, deliberately. The body's whole claim is "read out
> of the code at `5a5a7cf`", every entry is dated to that read, and editing
> entries out would leave a document asserting a provenance it no longer has --
> a survey that has been quietly corrected is less useful than one that says
> when it was taken. **What is invalid:** the `Course` button's disabled-when-no-workflow behaviour, and the course page it led to. "Rail + stage" and "floats on the stage" are layout vocabulary and are unaffected.

Vocabulary used throughout:

- **Built** — reachable by a user today.
- **Built but unreachable** — the data or the port exists and is fetched, but
  nothing in the UI renders or exposes it.
- **Designed, unimplemented** — named in `docs/design/topic-dispatch.md` or
  `BACKLOG.md`, no code.
- **Unsure** — stated as unsure, not asserted.

---

## 0. Shape of the page

`frontend/src/presentation/research/ResearchView.tsx` — a markup-only
component. Route `#/p/<projectId>/research[/entity/<entityId>]`, parsed in
`frontend/src/presentation/routing/routes.ts` (`Route` variant `research`),
rendered from `frontend/src/app/App.tsx:118-131`.

Layout is a **rail + stage**, not a 2x2 grid:

```
view-head:  "Research"                     [Course]  (btn-quiet link)
research-workbench:
  research-rail (left column, ~320-340px)   pane-graph (stage, fills viewport)
    RailPane "Seeding"    -> SeedPanel        GraphPane
    RailPane "Topics"     -> TopicList
    RailPane "Documents"  -> DocumentList
```

The page itself does not scroll; each region scrolls independently. Styles in
`frontend/src/styles/research.css`.

### F0.1 Reaching the research view — **built**

Four entry points, all plain links/buttons:

| Where | File | Control |
|---|---|---|
| Landing page project row | `presentation/tree/ProjectList.tsx:457` | `Research` button (never disabled; unlike `Course`, which disables when the project has no workflow) |
| Course page head | `presentation/course/CourseView.tsx:67` | `Research` quiet link |
| Session transcript breadcrumb | `presentation/shell/Breadcrumbs.tsx:87` | `research` crumb, only when the session knows its `projectId` |
| Direct URL / paste | `routing/routes.ts:128` `researchHref` | hash URL, incl. `/entity/<id>` deep link |

Dependencies: a `ProjectId` only. The view itself never checks the project
exists — every child query does, and each fails separately (see §7).

### F0.2 Leaving it — **built**

One control: the `Course` quiet link in the view head (`ResearchView.tsx:54`).
There is **no** link from the research view to the holding session, to a
worker, or back to the landing page except through the browser's own chrome.
(The `Course` page offers "Open holding session"; research does not.)

### F0.3 The graph selection lives in the URL — **built**

`App.tsx:130` navigates with `{ replace: true }` on every entity change. The
comment states why: browsing a graph *grows* it, so a back button restoring a
previous entity could not un-draw what that click added. Consequence a redesign
should know: **the back button never steps back through graph browsing**; it
leaves the research view entirely.

---

## 1. The rail chrome

### F1.1 Fold/unfold a rail pane — **built**

`presentation/research/RailPane.tsx`.

- **What**: each of the three rail panes collapses to its title bar.
- **Control**: a ghost button showing `▾` / `▸` in the pane head, with
  `aria-expanded` and an `aria-label`/`title` of "Fold X away" / "Expand X".
- **Depends on**: the `preferences` port (`collapsedPanes('research')` /
  `setCollapsedPanes`) — persisted, so folding survives a reload. The group key
  is `'research'`, separate from the session view's stored layout.
- **State model**: folding **unmounts** the body (not `display:none`) so the
  document virtualizer does not measure a zero-height scroller. Cost, stated in
  the comment: expanding re-renders from the query cache and refetches if the
  entry is stale.
- **Rough edge**: unlike the session view, there is no "at least one must stay
  open" rule — all three can be folded at once, leaving the rail as three bare
  headers. That is deliberate (the heads stay reachable), but it means a user
  can reach a state where the rail shows no content at all.
- **Keyboard**: normal tab-and-enter only; no shortcut.

---

## 2. Seeding (`SeedPanel.tsx`)

### F2.1 Seed topics from a subject — **built**

- **What**: type a subject, press one button, and the server runs one model
  turn that names up to 8 topics and opens them into the queue.
- **Where**: `presentation/research/SeedPanel.tsx`.
- **Control**: a labelled `Subject` text input (placeholder "spaced repetition
  and memory consolidation") plus an accent `Seed topics` submit button. It is
  a real `<form>`, so **Enter in the field submits**.
- **Depends on**: `POST /api/projects/{id}/topics/seed` with
  `{subject, max_topics: 8}`. `MAX_TOPICS = 8` is hardcoded in the component to
  match the server's `NewSeed.max_topics` default — **the user cannot change
  it** (§9.6).
- **State model**:
  - *Idle*: empty box, button enabled once the trimmed subject is non-empty.
  - *Submitting/running*: the input is `disabled`, the button reads `Seeding…`,
    and a `role="status"` line says `Naming topics for "<subject>"…`.
  - *Running, picked up from another tab*: the running frame carries no
    subject (`SeedingActivity.start` mints it before the model names one), so
    the line degrades to `Naming topics…`.
  - *Failed*: `The last seed failed: <detail>` in `.seed-failed`.
  - *Done*: `Last seed opened topics for "<subject>"`, or
    `"an earlier subject"` when the wire had no subject.
  - *409 (a seed already running)*: surfaced as a **toast**, `tone: 'bad'`, via
    `notify(errorMessage(error))` — not inline in the panel.
- **Live behaviour**: `useQuery(queryKeys.seed)` on mount; a `seeding` frame
  for this project writes straight into the cache (`running` → `current`,
  anything else → `last`); `stream.onReconnect` invalidates, because a seeding
  frame carries no feed position and `Last-Event-ID` cannot replay it.
- **What it deliberately does not do**: nothing here reads the topics a run
  opened — `open_topic` appends to the log, so `TopicList`'s own `topic`-frame
  refresh picks them up.

### F2.2 `SeedingRun.reply` — **built but unreachable**

`domain/research/seeding.ts` carries `reply` ("the model's own account of what
it did"), mapped from the wire, and **no component renders it**. A user who
seeds gets a count of topics appearing in the list below and never sees the
model's rationale.

---

## 3. The topic queue (`TopicList.tsx`)

The densest surface on the page. Ten distinct features.

### F3.1 The ranked queue — **built**

- **What**: every topic in the project, one row each, sorted by
  `byUrgency` (`domain/research/topic.ts:130`): blocked first, then
  `needsAttention`, then anything live, then closed, ties broken by question
  text (deliberately, so rows do not swap on every refetch).
- **Row contents**: the question; then a meta line of status (with `_` replaced
  by a space), `N sources`, `N findings`, and `N open` (only when
  `openSubQuestions > 0`); then a dispatch chip if any; then the topic's
  `triggers` as a list.
- **Row classes**: `topic-blocked` / `topic-attention` / `topic-closed` /
  plain, in that precedence.
- **Depends on**: `GET /api/projects/{id}/topics`.

### F3.2 Free-text filter — **built**

`<input type="search">`, `aria-label="Filter topics"`, placeholder "Filter
topics". `matchesTopic` matches against the **question and the triggers** —
searching "contested" finds topics flagged for that reason, which matching the
question alone would not. Case-insensitive, trimmed, substring.

### F3.3 Focus slices — **built**

A `role="radiogroup"` labelled "Which topics to show" with four
`role="radio"` buttons: `All`, `Needs you`, `Live`, `Closed`. Each carries a
count computed over the **whole** queue, not the filtered slice, so an empty
slice announces itself before it is picked. `attention` deliberately spans both
`isBlocked` and `needsAttention`. Default is `all`.

### F3.4 Dispatch one topic ("Write understanding") — **built**

- **What**: sends an agent at the topic; it joins the project, runs one turn,
  writes `understanding.md` into the topic's directory, and releases.
- **Control**: a small `Write understanding` button on every row.
- **Depends on**: `POST /api/projects/{id}/topics/{topicId}/dispatch` with
  `{action: 'understanding'}`, answering **202** (never 409 — it queues).
- **Disabled when**: `hasNothingToSynthesise` (`sources === 0 && findings === 0`),
  or a dispatch is already being submitted, or this topic's dispatch is
  `queued`. Title text changes to "Nothing gathered for this topic yet".
  This is explicitly the *only* disabled control in the feature, to prevent
  confabulation presented as a deliverable.
- **Comment vs code**: the comment says it "becomes a split button when
  `research` and `lesson` land". Server-side `DISPATCH_ACTIONS` is
  `frozenset({"understanding"})` — one action, confirmed. The UI sends a
  hardcoded string; a server that grew `lesson` would still show only this
  button.

### F3.5 Dispatch status chips — **built**

`DispatchChip` renders per row from `useDispatchBoard`:

| Status | Renders |
|---|---|
| queued | `⧗ queued · 1st` (ordinal, recomputed server-side per read) or `· waiting` when `position` is null |
| running | `⟳ understanding · running` |
| failed | `✕ understanding · failed · <detail>`, clamped to one line, full text in `title` |
| cancelled | `⊘ understanding · cancelled` |
| done | `✓ understanding · <path>` (or `written` if no path) |

Finished chips are **kept, not cleared** — deliberately, so the button does not
look like it did nothing. `byTopic` is last-write-wins with the caller ordering
`finished, queued, running`, so a re-dispatched topic shows the current one.

### F3.6 The dispatch bar and project-wide Stop — **built**

Appears above the list only when something is running or queued. Reads
`1 running, 2 queued` (or `none running, 2 queued`) plus one small `Stop`
button, titled "Stop the running dispatch and drop everything queued".

- **Depends on**: `POST /api/projects/{id}/dispatch/cancel`, which answers
  `{cancelled: N}`.
- **Note**: the returned count is **discarded** — the UI never says "stopped 3",
  even though the route exists to make that sayable. The route's own docstring
  says the count is there for exactly that.
- **Deliberate absence**: no per-row cancel, because cancel is per project on
  the server and a per-row control would offer an action it cannot honour. The
  design doc (§8 "Three at once") sketches per-row `[cancel]`; that is
  **designed, unimplemented** and would need a server change.

### F3.7 Manage → the topic dialog — **built**

A small `Manage` button per row sets `managing`, which fires a second query
(`GET /api/projects/{id}/topics/{topicId}`). The dialog renders **only once
the detail has loaded** — so a click on Manage produces no visible feedback at
all until the request lands. On a slow read this looks like a dead button.

### F3.8 Live refresh off the feed — **built**

`useTopicRefresh` via `useFrameRefresh` (400 ms debounce, `FRAME_DEBOUNCE_MS`):
any `topic` frame invalidates `queryKeys.topics(projectId)`, and
`queryKeys.topic(projectId, managing)` if a dialog is open. Deliberately
scoped to two keys — the graph, documents and seeding panes are left alone.

**A known cost, written down in the code**: a topic frame carries no project
id (`topic_change` in `presenters.py` only knows one on the creation event), so
**another project's topic moving refetches this project's list**. Harmless, but
a redesign should know the frame is not project-addressed.

### F3.9 State model

- *Loading*: `loading topics…` (`Loading`), replacing the whole pane — the
  filters and the dispatch bar are not rendered.
- *Error*: `ErrorBox` "Could not read this project's topics" + message + a
  `Retry` button.
- *Empty (no topics at all)*: `EmptyState` — "No topics" / "Nothing has been
  seeded into this queue yet."
- *Empty (filter hides everything)*: a distinct `EmptyState` — "No topics
  match" / "Widen it to see the rest of the queue."

### F3.10 Fields fetched and never shown — **built but unreachable**

`TopicView` has everything the row uses. `TopicDetail` additionally carries
`rationale`, `scope`, `sourceIds`, `findingNotes` and `contested` — all mapped
from the wire in `infrastructure/http/mappers.ts`, all fetched by the Manage
dialog, and **none rendered anywhere in `presentation/`** (verified by grep).

**Comment vs code**: `TopicList.tsx:41` says the detail is fetched fresh
"because the row's `TopicView` leaves out the rationale, scope and
sub-questions the dialog needs". The dialog needs and renders the
sub-questions; it renders neither the rationale nor the scope. The comment
overstates what is built.

Notably `contested` — the flag `BACKLOG.md` B23 is entirely about — reaches the
browser and is invisible. A topic's *findings* (the prose in `findingNotes`) is
the single largest piece of research output the view refuses to show.

---

## 4. The topic dialog (`TopicStatusDialog.tsx`)

A non-drawer modal: `.drawer-backdrop` + `.drawer.topic-dialog`,
`role="dialog"`, `aria-modal="true"`, `aria-label="Manage <question>"`.

### F4.1 Change a topic's status — **built**

- **Control**: a row of `aria-pressed` toggle buttons, one per status, from
  `['open','investigating','answered','not_pursuing','superseded']` **minus the
  topic's current status** (a no-op transition 409s in the domain, so the
  control simply is not offered).
- Above them, a line: `Currently <status>`, plus
  `-- reopening is allowed.` when the current status is closed.
- **Justification is mandatory**: a labelled `<textarea>` (placeholder "why
  this change"). `Save` is disabled until a status is chosen *and* the trimmed
  justification is non-empty. The aggregate 422s on blank/whitespace, and the
  UI mirrors that rather than round-tripping.
- **Depends on**: `POST .../topics/{id}/status` with `{to_status, justification}`.
- **On success**: invalidates both `topic` and `topics` keys and closes.
- **On error**: toast, `tone: 'bad'`. The dialog stays open.
- **Human-only by design** (route docstring): there is no agent tool for this
  and the docstring says none should be added.

### F4.2 Keyboard contract — **built**

Focus moves to the `Close` button on open and is restored to the
previously-focused element on close (re-checked for DOM membership first).
`Escape` closes. `Tab`/`Shift+Tab` are trapped, with `FOCUSABLE_SELECTOR`
re-queried **on every keypress** because adding a sub-question grows the
dialog. Clicking the backdrop closes it; clicks inside stop propagation.

### F4.3 Sub-questions (`SubQuestions.tsx`) — **built**

- **List**: every sub-question with its text; resolved ones show their answer
  and carry `.sub-question-resolved`; unresolved ones show an inline `Answer`
  field and a `Resolve` button.
- **Add**: two labelled inputs — `Key` ("a short slug") and `Question` ("what
  is being asked") — plus an `Add` button, disabled until both are non-blank.
- **Depends on**: `POST .../sub-questions` and
  `POST .../sub-questions/{key}/resolve`. Both human-only routes.
- **State**: `Adding…` / `Resolving…` on the buttons; errors are toasts.
  Both mutations invalidate the `topic` and `topics` keys so the row's
  "N open" count follows.
- **Rough edge**: the user must invent the `key` slug by hand. There is no
  generation, no validation, no uniqueness feedback beyond a server error in a
  toast, and no way to **delete** or **edit** a sub-question or to **unresolve**
  one — the domain has `AddSubQuestion` and `ResolveSubQuestion` and nothing
  else.

### F4.4 Documents written about this topic (`TopicDocuments.tsx`) — **built**

The section that makes dispatch output findable at all.

- **What**: lists the markdown files a dispatch wrote for this topic and
  renders the selected one inline in the dialog.
- **Control**: a row of `aria-pressed` tab buttons, one per document, toggling
  open/closed (clicking the open one closes it).
- **Depends on**: `GET .../topics/{topicId}/documents`, which answers
  `{directory, sessionId, at, documents[]}`. The `(sessionId, at)` pair is
  load-bearing: everything below it reuses the **session-keyed** readers
  unchanged — `useLesson(sessionId, path, 'author', at, true)`,
  `useAttempts`, and `workspace.readFile`.
- **Rendering**: if the parsed lesson `interactive && doc`, it renders through
  `LessonDocument` with attempts; otherwise plain `Markdown`. The audience is
  **always `'author'`** here — answers are not withheld, deliberately, because
  this pane is the person who asked for the document. A learner reads through
  the session route, which has the audience toggle.
- **Live**: `useFrameRefresh` on `dispatch` frames scoped to *this project and
  this topic*, invalidating only this listing.
- **State model**:
  - *Loading*: `loading documents…`
  - *Error*: `ErrorBox` "Could not list this topic's documents" + Retry.
  - *Empty*: `EmptyState` "Nothing written yet" / "A dispatch writes to
    `<directory>`. Nothing is there yet." — naming the directory on purpose.
  - *Document loading/error*: separate `Loading`/`ErrorBox` inside the body.
- **Known dead end, documented in the route**: the directory is recomputed from
  the topic's **current position** in the list, not stored. A topic that moved
  since its document was written makes this route look in a directory that does
  not exist and answer an **empty listing** — indistinguishable from "nothing
  dispatched yet" except that the named directory changed. This is the reason
  the empty state names the path.

---

## 5. The document browser (`DocumentList.tsx`, `DocumentReader.tsx`)

### F5.1 The corpus list — **built**

- **What**: every source the project has stored, virtualized
  (`@tanstack/react-virtual`, `overscan: 8`, `ROW_HEIGHT = 52` as an
  *estimate*, rows measured, `translateY` positioning).
- **Row**: a full-width button showing the title (or the source id when
  titleless, via `documentLabel`) and `<N> chars`.
- **Dropped documents stay in the list**, marked `.document-dropped` and
  showing `Dropped: <reason>` — the corpus keeps them as an audit trail and
  hiding them would misreport what the project holds.
- **Depends on**: `GET /api/projects/{id}/sources?include_dropped=true` —
  the repository always passes `true`; there is **no UI toggle** for it.

### F5.2 Filter documents — **built**

`<input type="search">`, `aria-label="Filter documents"`. Case-insensitive
substring on `documentLabel` only — i.e. on **title or id**, never on the
document's text, its URI, or its note.

### F5.3 Read a document — **built**

Clicking a row opens the shared `Drawer` **over the page** (not below the
list), titled with the row's label so the heading is right while the fetch is
in flight, falling back to the source id if the row has been filtered out from
under the open document.

- **Depends on**: `GET /api/projects/{id}/sources/{sourceId}`.
- **Body**: `Dropped: <reason>` if dropped, then the whole text in a single
  `<p class="document-reader-text">`.
- **Keyboard**: `Drawer`'s contract — focus in on open, restored on close,
  `Escape` closes, `Tab` trapped.
- **State**: `loading document…` / `ErrorBox` "Could not read this document" +
  Retry.

### F5.4 Live refresh — **built**

`useDocumentRefresh`: `corpus` frames **for this project only** invalidate the
list. `graph` and `log` frames are deliberately ignored (both asserted in
tests). The open document's *text* is never invalidated — it is immutable once
stored.

### F5.5 State model

- *Loading*: `loading documents…`
- *Error*: `ErrorBox` "Could not read this project's documents" + Retry.
- *Empty*: `EmptyState` "No documents" / "Nothing has been stored in this
  corpus yet." — **no next step offered**; nothing on this page can ingest a
  document (§7.5).

### F5.6 Range reads — **built but unreachable**

`DocumentRepository.read` takes a `DocumentRange` and the route accepts
`?start=&end=` with clamped, honest offsets returned. `DocumentReader.tsx:23`
calls `documents.read(projectId, sourceId, undefined)`. **No paging, no
quoting, no jump-to-offset in the UI**, despite the route existing precisely so
"a quote from it is checkable".

### F5.7 Fields fetched and never shown — **built but unreachable**

`DocumentSummary` carries `sha256`, `uri`, `publishedAt` and `note`; only
`title`, `charCount` and `droppedReason` are rendered. So a user cannot see
where a source came from, when it was published, or its hash — nor click
through to the original URL.

---

## 6. The graph (`GraphPane.tsx` + `GraphCanvas`, `GraphDetail`, `GraphLegend`)

### F6.1 The whole graph, drawn on arrival — **built**

`store.loadAll()` fires once per project on mount:
`GET /api/projects/{id}/graph` (no `limit` sent — the server's `MAX_GRAPH_NODES`
cap is the only bound). `loadWhole` **replaces** the drawing rather than
merging, and marks every node `expanded` **iff** the response was not
truncated — so on a complete graph clicking a node costs no request and the
legend correctly withholds the hollow-node rule.

`GraphCanvas` is `React.lazy` — the ~60 kB `react-force-graph-2d` bundle is
fetched only when this pane actually draws, never for a session transcript.

### F6.2 The canvas — **built**

`presentation/research/GraphCanvas.tsx`, `ForceGraph2D`.

- Sized by `ResizeObserver` on its container (not the library's
  `window.innerWidth` default); the library is **withheld entirely until the
  first measurement lands**.
- Node paint: radius `5/zoom`; **filled = expanded, hollow = more behind it**;
  colour = entity type (`entity-colors.ts`, resolved once from CSS custom
  properties via `getComputedStyle`); accent **ring = selected**.
- Labels drawn on the canvas, truncated at 28 chars with `…`, and **hidden
  entirely below `globalScale < 0.7`**.
- Hover tooltips: `nodeLabel` = `name (entityType)`, `linkLabel` =
  `relationshipType`. Links carry directional arrows and a fixed
  `rgba(138,149,163,0.35)`.
- Hit area is `9/scale`, larger than the painted 5px dot.
- `cooldownTime: 1800` (down from the library's 15 s).
- **Framing rules**: `zoomToFit(400, 48)` on engine stop, but only when the
  node count changed *and* nothing is selected. With a selection, framing is
  suppressed so an expansion does not zoom back out from what was just clicked.
- **Focus-on-select**: `centerAt` + `zoom(max(current, 2.5))` over 600 ms, for
  every selection route — canvas click, search result, or an entity named in
  the URL on load. `focusOn` never zooms *out*. A selection made before the
  simulation has positioned anything is picked up in `onEngineStop`.
- **Clicking a node pins it** (`fx`/`fy` set to current `x`/`y`) so the graph
  does not drift while the arriving neighbourhood settles. **Nothing ever
  unpins it** — see §7.4.
- **Gesture-only, undocumented on screen**: drag to pan, scroll to zoom, drag a
  node to move it — all `react-force-graph-2d` defaults, mentioned nowhere in
  the UI.

### F6.3 Expand a node — **built**

Clicking a node calls `onEntity(id)` → the route → back into
`store.expandNode(id)`, which selects first (so re-clicking an expanded node
still opens its detail) and then guards on `isExpanded` before issuing
`GET .../graph/entities/{id}/neighborhood`. `expand()` preserves node object
identity (d3-force stores positions on the objects) and merges the root, which
the route deliberately does not include in `entities`.

### F6.4 Search the graph — **built**

- `<input type="search" role="searchbox">`, `aria-label="Search the graph"`,
  placeholder "Search the graph". **Debounced 300 ms** because
  `find_entities` fetches the tenant's whole entity set per call.
- A `<select>` labelled "Filter by entity type": `All types` plus every type
  this store has *ever* seen in a result — accumulated, not derived from the
  current results, so choosing `fact` does not delete every other option.
- Blank term **and** no type → results cleared without a request. A type alone
  is a real query.
- Results render as a floating `.graph-results-panel` over the canvas with
  `aria-label="Search results"`; each row is a button showing name + type.
- **Picking a result clears the term**, which is what closes the floating panel
  so it stops covering the drawing you just asked for.
- Truncation is surfaced: `First N matches -- narrow the search to see more.`
  (from `next_after !== null` — the route paginates, the browser does not).

### F6.5 Reset view — **built**

Shown only when `view.nodes.length > 0`. Re-fetches the whole graph (rather
than restoring a snapshot, so it picks up extractions and merges since mount)
and drops the selection. Labelled "Reset", not "Clear", because with the whole
graph drawn by default an empty canvas is a state a reader would immediately
have to undo.

### F6.6 The detail panel (`GraphDetail.tsx`) — **built**

Rendered whenever `entity` is non-null. `aria-label="About <name>"`.

- Heading: the entity's name and type.
- `Remove` — takes the node off the *drawing* only; labelled "Remove from
  view" in its `aria-label` precisely so nobody reads it as a delete.
  `remove()` also drops neighbours that arrived only because of this node, but
  **keeps anything the reader expanded themselves**, and frees the id from
  `expanded` so it can be re-drawn later.
- `Close` — clears the selection.
- **Escape closes it**, and it is deliberately **not** a focus trap: the panel
  is meant to be read while working the canvas beside it.
- Edge list: one row per link, headed by `→`/`←` + the relationship type, then
  the other end's name. **Clicking a row selects and expands that node**, which
  is what makes the panel a way of walking the graph.
- Empty states, and the distinction is deliberate:
  - expanded → "No relationships were recorded for this entity."
  - not expanded → "Nothing connected to this one has been drawn yet. Click it
    on the canvas to pull in its neighbourhood."

### F6.7 The legend (`GraphLegend.tsx`) — **built**

Floats on the stage, `aria-label="What the canvas colours mean"`. One swatch +
type name + count per type **actually on the canvas**, commonest first. Plus a
one-line note — "Hollow nodes have more to pull in. Click one to expand it." —
withheld when every node is filled.

### F6.8 Live refresh — **built**

Any `graph` frame for this project re-runs `loadAll()`. Corpus frames are
ignored (asserted). **Stated cost**: `loadWhole` replaces the drawing, so an
extraction the reader did not ask for silently **undoes their pruning**. Their
*selection* survives if the node is still present.

### F6.9 State model

| Condition | Renders |
|---|---|
| `loading && nodes.length === 0` | `loading the knowledge graph…` |
| `nodes.length === 0`, no error | `EmptyState` "This graph is empty" / "Nothing has been extracted into this project yet. Ingest a document to start building it." |
| `nodes.length === 0`, error set | `EmptyState` "The graph could not be read" / "The project may still have entities; this page could not fetch them." — deliberately not claiming emptiness |
| lazy chunk in flight | `loading the graph canvas…` |
| search in flight | `loading entities…` under the controls |
| search returned nothing (and a term or type was actually asked for) | "Nothing matched. Try a shorter term, or widen the type filter." |
| whole-graph response truncated | "Showing part of a larger graph -- search to find what is not drawn." |
| any store error | `<p class="graph-error">` under the controls, **persistent until the next successful call** |

---

## 7. Dead ends and rough edges

### 7.1 Controls that can 503, and say nothing useful about it

Every optional dependency in `app.py` answers **503** when unwired, and the
frontend renders all of them as generic errors:

| Route | 503 detail | Where it lands in the UI |
|---|---|---|
| `/topics`, `/topics/{id}` | "no topic read model is configured" | `ErrorBox` "Could not read this project's topics" — reads as a server fault, not a build without the feature |
| `/topics/seed` (POST) | "topic seeding is not configured" | a **toast**; the Seed button stays enabled and looks live |
| `/topics/{id}/dispatch` (POST) | "topic dispatch is not configured" | `useDispatchTopic` has **no `onError` at all** — see 7.2 |
| `/dispatch/cancel` | "topic dispatch is not configured" | `useCancelDispatch` has **no `onError`** either |
| `/sources` | "no corpus read model is configured" | `ErrorBox` "Could not read this project's documents" |
| `/graph*` | "no graph read model is configured" | `.graph-error` line + "The graph could not be read" |
| topic write routes | "no topic write model is configured" | toast from the dialog |

`GET /topics/seed` and `GET /dispatch` are the two exceptions: they answer
empty rather than 503, so a build with no seeding shows an *idle* seed panel
and a build with no dispatch queue shows *no* dispatch bar.

### 7.2 Actions with no error path at all

`useDispatchTopic` and `useCancelDispatch` (`application/research/use-dispatch.ts`)
declare only `onSuccess`. A 503 (unwired), 404 (unknown topic), or 422 (unknown
action) from `Write understanding` or `Stop` produces **nothing visible** — no
toast, no chip, no state change. The button appears to do nothing. This is the
single clearest defect found.

### 7.3 404s a user can reach

- A pasted `/entity/<id>` for an entity that does not exist: `expandNode`
  catches it and shows `.graph-error` — but the URL keeps the bad entity, the
  detail panel renders `null` (the node is not in the view), and the only way
  out is `Reset view` or hand-editing the address bar. **Unsure** whether the
  error line is the only artifact; not run.
- A topic deleted or foreign to the project: `Manage` fires a query that 404s.
  `TopicList` renders the dialog only when `detail.data` is truthy, so the
  **query error is never rendered** — the click silently does nothing.
- A dropped/absent source id: `DocumentReader` shows its `ErrorBox` correctly.

### 7.4 State that needs a refresh, or is silently lost

- **Queued dispatches do not survive a server restart** (`BACKLOG.md` B37,
  `DispatchQueue` is process-local). The chips simply stop existing on the next
  read, which is indistinguishable from never having pressed the button. The UI
  says nothing.
- **Graph pruning is undone by any extraction** (F6.8), without warning.
- **Pinned nodes are never unpinned.** `GraphCanvas.onNodeClick` sets `fx`/`fy`
  and nothing clears them; after browsing a dozen nodes the layout is a field
  of frozen points. `Reset view` re-fetches, but `loadWhole` reuses existing
  node objects by id, so the pins **probably survive a reset**. **Unsure** —
  flagged rather than asserted; worth a test.
- **A topic that moves position orphans its documents** (F4.4) with an empty
  listing and no explanation beyond the changed directory name.

### 7.5 Empty states that do not say what to do next

- "No documents / Nothing has been stored in this corpus yet." — nothing on the
  research view can ingest a document. The user is not told where to go.
- "This graph is empty / Ingest a document to start building it." — names the
  action, offers no route to it.
- "No topics / Nothing has been seeded into this queue yet." — the Seed panel is
  directly above, but the empty state does not point at it, and if the Seeding
  rail pane is folded (which persists across reloads, F1.1) the user can be
  looking at "nothing has been seeded" with **no seeding control on screen**.

### 7.6 Ambiguity and truncation

- `GraphPane` shows both a "part of a larger graph" note (whole-graph cap) and
  a "First N matches" note (search page cap) in the same column, in the same
  `.graph-truncated` class. Two different truncations, one visual treatment.
- The `graph-error` line has no dismiss and no retry button; the only retry is
  another search or `Reset view`.
- The dispatch bar's "1 running" never says **which topic** is running unless
  the row happens to be scrolled into view — even though `Dispatch.question` is
  on the wire specifically so the row and the landing roster say the same
  words. **Built but unreachable.**

### 7.7 Accessibility and keyboard gaps

- No keyboard route to the graph at all: the canvas is not focusable, nodes
  cannot be tabbed, and the search results list is the only keyboard-reachable
  way to select an entity. There is no textual list of the graph.
- No keyboard shortcuts anywhere on the page (no `/` to focus search, no `Esc`
  to clear a filter).
- `GraphDetail` is not a focus trap by design, but nothing moves focus to it
  when a node is selected from the canvas.
- The `Manage` dialog and the document `Drawer` both trap focus correctly.

---

## 8. Adjacent features that do not know about each other

### 8.1 Seeding and the topic queue's size

`SeedPanel` hardcodes `MAX_TOPICS = 8` to match the server's default. The
route accepts `max_topics`. A user with a queue of 40 topics and a user with an
empty project get the same fixed 8, with no control and no explanation.

### 8.2 The graph and extraction

The **knowledge graph** is on the research view. **`ExtractionPane`** — which
narrates the very extraction that fills that graph — is on the **course** page
(`CourseView.tsx:87`), inside a "Working now" panel together with `Workers`.
So a reader watching their graph grow has no way to see *why* it is growing,
and a reader watching extraction has no picture of what it produced. Two halves
of one job on two pages.

### 8.3 The topic queue and autonomous research

`RunPanel` (start/cancel an `AutoResearchRun`, `POST .../auto-research`) is on
the **course** page. An autonomous run works the **project's topic queue** —
the exact list rendered on the research view — and the research view offers no
way to start, stop, or even see one. `CourseView`'s own comment concedes the
panel "sits above the course rather than inside it" because "a run works the
project's topic queue, not the workflow's stages"; it is on the wrong page by
its own argument.

The consequence for a user: `Write understanding` is disabled on every topic
with no sources, the fix is "research it", and the only research control is on
another page under a different heading.

### 8.4 The corpus list and the graph

Both are on this page and share nothing. Selecting an entity does not highlight
the documents it was extracted from; opening a document does not show which
entities came out of it. `sourceIds` on `TopicDetail` would link a topic to its
sources and is unrendered (§3.10). Nothing anywhere joins a graph node to a
`SourceId`.

### 8.5 Topic documents and the document browser

`TopicDocuments` (dispatch output, session-keyed workspace files) and
`DocumentList` (the corpus, source-keyed) are both called "Documents" in the
UI, live in two different places, and are entirely different things. The rail
pane is titled `Documents`; the section inside the dialog is headed
`Documents`.

### 8.6 Dispatch and the session it ran on

`Dispatch.sessionId` is on the wire and documented as "the only handle a viewer
has on it". Nothing renders it and nothing links to it. A user cannot open the
transcript of the agent that wrote their document from the research view —
though `TopicDocuments` uses that session id internally to read the file.

### 8.7 Approvals

The design doc (§8 "When it asks to fetch") specifies an inline
`⏸ research · waiting for you` row with `[allow]`/`[deny]`. Nothing on the
research view surfaces approvals. Since the shipped action (`understanding`) is
read-only this does not bite today; it will the moment `research` lands.

---

## 9. What a power user cannot do that the data model supports

Ordered roughly by how cheaply the gap could close.

1. **See a topic's findings.** `findingNotes` is fetched and dropped on the
   floor. The count is shown; the content never is.
2. **See a topic's rationale and scope.** Same — fetched, mapped, unrendered.
   These are the two fields that say *why* a topic exists.
3. **See that a topic is contested.** `contested` is on the wire; `BACKLOG.md`
   B23 is entirely about this flag; nothing renders it.
4. **See a source's provenance.** `uri`, `publishedAt`, `note` and `sha256` all
   arrive with every row. A user cannot open the original URL of a paper in
   their own corpus.
5. **Quote a range of a document.** `?start=&end=` exists, clamps, and returns
   honest offsets so a citation is checkable. The reader always requests the
   whole thing.
6. **Choose how many topics a seed opens.** `max_topics` is a request field.
7. **Know how many dispatches `Stop` cancelled.** The route answers the number
   precisely so it can be said.
8. **Cancel one queued dispatch.** Server-side cancel is per project only, so
   this needs a route as well as a control — but the queue is already ordered
   and positioned, and the design doc (§8) specifies the control.
9. **Retry a failed dispatch.** The chip persists with its reason, deliberately
   ("the failure and the retry are the same row"), and there is **no retry
   button** — the user re-presses `Write understanding`, which is not labelled
   as a retry and is disabled when the topic still has nothing gathered.
10. **Open the session a dispatch ran on.** `sessionId` is right there.
11. **Restate a topic's question.** `BACKLOG.md` B39: no command exists, by
    decision. The interim is "supersede and re-open", and the dialog *can* set
    `superseded` — but nothing in the UI links the two topics, so the
    relationship is lost.
12. **Delete, edit, or unresolve a sub-question.** The domain has add and
    resolve only.
13. **Page the graph search.** `next_after` is a real cursor; the browser reads
    it as a boolean.
14. **Ask for a neighbourhood deeper than 1 hop.** `GraphRepository.neighborhood`
    takes an optional `depth`, the route accepts it up to
    `MAX_NEIGHBORHOOD_DEPTH` and 422s above it, and `GraphPane` never passes
    one. A fully plumbed, entirely unreachable capability.
15. **Filter documents to dropped/live.** `include_dropped` is hardcoded true.
16. **Search entities by type alone** — this does work (blank term + a chosen
    type is a real query) but is completely undiscoverable.
17. **Export or copy anything** — no copy button on a document, an entity id, a
    topic question, or an edge list.

---

## 10. Designed but unimplemented (for completeness)

From `docs/design/topic-dispatch.md` §8 and `BACKLOG.md`:

- **Split dispatch button** with three actions: `Research and fetch sources`,
  `Write our understanding`, `Build a lesson`. Only the middle one exists;
  `DISPATCH_ACTIONS` is a one-element frozenset. The UI comment says it becomes
  a split button "when `research` and `lesson` land".
- **Richer running chip** — `⟳ research · round 2 · reading source 4`. Needs the
  turn-activity channel (`BACKLOG.md` B25). Today: `⟳ understanding · running`.
- **Per-queued-row `[cancel]`** (needs a server route).
- **`[retry]` on a failed chip.**
- **Inline approval interrupt** on the row.
- **`TOPICS · 1 running, 2 queued` in the pane header** — shipped instead as a
  separate `.topic-dispatch-bar` above the list, which is arguably better.
- **Topic dispatch in the REPL** (`BACKLOG.md` B36) — web-only, deliberately.
- **Durable dispatch queue** (`BACKLOG.md` B37) — deliberately not built until
  someone loses work to it.
- **Auto-research fetching** (`BACKLOG.md` B24) — a run is read-only over the
  corpus it already has, by design.
- **Contradiction detection** (`BACKLOG.md` B23) — `contested` is set by a human
  gate that does not exist in this UI.

---

## 11. File index

| Concern | File |
|---|---|
| Page shell | `frontend/src/presentation/research/ResearchView.tsx` |
| Rail folding | `frontend/src/presentation/research/RailPane.tsx` |
| Seeding | `frontend/src/presentation/research/SeedPanel.tsx` |
| Topic queue | `frontend/src/presentation/research/TopicList.tsx` |
| Topic dialog | `frontend/src/presentation/research/TopicStatusDialog.tsx` |
| Sub-questions | `frontend/src/presentation/research/SubQuestions.tsx` |
| Dispatch output viewer | `frontend/src/presentation/research/TopicDocuments.tsx` |
| Corpus list | `frontend/src/presentation/research/DocumentList.tsx` |
| Document reader | `frontend/src/presentation/research/DocumentReader.tsx` |
| Graph pane | `frontend/src/presentation/research/GraphPane.tsx` |
| Graph canvas | `frontend/src/presentation/research/GraphCanvas.tsx` |
| Graph detail | `frontend/src/presentation/research/GraphDetail.tsx` |
| Graph legend | `frontend/src/presentation/research/GraphLegend.tsx` |
| Entity colours | `frontend/src/presentation/research/entity-colors.ts` |
| Styles | `frontend/src/styles/research.css` |
| Graph store | `frontend/src/application/research/graph-store.ts` |
| Dispatch hooks | `frontend/src/application/research/use-dispatch.ts` |
| Frame debounce | `frontend/src/presentation/shell/use-frame-refresh.ts` |
| Feed frame types | `frontend/src/application/ports/event-stream.ts` |
| Topic domain | `frontend/src/domain/research/topic.ts` |
| Dispatch domain | `frontend/src/domain/research/dispatch.ts` |
| Document domain | `frontend/src/domain/research/document.ts` |
| Topic-document domain | `frontend/src/domain/research/topic-document.ts` |
| Seeding domain | `frontend/src/domain/research/seeding.ts` |
| Graph domain | `frontend/src/domain/knowledge/graph.ts` |
| Topic HTTP | `frontend/src/infrastructure/http/topic-repository.ts` |
| Document HTTP | `frontend/src/infrastructure/http/document-repository.ts` |
| Graph HTTP | `frontend/src/infrastructure/http/graph-repository.ts` |
| Routing | `frontend/src/presentation/routing/routes.ts` |
| Backend routes | `research_team/interfaces/web/app.py:617-1074` |
| Dispatch actions | `research_team/application/topic_dispatch.py:65` |
| Design | `docs/design/topic-dispatch.md` |
| Deferred work | `BACKLOG.md` B23, B24, B25, B36, B37, B39 |

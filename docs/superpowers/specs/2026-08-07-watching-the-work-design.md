# Watching the work

A course page today says almost nothing about what is happening on it. `RunPanel`
polls for counters -- rounds, turns, findings, quiet rounds, failures -- and names
the topic in flight. Everything else is a navigation away, and the knowledge graph
is not visible at any distance: `remember` runs for minutes and emits one line of
tool-result text when it is done.

This design closes both gaps on the course page itself: a roster of everything in
flight on the project, a drawer that puts a worker's real transcript over the page,
and live telemetry from inside extraction.

## What this is not

**A browsable graph.** Read methods on `KnowledgePort` (`entities`, `neighbors`,
`merges`) and a view over them are a separate piece of work, deliberately deferred.
They read state rather than watch work and share no code with anything here.

**A new durable record.** Nothing below appends a domain event. See "The frames are
provisional" -- it is the load-bearing constraint, not a footnote.

---

# Part A -- the roster and the drawer

## The surface

A `Workers` panel on the course page, above `RunPanel`:

```
● research run          round 4 · "spaced repetition"        2m 14s
  └ ● extraction        roediger-2006 · consolidating 7/23     18s
● session 3f2a  (you)   turn 12                                 4s
○ session 91bc          idle
```

Extraction **nests under the turn running it** rather than sitting as a sibling.
A `remember` call happens inside a round's turn; two rows side by side would draw
two workers where there is one, and the containment is the thing a reader wants
when a round looks stalled.

Clicking a session or run row opens the drawer on that session's transcript.
Clicking the extraction row opens it on the extraction pane.

## The roster

New `application/workers.py`. One service, one question:

```python
async def on(self, project_id: UUID) -> list[Worker]
```

It folds the project for `member_session_ids`, asks `TurnSupervisor.running()` for
each, asks `ResearchSupervisor.active()` for the run, and asks what extraction is in
flight. `Worker` is a frozen dataclass discriminated by
`kind: "turn" | "run" | "extraction"`, with `parent` set for nesting.

The extraction question arrives through a `Protocol` declared here --

```python
class ExtractionsInFlight(Protocol):
    def in_flight(self, project_id: UUID) -> ExtractionSnapshot | None: ...
```

-- which `ExtractionActivity` happens to satisfy. `application` must not import
`interfaces`, and the same reasoning `TopicQueuePort` gives applies: a protocol
here means the roster can be tested with a stub and names no web class.

Route: `GET /api/projects/{project_id}/workers`.

### Why polled rather than pushed

Client-side polling at 2s, matching `RunPanel`'s existing `POLL_MS`.

Pushing the roster would mean making `TurnActivity` and `TurnSupervisor`
project-aware so they could address a broadcast, and both are deliberately
session-keyed. The roster itself is two process-local dicts and a fold, so a 2s
poll costs almost nothing and bounds staleness at 2s on a list that changes every
few minutes. Everything *interesting inside* a worker is still pushed over SSE, so
the poll sets the latency of "a new worker appeared", not of anything a person
watches.

The upgrade path, should it ever matter: a provisional `WorkerChanged` frame
emitted from `TurnActivity.begin`/`settle`, once something else needs the project
id in there anyway.

## The drawer

`presentation/course/WorkerDrawer.tsx`.

`createSessionStore` is a factory, so the drawer builds **its own store**, calls
`open(sessionId)`, subscribes through `useSessionStream`, and renders the existing
`Conversation` and `ActivityFeed` unchanged. No edits to either component, and no
contention with the shell's store, which belongs to the session route. Closing the
drawer calls `close()` on its store.

**Read-only, deliberately.** No `Composer`. A pending approval shows as a chip
linking to the session view rather than being answerable in place: typing into a
session you opened in order to observe is a different intention, and it should cost
a navigation. (An unattended run does not generate approvals in the first place --
the driver floors `fetch` at `ask` and works read-only precisely so it cannot
deadlock on one -- so this case belongs to a human's joined session, whose
approvals belong to whoever is driving it.)

The watched session lives in the URL (`?watching=<sessionId>`), so a reload
reproduces the screen. Same reasoning `SessionView` gives for keeping the open file
in the route: the address bar owns it, so nothing can silently drop it and a link
always reproduces what you were looking at.

## Failure

A failed roster poll shows a **stale** badge and keeps the last list. It must not
empty the panel: an empty panel reads as "nothing is running", which is the exact
lie this feature exists to kill.

A drawer whose session finishes stays open on the finished transcript. The session
store already handles turn end; nothing special is needed.

---

# Part B -- extraction telemetry

## The port

In `application/knowledge.py`, mirroring `ActivityReporter`:

```python
@dataclass(frozen=True)
class ExtractionNote:
    source_id: str
    stage: Literal["storing", "extracting", "extracted",
                   "consolidating", "consolidated", "failed"]
    detail: str = ""
    entities: int | None = None
    relationships: int | None = None
    domain: str | None = None
    domain_confidence: float | None = None
    index: int | None = None
    total: int | None = None
    model_calls: int | None = None

ExtractionReporter = Callable[[ExtractionNote], None]
```

`KnowledgePort.ingest` grows `report: ExtractionReporter | None = None`.

A call parameter rather than a constructor collaborator, because that is the
established shape in this codebase -- `TurnSupervisor.run(on_activity=...)` -- and
because it keeps the adapter's constructor from growing a seventh dependency.
Optional, so every existing caller and test is unaffected.

`domain_confidence` carries `IngestReport`'s distinction intact: `0.0` means the
classifier gave up and fell back, `None` means no classifier ran. A pane that
collapsed those would be reporting a guess as a decision.

## Instrumenting the adapter

Six report points in `RedstringKnowledge.ingest`, and one decorator.

1. `storing` -- after `_store_document`.
2. `extracting` -- before `build_graph`.
3. **A reporting `LlmProvider` wrapper**, in force for the duration.
   `build_graph` takes no callbacks and is one opaque await containing domain
   classification, chunking, and N extraction calls. `LlmProvider` is a
   single-method protocol, so a decorator that counts and reports each call is a
   few lines, and it is the only way to see inside `build_graph` without
   hand-driving `ExtractionPipeline` -- which `redstring_adapter.py`'s own
   docstring warns loses `domain` and `domain_confidence` and needs a dotted
   import of an internal classifier.

   It reports **model calls, not chunks.** The chunk count is not knowable in
   advance, and "chunk 4 of 9" would be an invented denominator.
4. `extracted` -- `entities`, `relationships`, `domain`, `domain_confidence`.
5. `consolidating` -- per iteration of `_consolidate`'s loop, which is our own
   code and therefore free: `index`, `total`, and the entity name, then a note per
   `ConsolidationReport` carrying `reason` (the score band and any adjudicator
   verdict) with the canonical and absorbed names. The adjudicator's own model
   calls tick through the same decorator.
6. `consolidated`, or `failed` with the `KnowledgeError` message.

**Reporting must never fail an ingest.** Every call is guarded, the way
`_record_look` is best-effort: a listener that raises must not cost a document that
has already been fetched and paid for.

`format_ingest`'s output does not change. The model's view of the tool does not
move.

## Carrying the frames

New `interfaces/web/extraction.py`. `activity.py`'s docstring says it is "shaped
deliberately like `approvals.py`, which solves the same problem for the same
reason"; this is the third of that shape and should be visibly so.

`ExtractionActivity` is keyed by **project_id**, not session: extraction is a
project-level fact and the graph is tenant-scoped by project.

- `begin(project_id, source_id)`, `note(...)`, `settle(project_id, source_id, ok=)`
- `listen()` / `stop_listening()` for the SSE fan-out, unbounded like the others
- `GET /api/projects/{project_id}/extraction` returns the running extraction and
  the last finished one

The catch-up route is not an optimisation. These frames carry no feed position, so
`Last-Event-ID` cannot replay them, and an SSE connection drops routinely -- sleep,
a network change, a proxy closing an idle socket. Without somewhere to catch up
from, a lossy reconnect would look exactly like a stalled extraction: a frozen pane
either way. This is `activity.py`'s argument, unchanged, for the same reason.

A failed extraction moves aside rather than vanishing, exactly as
`TurnActivity.discarded` does: what streamed is the only trace of it that exists.

Frame type `"Extraction"` -- PascalCase like `TurnActivity`, because the browser
switches on one `type` field for everything it receives. A third listener joins the
multiplexer in `app.py`.

## The frames are provisional

**They must never become domain events.**

The log is the replay substrate. `rebuild.py` refuses to serve a partial graph and
forbids model calls on the replay path, so that a session refolded years from now
does not depend on a live endpoint. Extraction progress is not a fact about the
domain -- it is a fact about one attempt, at one moment, that a later reader has no
use for and cannot act on. It belongs in the provisional channel beside the turn
deltas.

`DocumentExtracted` and `EntitiesMerged` remain the entire durable record. The
graph refolds to exactly what it folds to today.

## The pane

In the drawer: stages with elapsed times, the extraction result once known, then
the consolidation pass as a live list -- each entity with its verdict and the
reason it was given.

Consolidation is where the judgement is, so it gets the detail. The rest is
throughput.

---

# Testing

- `WorkerRoster` against fake supervisors. No model involved.
- `ExtractionActivity` driven through `note()` directly, like the existing activity
  tests -- no connection, no timers.
- **The valuable one:** a real `ingest` over redstring's `FakeLlmProvider` and
  `InMemoryGraphStore`, asserting the note sequence. This pins stage order and
  catches a decorator that has quietly stopped reporting.
- A reporter that raises does not fail the ingest.
- Frontend: domain tests for the worker model and the extraction buffer, mirroring
  `activity.test.ts`; an extraction-store test driving `handleFrame` with
  `Extraction` frames, including one for another project that must be ignored.
- `format_ingest`'s text is asserted unchanged.

# Files

New:

- `research_team/application/workers.py`
- `research_team/interfaces/web/extraction.py`
- `frontend/src/domain/worker/worker.ts` (+ test)
- `frontend/src/domain/knowledge/extraction.ts` (+ test)
- `frontend/src/application/knowledge/extraction-store.ts` (+ test) -- project-keyed,
  because `Extraction` frames are addressed to a project. Putting them in the
  session store would be filing a project-level fact under whichever session
  happened to be open.
- `frontend/src/presentation/course/Workers.tsx`
- `frontend/src/presentation/course/WorkerDrawer.tsx`
- `frontend/src/presentation/course/ExtractionPane.tsx`

Changed:

- `research_team/application/knowledge.py` -- `ExtractionNote`, `ExtractionReporter`,
  `ingest` signature
- `research_team/infrastructure/knowledge/redstring_adapter.py` -- report points and
  the provider decorator
- `research_team/infrastructure/agent/knowledge_tools.py` -- thread the reporter
- `research_team/composition.py` -- wire the roster and `ExtractionActivity`
- `research_team/interfaces/web/app.py` -- two routes, third SSE listener
- `frontend/src/presentation/course/CourseView.tsx` -- mount `Workers`
- `frontend/src/styles/course.css`

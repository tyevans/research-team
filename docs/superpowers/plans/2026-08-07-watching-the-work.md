# Watching the Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a course page show what is actually happening on it — a roster of everything in flight on the project, a read-only drawer over that page carrying a worker's real transcript, and live telemetry from inside knowledge-graph extraction.

**Architecture:** Two halves over one existing SSE connection. The roster is a process-local read (`GET /api/projects/{id}/workers`, polled at 2s) assembled by a new `application/workers.py` from the turn supervisor, the research supervisor, and an extraction protocol. Extraction telemetry is a reporter threaded into `RedstringKnowledge.ingest`, broadcast by a new `interfaces/web/extraction.py` shaped exactly like the existing `activity.py` and `approvals.py`, and rendered in a pane. **Nothing here appends a domain event.**

**Tech Stack:** Python 3.13, FastAPI, eventsource, redstring, pytest/pytest-asyncio. Frontend: TypeScript, React, zustand, TanStack Query, Vitest.

**Spec:** `docs/superpowers/specs/2026-08-07-watching-the-work-design.md`

## Global Constraints

- **Extraction frames are provisional and must never become domain events.** No task appends to the event log. `DocumentExtracted` and `EntitiesMerged` remain the entire durable record.
- **Layering is test-enforced.** `tests/test_architecture.py::test_imports_point_inward` fails if `application` imports `infrastructure` or `interfaces`. `application/workers.py` therefore declares protocols; it names no concrete supervisor or web class.
- **`application` may not name a framework.** `test_inner_layers_name_no_framework` enforces it. No FastAPI, no pydantic-only-for-HTTP in `application/`.
- **Reporting must never fail an ingest.** Every `report(...)` call site is guarded, the way `AutoResearchDriver._record_look` is best-effort.
- **`format_ingest`'s output does not change.** The model's view of the `remember` tool must not move.
- **The roster must never render empty on error.** An empty panel reads as "nothing is running", which is the exact lie this feature exists to kill. A failed poll shows a stale badge over the last known list.
- **Python style:** every module and public callable gets a docstring explaining *why*, matching the density of the surrounding code. Line length 100.
- **Frontend verification** is `cd frontend && npm run verify` (format:check, lint, typecheck, test:coverage, build, size). `npm run build` output under `research_team/interfaces/web/static/` **is committed** — `web.py` serves it with no Node toolchain.
- **Python verification** is `uv run pytest`. Run only touched test files while iterating; CI runs the full suite.

## Shared interfaces

Defined in Task 1 and Task 6; every later task consumes these exact names.

```python
# research_team/application/workers.py
ExtractionSnapshot(source_id: str, stage: str, detail: str, index: int | None,
                   total: int | None, started_at: datetime | None)
Worker(kind: Literal["run", "turn", "extraction"], ref: str, detail: str,
       session_id: UUID | None, parent: str | None, started_at: datetime | None)
Roster(project_id: UUID, workers: tuple[Worker, ...], idle_session_ids: tuple[UUID, ...])
WorkerRoster(projects, turns: TurnsInFlight, runs: RunsInFlight | None,
             extractions: ExtractionsInFlight | None).on(project_id) -> Roster
```

```python
# research_team/application/knowledge.py
ExtractionNote(source_id, stage, detail, entities, relationships, domain,
               domain_confidence, index, total, model_calls)
ExtractionReporter = Callable[[ExtractionNote], None]
KnowledgePort.ingest(source, *, report: ExtractionReporter | None = None)
```

```ts
// frontend/src/domain/worker/worker.ts
Worker { kind, ref, detail, sessionId, parent, startedAt }
Roster { projectId, workers, idleSessionIds }
WorkerNode { worker, children }
nest(workers: readonly Worker[]): readonly WorkerNode[]

// frontend/src/domain/knowledge/extraction.ts
Extraction { sourceId, stage, stages, entities, relationships, domain,
             domainConfidence, index, total, modelCalls, merges, failed }
emptyExtraction(sourceId): Extraction
applyNote(extraction: Extraction, note: ExtractionFrame): Extraction
```

---

# Part A — the roster and the drawer

## Task 1: `WorkerRoster`

The roster is pure application logic over three protocols, so it is testable with stubs and no model, no HTTP, and no database.

**Files:**
- Create: `research_team/application/workers.py`
- Modify: `research_team/application/__init__.py` (export the new names)
- Test: `tests/application/test_workers.py`

**Interfaces:**
- Consumes: `ProjectState.member_session_ids` / `.active_session_id` (`research_team/domain/project.py`), `RunningTurn` and `ActiveRun` shapes (structural only — referenced through protocols, not imported).
- Produces: `Worker`, `Roster`, `ExtractionSnapshot`, `WorkerRoster`, `TurnsInFlight`, `RunsInFlight`, `ExtractionsInFlight`.

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_workers.py`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

from research_team.application.workers import (
    ExtractionSnapshot,
    WorkerRoster,
)
from research_team.domain.project import ProjectState

AT = datetime(2026, 8, 7, 12, 0, tzinfo=UTC)


@dataclass(frozen=True)
class FakeRunningTurn:
    session_id: UUID
    turn_index: int
    started_at: datetime


@dataclass(frozen=True)
class FakeActiveRun:
    run_id: UUID
    project_id: UUID
    session_id: UUID


class FakeTurns:
    """A `TurnsInFlight` over a dict."""

    def __init__(self, running: dict[UUID, FakeRunningTurn]) -> None:
        self._running = running

    def running(self, session_id: UUID):
        return self._running.get(session_id)


class FakeRuns:
    def __init__(self, run: FakeActiveRun | None) -> None:
        self._run = run

    def active(self, project_id: UUID):
        return self._run


class FakeExtractions:
    def __init__(self, snapshot: ExtractionSnapshot | None) -> None:
        self._snapshot = snapshot

    def in_flight(self, project_id: UUID):
        return self._snapshot


class FakeProjects:
    """The slice of the session service the roster uses."""

    def __init__(self, state: ProjectState) -> None:
        self._state = state

    async def project_state(self, project_id: UUID) -> ProjectState:
        return self._state


def state_with(project_id: UUID, members: list[UUID]) -> ProjectState:
    return ProjectState(
        project_id=project_id, status="created", name="course", member_session_ids=members
    )


@pytest.mark.asyncio
async def test_a_running_turn_is_a_worker_and_a_quiet_session_is_idle():
    project_id, busy, quiet = uuid4(), uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [busy, quiet])),
        turns=FakeTurns({busy: FakeRunningTurn(busy, 12, AT)}),
        runs=None,
        extractions=None,
    )

    result = await roster.on(project_id)

    assert [w.kind for w in result.workers] == ["turn"]
    assert result.workers[0].session_id == busy
    assert result.workers[0].detail == "turn 12"
    assert result.workers[0].started_at == AT
    assert result.idle_session_ids == (quiet,)


@pytest.mark.asyncio
async def test_the_run_comes_first_and_extraction_nests_under_it():
    project_id, run_session = uuid4(), uuid4()
    run = FakeActiveRun(uuid4(), project_id, run_session)
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [run_session])),
        turns=FakeTurns({run_session: FakeRunningTurn(run_session, 4, AT)}),
        runs=FakeRuns(run),
        extractions=FakeExtractions(
            ExtractionSnapshot(
                source_id="roediger-2006",
                stage="consolidating",
                detail="Henry L. Roediger III",
                index=7,
                total=23,
                started_at=AT,
            )
        ),
    )

    result = await roster.on(project_id)

    assert [w.kind for w in result.workers] == ["run", "turn", "extraction"]
    assert result.workers[0].ref == str(run.run_id)
    extraction = result.workers[-1]
    assert extraction.parent == str(run.run_id)
    assert extraction.detail == "consolidating 7/23 · Henry L. Roediger III"
    # Extraction opens no session of its own: the pane is its detail view.
    assert extraction.session_id is None


@pytest.mark.asyncio
async def test_extraction_nests_under_the_only_turn_when_no_run_is_active():
    project_id, session_id = uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [session_id])),
        turns=FakeTurns({session_id: FakeRunningTurn(session_id, 3, AT)}),
        runs=None,
        extractions=FakeExtractions(
            ExtractionSnapshot("notes", "extracting", "", None, None, AT)
        ),
    )

    result = await roster.on(project_id)

    assert result.workers[-1].parent == str(session_id)


@pytest.mark.asyncio
async def test_extraction_is_top_level_when_the_owner_is_ambiguous():
    """Two turns and no run: nothing here knows which one called `remember`.

    Shown at top level rather than attached to a guess. A wrong parent claims
    a containment that is not there, which is worse than none.
    """
    project_id, one, two = uuid4(), uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [one, two])),
        turns=FakeTurns(
            {one: FakeRunningTurn(one, 1, AT), two: FakeRunningTurn(two, 1, AT)}
        ),
        runs=None,
        extractions=FakeExtractions(
            ExtractionSnapshot("notes", "extracting", "", None, None, AT)
        ),
    )

    result = await roster.on(project_id)

    assert result.workers[-1].parent is None


@pytest.mark.asyncio
async def test_a_project_with_nothing_running_has_no_workers():
    project_id, session_id = uuid4(), uuid4()
    roster = WorkerRoster(
        FakeProjects(state_with(project_id, [session_id])),
        turns=FakeTurns({}),
        runs=None,
        extractions=None,
    )

    result = await roster.on(project_id)

    assert result.workers == ()
    assert result.idle_session_ids == (session_id,)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/application/test_workers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.application.workers'`

- [ ] **Step 3: Write the implementation**

Create `research_team/application/workers.py`:

```python
"""Everything in flight on one project, in one answer.

A course page that shows counters and nothing else cannot answer "what is
happening right now", and the pieces that *could* answer it are scattered:
which sessions belong to the project is a fold, which of them are mid-turn is
the turn supervisor's dict, whether a run is going is the research
supervisor's, and whether extraction is working is the web layer's buffer.
This gathers those four into one read.

**Protocols rather than the concrete supervisors.** `application` may not
import `interfaces`, and `test_imports_point_inward` enforces it -- the
extraction buffer lives in the web layer, so it arrives here as a structural
type. The same reasoning `TopicQueuePort` gives applies to all three: a
protocol means this can be tested with a stub and names no adapter.

**Nothing here is state the log does not have, and nothing here is durable.**
Every source is process-local by necessity -- a task cannot be persisted --
so a restart shows an empty roster, which is the truth: nothing is running.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

WorkerKind = Literal["run", "turn", "extraction"]


@dataclass(frozen=True)
class ExtractionSnapshot:
    """One extraction in flight, as the roster needs to describe it.

    Carries no session id, deliberately. The adapter that produces these is
    scoped to a project and knows nothing about sessions; giving it a second
    identity to get wrong would be worse than resolving the containment here.
    See `_parent_for`.
    """

    source_id: str
    stage: str
    detail: str = ""
    index: int | None = None
    total: int | None = None
    started_at: datetime | None = None


@dataclass(frozen=True)
class Worker:
    """One thing working on this project."""

    kind: WorkerKind
    ref: str
    """Identifies this worker within the roster: a run id, a session id, or a
    source id. Text rather than a UUID because the three are different kinds
    of identifier and `parent` has to be comparable across them."""
    detail: str
    """What it is doing, already composed. The reader wants "round 4 ·
    spaced repetition", and composing it here keeps two front ends from
    disagreeing about how to say the same thing."""
    session_id: UUID | None
    """The session whose transcript is this worker's detail view. None for
    extraction, whose detail view is the extraction pane."""
    parent: str | None
    """The `ref` of the worker this one runs inside, when that is known."""
    started_at: datetime | None


@dataclass(frozen=True)
class Roster:
    """What is working on a project, and who is attached but quiet.

    Two fields rather than one list with a flag, because a worker is a thing
    that is working: an idle session is context about who is here, and folding
    it into `workers` would make "is anything running" a filter rather than a
    length.
    """

    project_id: UUID
    workers: tuple[Worker, ...] = ()
    idle_session_ids: tuple[UUID, ...] = ()


class ProjectStates(Protocol):
    """The slice of the session service the roster reads."""

    async def project_state(self, project_id: UUID): ...


class TurnsInFlight(Protocol):
    """Satisfied by `TurnSupervisor`."""

    def running(self, session_id: UUID): ...


class RunsInFlight(Protocol):
    """Satisfied by `ResearchSupervisor`."""

    def active(self, project_id: UUID): ...


class ExtractionsInFlight(Protocol):
    """Satisfied by `ExtractionActivity` in the web layer."""

    def in_flight(self, project_id: UUID) -> ExtractionSnapshot | None: ...


class WorkerRoster:
    """Assembles one project's roster from whoever knows a piece of it."""

    def __init__(
        self,
        projects: ProjectStates,
        *,
        turns: TurnsInFlight,
        runs: RunsInFlight | None = None,
        extractions: ExtractionsInFlight | None = None,
    ) -> None:
        self._projects = projects
        self._turns = turns
        self._runs = runs
        self._extractions = extractions

    async def on(self, project_id: UUID) -> Roster:
        """Everything working on `project_id`, in a fixed order.

        Ordered run, then turns, then extraction -- fixed rather than
        incidental, so the panel does not reshuffle between polls and a test
        can assert on a sequence.
        """
        state = await self._projects.project_state(project_id)
        members = list(state.member_session_ids)

        run = self._runs.active(project_id) if self._runs is not None else None
        running = [
            turn for turn in (self._turns.running(session) for session in members) if turn
        ]

        workers: list[Worker] = []
        if run is not None:
            workers.append(
                Worker(
                    kind="run",
                    ref=str(run.run_id),
                    detail="autonomous run",
                    session_id=run.session_id,
                    parent=None,
                    started_at=None,
                )
            )
        workers.extend(
            Worker(
                kind="turn",
                ref=str(turn.session_id),
                detail=f"turn {turn.turn_index}",
                session_id=turn.session_id,
                parent=None,
                started_at=turn.started_at,
            )
            for turn in running
        )

        snapshot = (
            self._extractions.in_flight(project_id) if self._extractions is not None else None
        )
        if snapshot is not None:
            workers.append(
                Worker(
                    kind="extraction",
                    ref=snapshot.source_id,
                    detail=_extraction_detail(snapshot),
                    session_id=None,
                    parent=_parent_for(run, running),
                    started_at=snapshot.started_at,
                )
            )

        busy = {turn.session_id for turn in running}
        return Roster(
            project_id=project_id,
            workers=tuple(workers),
            idle_session_ids=tuple(session for session in members if session not in busy),
        )


def _extraction_detail(snapshot: ExtractionSnapshot) -> str:
    """The stage, with its progress and subject when there are any."""
    parts = [snapshot.stage]
    if snapshot.index is not None and snapshot.total:
        parts[0] = f"{snapshot.stage} {snapshot.index}/{snapshot.total}"
    if snapshot.detail:
        parts.append(snapshot.detail)
    return " · ".join(parts)


def _parent_for(run, running: Iterable) -> str | None:
    """Which worker an extraction is running inside, when that is knowable.

    A run owns whatever extraction is happening: it is the only thing working
    the queue. With no run, one running turn is unambiguous. Two are not, and
    an extraction is shown at top level rather than attached to a guess -- a
    wrong parent claims a containment that is not there, which reads worse
    than no claim at all.
    """
    if run is not None:
        return str(run.run_id)
    turns = list(running)
    if len(turns) == 1:
        return str(turns[0].session_id)
    return None
```

- [ ] **Step 4: Export the new names**

In `research_team/application/__init__.py`, add to the imports and to `__all__`:

```python
from research_team.application.workers import (
    ExtractionSnapshot,
    ExtractionsInFlight,
    Roster,
    Worker,
    WorkerRoster,
)
```

Add `"ExtractionSnapshot"`, `"ExtractionsInFlight"`, `"Roster"`, `"Worker"`, `"WorkerRoster"` to `__all__`, keeping it alphabetically sorted as the file already is.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/application/test_workers.py tests/test_architecture.py -v`
Expected: PASS — all five roster tests, and the architecture suite still green.

- [ ] **Step 6: Commit**

```bash
git add research_team/application/workers.py research_team/application/__init__.py tests/application/test_workers.py
git commit -m "feat: a roster of what is in flight on a project"
```

---

## Task 2: The roster route

**Files:**
- Create: nothing
- Modify: `research_team/interfaces/web/presenters.py` (add `roster_view`), `research_team/interfaces/web/app.py` (`create_app` signature + one route)
- Test: `tests/interfaces/test_web.py` (append)

**Interfaces:**
- Consumes: `Roster`, `Worker` from Task 1.
- Produces: `roster_view(roster: Roster) -> dict[str, Any]`; `GET /api/projects/{project_id}/workers`; `create_app(..., workers: WorkerRoster | None = None)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/interfaces/test_web.py`. Follow the file's existing client fixture and project-creation helpers rather than inventing new ones — read the top of the file first and reuse whatever it already uses to make a project and a session.

```python
@pytest.mark.asyncio
async def test_workers_lists_an_idle_member_session(client):
    """A project with a session attached and nothing running.

    The 200-with-empty-workers case matters as much as the busy one: the panel
    must be able to say "attached, nothing running" without an error.
    """
    project_id = await make_project(client)
    session_id = await join_session(client, project_id)

    response = await client.get(f"/api/projects/{project_id}/workers")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == str(project_id)
    assert body["workers"] == []
    assert body["idle_session_ids"] == [str(session_id)]


@pytest.mark.asyncio
async def test_workers_404s_on_an_unknown_project(client):
    response = await client.get(f"/api/projects/{uuid4()}/workers")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_workers_is_404_when_the_roster_is_not_wired(client_without_workers):
    """A build with no roster says so, rather than reporting an empty project.

    The same shape `auto-research` uses for a disabled feature: 200 with an
    empty list would tell a browser that nothing is running, which is a
    different claim from "this build cannot tell you".
    """
    project_id = await make_project(client_without_workers)
    response = await client_without_workers.get(f"/api/projects/{project_id}/workers")
    assert response.status_code == 404
```

Add a `client_without_workers` fixture beside the existing client fixture, built the same way but passing `workers=None` to `create_app`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/interfaces/test_web.py -k workers -v`
Expected: FAIL — 404 from FastAPI on an unregistered route (the third test may pass vacuously; the first two must fail).

- [ ] **Step 3: Add the presenter**

In `research_team/interfaces/web/presenters.py`, beside `run_view`:

```python
def worker_view(worker: Worker) -> dict[str, Any]:
    """One worker, in the browser's shape.

    `started_at` is ISO-8601 text rather than an epoch number, matching every
    other timestamp this layer emits.
    """
    return {
        "kind": worker.kind,
        "ref": worker.ref,
        "detail": worker.detail,
        "session_id": str(worker.session_id) if worker.session_id else None,
        "parent": worker.parent,
        "started_at": worker.started_at.isoformat() if worker.started_at else None,
    }


def roster_view(roster: Roster) -> dict[str, Any]:
    """Everything in flight on a project, plus who is attached and quiet."""
    return {
        "project_id": str(roster.project_id),
        "workers": [worker_view(worker) for worker in roster.workers],
        "idle_session_ids": [str(session) for session in roster.idle_session_ids],
    }
```

Import `Roster` and `Worker` from `research_team.application` at the top of the file, following the existing import grouping.

- [ ] **Step 4: Add the parameter and the route**

In `research_team/interfaces/web/app.py`, add to `create_app`'s signature after `research`:

```python
    workers: WorkerRoster | None = None,
```

Import `WorkerRoster` from `research_team.application` and `roster_view` from `research_team.interfaces.web.presenters`, following the existing groupings.

Add the route next to `get_auto_research` (near line 626):

```python
    @app.get("/api/projects/{project_id}/workers")
    async def get_workers(project_id: UUID):
        """Everything in flight on this project, right now.

        Polled rather than pushed, and cheap enough to be: two process-local
        dicts and one fold. What it sets the latency of is "a new worker
        appeared" -- everything *inside* a worker arrives over the live feed,
        which is where a person's attention actually is.

        404 when no roster is wired, matching how `auto-research` answers for
        a feature this build does not have. A 200 with an empty list would
        tell a browser that nothing is running, which is a different claim.
        """
        if workers is None:
            raise HTTPException(status_code=404, detail="the worker roster is not enabled")
        await _require_project(project_id)
        return roster_view(await workers.on(project_id))
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/interfaces/test_web.py -k workers -v`
Expected: PASS — all three.

- [ ] **Step 6: Commit**

```bash
git add research_team/interfaces/web/presenters.py research_team/interfaces/web/app.py tests/interfaces/test_web.py
git commit -m "feat: serve a project's worker roster"
```

---

## Task 3: Wire the roster into composition

The roster needs the turn supervisor, the research supervisor, and the session service — all of which `build_application` already holds. Extraction is wired in Task 9; it is `None` here.

**Files:**
- Modify: `research_team/composition.py` (build the roster, add it to `Application`), `web.py` (pass it to `create_app`)
- Test: `tests/interfaces/test_web.py` (already covers it through the fixture) plus one composition assertion

**Interfaces:**
- Consumes: `WorkerRoster` from Task 1.
- Produces: `Application.workers: WorkerRoster`.

- [ ] **Step 1: Write the failing test**

Append to `tests/application/test_workers.py`:

```python
@pytest.mark.asyncio
async def test_the_composition_root_wires_a_roster(db_path):
    """A built application can answer "what is running" without more wiring.

    Asserted here rather than left to the web tests because both front ends
    are entitled to the roster, and a CLI that had to build its own would end
    up with a second one disagreeing with the first.
    """
    from research_team import composition

    app = composition.build_application(db_path=db_path)

    assert app.workers is not None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/application/test_workers.py -k composition -v`
Expected: FAIL — `AttributeError: 'Application' object has no attribute 'workers'`

- [ ] **Step 3: Add the field and build it**

In `research_team/composition.py`, import `WorkerRoster` from `research_team.application`, then add a field to the `Application` dataclass beside `research`:

```python
    workers: WorkerRoster
    """Everything in flight on a project, for a front end that wants to show it.

    A field for the same reason `research` is one: it needs three things only
    this module holds together -- the session service, the turn supervisor and
    the research supervisor -- and both front ends want the same answer from
    the same three."""
```

Where the `Application` is constructed, build it:

```python
    worker_roster = WorkerRoster(service, turns=turns, runs=research_supervisor)
```

using whatever local names this function already has for the service, the turn supervisor and the research supervisor — read the surrounding lines rather than assuming. Pass `workers=worker_roster` to the `Application(...)` construction. Leave `extractions` unset; Task 9 supplies it.

- [ ] **Step 4: Pass it to the web app**

In `web.py`, add `workers=app.workers` to the `create_app(...)` call, alongside the existing `research=`/`activity=` arguments.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/application/test_workers.py tests/interfaces/test_web.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add research_team/composition.py web.py tests/application/test_workers.py
git commit -m "feat: wire the worker roster into both front ends"
```

---

## Task 4: The frontend worker model

Pure domain: the wire shape, the nesting, and the elapsed formatting. No React.

**Files:**
- Create: `frontend/src/domain/worker/worker.ts`, `frontend/src/domain/worker/worker.test.ts`
- Test: the same

**Interfaces:**
- Consumes: `SessionId`, `ProjectId` from `@domain/shared/identifier.ts`.
- Produces: `Worker`, `Roster`, `WorkerNode`, `nest`, `isBusy`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/domain/worker/worker.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { isBusy, nest, type Roster, type Worker } from './worker.ts'

const worker = (over: Partial<Worker> = {}): Worker => ({
  kind: 'turn',
  ref: 'ref',
  detail: 'turn 1',
  sessionId: null,
  parent: null,
  startedAt: null,
  ...over,
})

const roster = (over: Partial<Roster> = {}): Roster => ({
  projectId: ProjectId('11111111-1111-1111-1111-111111111111'),
  workers: [],
  idleSessionIds: [],
  ...over,
})

describe('nest', () => {
  it('hangs a child under the parent it names', () => {
    const run = worker({ kind: 'run', ref: 'run-1', detail: 'autonomous run' })
    const extraction = worker({ kind: 'extraction', ref: 'src-1', parent: 'run-1' })

    const tree = nest([run, extraction])

    expect(tree).toHaveLength(1)
    expect(tree[0].worker.ref).toBe('run-1')
    expect(tree[0].children.map((node) => node.worker.ref)).toEqual(['src-1'])
  })

  it('keeps a child whose parent is absent at the top level', () => {
    // The roster is polled, so a parent can vanish between the poll that
    // named it and this render. Dropping the child would hide live work.
    const orphan = worker({ kind: 'extraction', ref: 'src-1', parent: 'gone' })

    const tree = nest([orphan])

    expect(tree.map((node) => node.worker.ref)).toEqual(['src-1'])
  })

  it('preserves the order the server sent', () => {
    const tree = nest([worker({ ref: 'a' }), worker({ ref: 'b' }), worker({ ref: 'c' })])
    expect(tree.map((node) => node.worker.ref)).toEqual(['a', 'b', 'c'])
  })

  it('does not loop on a worker that parents itself', () => {
    // Not something the server should ever send. It must not hang a browser
    // if it does.
    const tree = nest([worker({ ref: 'a', parent: 'a' })])
    expect(tree.map((node) => node.worker.ref)).toEqual(['a'])
  })
})

describe('isBusy', () => {
  it('is false when nothing is working, whatever is attached', () => {
    expect(
      isBusy(roster({ idleSessionIds: [SessionId('22222222-2222-2222-2222-222222222222')] })),
    ).toBe(false)
  })

  it('is true as soon as there is one worker', () => {
    expect(isBusy(roster({ workers: [worker()] }))).toBe(true)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/domain/worker/worker.test.ts`
Expected: FAIL — cannot resolve `./worker.ts`

- [ ] **Step 3: Write the implementation**

Create `frontend/src/domain/worker/worker.ts`:

```ts
import type { ProjectId, SessionId } from '../shared/identifier.ts'

/** One thing working on a project right now.
 *
 * Everything here is process-local on the server: a restart shows an empty
 * roster, which is the truth rather than a gap. That is also why an empty
 * roster and a failed poll must not render the same — see `Workers.tsx`.
 */
export interface Worker {
  readonly kind: 'run' | 'turn' | 'extraction'
  /** Identifies this worker within the roster: a run id, a session id, or a
   *  source id. Text because the three are different kinds of identifier and
   *  `parent` has to compare across them. */
  readonly ref: string
  /** What it is doing, composed by the server so two front ends cannot
   *  disagree about how to say the same thing. */
  readonly detail: string
  /** The session whose transcript is this worker's detail view. Null for
   *  extraction, whose detail view is the extraction pane. */
  readonly sessionId: SessionId | null
  readonly parent: string | null
  /** Epoch milliseconds, or null when the server had no start time. */
  readonly startedAt: number | null
}

export interface Roster {
  readonly projectId: ProjectId
  readonly workers: readonly Worker[]
  readonly idleSessionIds: readonly SessionId[]
}

export interface WorkerNode {
  readonly worker: Worker
  readonly children: readonly WorkerNode[]
}

/** Whether anything is actually working, as distinct from attached. */
export const isBusy = (roster: Roster | null): boolean => (roster?.workers.length ?? 0) > 0

/** Arrange workers into the containment the server described.
 *
 * A child whose parent is not present stays at the top level rather than being
 * dropped. The roster is polled, so a parent can disappear between the poll
 * that named it and this render, and a dropped child would hide live work —
 * the one thing this panel exists to prevent. A worker that names itself as
 * its own parent is treated the same way, so a bad server response cannot
 * produce a cycle here.
 */
export const nest = (workers: readonly Worker[]): readonly WorkerNode[] => {
  const present = new Set(workers.map((worker) => worker.ref))
  const children = new Map<string, Worker[]>()

  for (const worker of workers) {
    const parent = worker.parent
    if (parent === null || parent === worker.ref || !present.has(parent)) continue
    const siblings = children.get(parent)
    if (siblings) siblings.push(worker)
    else children.set(parent, [worker])
  }

  const nested = new Set(Array.from(children.values()).flat())

  return workers
    .filter((worker) => !nested.has(worker))
    .map((worker) => ({
      worker,
      children: (children.get(worker.ref) ?? []).map((child) => ({ worker: child, children: [] })),
    }))
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/domain/worker/worker.test.ts`
Expected: PASS — all six.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/domain/worker/
git commit -m "feat: the worker roster as a frontend domain model"
```

---

## Task 5: The roster repository

**Files:**
- Modify: `frontend/src/application/ports/repositories.ts` (add `WorkerRepository`), `frontend/src/infrastructure/http/dto.ts` (wire shape), `frontend/src/infrastructure/http/mappers.ts` (`toRoster`), `frontend/src/infrastructure/http/project-repository.ts` (`HttpWorkerRepository`), `frontend/src/app/container.ts` (register it), `frontend/src/application/queries/keys.ts` (`workers` key)
- Test: `frontend/src/infrastructure/http/mappers.test.ts` (append)

**Interfaces:**
- Consumes: `Roster`, `Worker` from Task 4.
- Produces: `WorkerRepository.on(projectId): Promise<Roster>`; `queryKeys.workers(projectId)`; `container.workers`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/infrastructure/http/mappers.test.ts`:

```ts
describe('toRoster', () => {
  it('maps the wire shape, parsing timestamps to epoch milliseconds', () => {
    const roster = toRoster({
      project_id: '11111111-1111-1111-1111-111111111111',
      workers: [
        {
          kind: 'run',
          ref: 'run-1',
          detail: 'autonomous run',
          session_id: '22222222-2222-2222-2222-222222222222',
          parent: null,
          started_at: '2026-08-07T12:00:00+00:00',
        },
      ],
      idle_session_ids: ['33333333-3333-3333-3333-333333333333'],
    })

    expect(roster.workers[0].kind).toBe('run')
    expect(roster.workers[0].sessionId).toBe('22222222-2222-2222-2222-222222222222')
    expect(roster.workers[0].startedAt).toBe(Date.parse('2026-08-07T12:00:00+00:00'))
    expect(roster.idleSessionIds).toEqual(['33333333-3333-3333-3333-333333333333'])
  })

  it('keeps a null start time null rather than turning it into now', () => {
    // A worker with no start time must not render as "0s elapsed", which
    // reads as having just begun.
    const roster = toRoster({
      project_id: '11111111-1111-1111-1111-111111111111',
      workers: [
        {
          kind: 'extraction',
          ref: 'src-1',
          detail: 'extracting',
          session_id: null,
          parent: 'run-1',
          started_at: null,
        },
      ],
      idle_session_ids: [],
    })

    expect(roster.workers[0].startedAt).toBeNull()
    expect(roster.workers[0].sessionId).toBeNull()
  })
})
```

Add `toRoster` to the file's existing import from `./mappers.ts`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/infrastructure/http/mappers.test.ts`
Expected: FAIL — `toRoster` is not exported

- [ ] **Step 3: Add the DTO**

In `frontend/src/infrastructure/http/dto.ts`, following the file's existing naming:

```ts
export interface WorkerDto {
  readonly kind: string
  readonly ref: string
  readonly detail: string
  readonly session_id: string | null
  readonly parent: string | null
  readonly started_at: string | null
}

export interface RosterDto {
  readonly project_id: string
  readonly workers: readonly WorkerDto[]
  readonly idle_session_ids: readonly string[]
}
```

- [ ] **Step 4: Add the mapper**

In `frontend/src/infrastructure/http/mappers.ts`:

```ts
/** An ISO-8601 timestamp as epoch milliseconds, or null.
 *
 * Null stays null rather than defaulting to now: a worker with no start time
 * would otherwise render as "0s elapsed", which reads as having just begun.
 */
const toEpoch = (raw: string | null): number | null => {
  if (!raw) return null
  const parsed = Date.parse(raw)
  return Number.isNaN(parsed) ? null : parsed
}

export const toRoster = (dto: RosterDto): Roster => ({
  projectId: ProjectId(dto.project_id),
  workers: dto.workers.map((worker) => ({
    // The server's vocabulary, narrowed. An unrecognised kind renders as a
    // plain row rather than being dropped: a worker this build cannot label
    // is still a worker, and hiding it is the failure mode that matters.
    kind: worker.kind === 'run' || worker.kind === 'extraction' ? worker.kind : 'turn',
    ref: worker.ref,
    detail: worker.detail,
    sessionId: worker.session_id ? SessionId(worker.session_id) : null,
    parent: worker.parent,
    startedAt: toEpoch(worker.started_at),
  })),
  idleSessionIds: dto.idle_session_ids.map((id) => SessionId(id)),
})
```

Add the imports it needs (`Roster` from `@domain/worker/worker.ts`, `RosterDto` from `./dto.ts`, `ProjectId`/`SessionId` if not already imported), following the file's existing grouping.

- [ ] **Step 5: Add the port, the adapter, the key, and the registration**

In `frontend/src/application/ports/repositories.ts`:

```ts
export interface WorkerRepository {
  /** Everything in flight on a project. Rejects when this build has no
   *  roster, which a caller must distinguish from an empty one. */
  on(projectId: ProjectId): Promise<Roster>
}
```

In `frontend/src/infrastructure/http/project-repository.ts`, beside `HttpResearchRepository`:

```ts
export class HttpWorkerRepository implements WorkerRepository {
  constructor(private readonly http: HttpClient) {}

  async on(projectId: ProjectId): Promise<Roster> {
    return toRoster(await this.http.get<RosterDto>(`/api/projects/${projectId}/workers`))
  }
}
```

In `frontend/src/application/queries/keys.ts`, beside the existing `run` key:

```ts
  workers: (projectId: ProjectId) => ['workers', projectId] as const,
```

In `frontend/src/app/container.ts`, add `readonly workers: WorkerRepository` to `Container` and `workers: new HttpWorkerRepository(http),` to `createContainer`.

- [ ] **Step 6: Run the tests and the typechecker**

Run: `cd frontend && npx vitest run src/infrastructure/http/mappers.test.ts && npm run typecheck`
Expected: PASS, and a clean typecheck.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/application/ports/repositories.ts frontend/src/infrastructure/http/ frontend/src/app/container.ts frontend/src/application/queries/keys.ts
git commit -m "feat: read the worker roster over HTTP"
```

---

## Task 6: The `Workers` panel

**Files:**
- Create: `frontend/src/presentation/course/Workers.tsx`
- Modify: `frontend/src/presentation/course/CourseView.tsx` (mount it above the run panel, line ~66), `frontend/src/styles/course.css`
- Test: `frontend/src/presentation/course/Workers.test.tsx`

**Interfaces:**
- Consumes: `nest`, `isBusy`, `Roster` (Task 4); `container.workers`, `queryKeys.workers` (Task 5).
- Produces: `<Workers projectId watching onWatch />` — `watching: SessionId | null`, `onWatch: (sessionId: SessionId | null) => void`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/presentation/course/Workers.test.tsx`. Read `frontend/src/application/lesson/use-attempts.test.tsx` first and reuse its render harness (QueryClientProvider + container context) rather than building a new one.

```tsx
import { render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import type { Roster } from '@domain/worker/worker.ts'

import { Workers } from './Workers.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

const empty: Roster = { projectId: PROJECT, workers: [], idleSessionIds: [] }

it('names the work in flight and offers it as a button', async () => {
  const workers = {
    on: vi.fn().mockResolvedValue({
      ...empty,
      workers: [
        {
          kind: 'turn' as const,
          ref: SESSION,
          detail: 'turn 12',
          sessionId: SESSION,
          parent: null,
          startedAt: null,
        },
      ],
    }),
  }

  renderWithContainer(<Workers projectId={PROJECT} watching={null} onWatch={() => {}} />, {
    workers,
  })

  expect(await screen.findByText('turn 12')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /turn 12/ })).toBeInTheDocument()
})

it('says nothing is running rather than showing an empty box', async () => {
  const workers = { on: vi.fn().mockResolvedValue(empty) }

  renderWithContainer(<Workers projectId={PROJECT} watching={null} onWatch={() => {}} />, {
    workers,
  })

  expect(await screen.findByText(/nothing is running/i)).toBeInTheDocument()
})

it('keeps the last roster and marks it stale when a poll fails', async () => {
  // The load-bearing case. Emptying the panel on a failed poll would say
  // "nothing is running", which is the exact lie this panel exists to kill.
  const workers = {
    on: vi
      .fn()
      .mockResolvedValueOnce({
        ...empty,
        workers: [
          {
            kind: 'run' as const,
            ref: 'run-1',
            detail: 'autonomous run',
            sessionId: SESSION,
            parent: null,
            startedAt: null,
          },
        ],
      })
      .mockRejectedValue(new Error('network')),
  }

  const { rerender } = renderWithContainer(
    <Workers projectId={PROJECT} watching={null} onWatch={() => {}} />,
    { workers },
  )

  expect(await screen.findByText('autonomous run')).toBeInTheDocument()

  await triggerRefetch(rerender)

  await waitFor(() => expect(screen.getByText(/stale/i)).toBeInTheDocument())
  expect(screen.getByText('autonomous run')).toBeInTheDocument()
})

it('indents a nested extraction under its parent', async () => {
  const workers = {
    on: vi.fn().mockResolvedValue({
      ...empty,
      workers: [
        {
          kind: 'run' as const,
          ref: 'run-1',
          detail: 'autonomous run',
          sessionId: SESSION,
          parent: null,
          startedAt: null,
        },
        {
          kind: 'extraction' as const,
          ref: 'src-1',
          detail: 'consolidating 7/23',
          sessionId: null,
          parent: 'run-1',
          startedAt: null,
        },
      ],
    }),
  }

  renderWithContainer(<Workers projectId={PROJECT} watching={null} onWatch={() => {}} />, {
    workers,
  })

  const nested = await screen.findByText('consolidating 7/23')
  expect(nested.closest('.worker-child')).not.toBeNull()
})
```

Implement `renderWithContainer` and `triggerRefetch` as local helpers in this file, modelled on the existing test harness. `triggerRefetch` should invalidate the `workers` query on the test's `QueryClient`.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/course/Workers.test.tsx`
Expected: FAIL — cannot resolve `./Workers.tsx`

- [ ] **Step 3: Write the panel**

Create `frontend/src/presentation/course/Workers.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import { isBusy, nest, type WorkerNode } from '@domain/worker/worker.ts'
import { shortId, type ProjectId, type SessionId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'

const POLL_MS = 2_000

/** Everything working on this project, right now.
 *
 * Polled rather than pushed: the roster is process-local state on the server,
 * and pushing it would mean making the session-keyed activity buffer
 * project-aware. What the poll sets the latency of is "a new worker appeared";
 * everything *inside* a worker arrives over the live feed.
 *
 * The one rule this component must not break: **a failed poll keeps the last
 * roster and marks it stale.** Rendering empty would say "nothing is running",
 * which is the specific lie this panel exists to kill.
 */
export const Workers = ({
  projectId,
  watching,
  onWatch,
}: {
  projectId: ProjectId
  watching: SessionId | null
  onWatch: (sessionId: SessionId | null) => void
}) => {
  const { workers } = useContainer()

  const roster = useQuery({
    queryKey: queryKeys.workers(projectId),
    queryFn: () => workers.on(projectId),
    refetchInterval: POLL_MS,
    // Keeping the previous data is what makes a failed poll stale rather than
    // empty. Retry is off so a failure is visible within one interval instead
    // of being hidden behind backoff.
    placeholderData: (previous) => previous,
    retry: false,
  })

  const current = roster.data ?? null
  const stale = roster.isError && current !== null

  if (!current && roster.isError) {
    return (
      <p className="sub worker-sub">
        Could not read what is running on this project. This build may not expose the roster.
      </p>
    )
  }

  return (
    <>
      <div className="worker-head">
        <h3 className="worker-title">Working now</h3>
        {stale ? (
          <Chip tone="run-short" title="The last poll failed; this is the last roster that arrived">
            stale
          </Chip>
        ) : isBusy(current) ? (
          <Chip tone="current">{current!.workers.length} running</Chip>
        ) : (
          <Chip>idle</Chip>
        )}
      </div>

      {current && current.workers.length > 0 ? (
        <ul className="worker-list">
          {nest(current.workers).map((node) => (
            <Row key={node.worker.ref} node={node} watching={watching} onWatch={onWatch} />
          ))}
        </ul>
      ) : (
        <p className="sub worker-sub">
          Nothing is running on this project.{' '}
          {current && current.idleSessionIds.length > 0
            ? `${current.idleSessionIds.length} session(s) attached and quiet.`
            : 'No sessions are attached.'}
        </p>
      )}
    </>
  )
}

const Row = ({
  node,
  watching,
  onWatch,
  nested = false,
}: {
  node: WorkerNode
  watching: SessionId | null
  onWatch: (sessionId: SessionId | null) => void
  nested?: boolean
}) => {
  const { worker } = node
  // Extraction opens the pane on the session that is hosting it, which is its
  // parent's. With no resolvable parent there is nothing to open, so the row
  // is text rather than a dead button.
  const target = worker.sessionId
  const open = worker.kind === 'extraction' ? watching : null

  return (
    <>
      <li className={nested ? 'worker-row worker-child' : 'worker-row'}>
        <span className={`worker-dot worker-dot-${worker.kind}`} aria-hidden="true" />
        <span className="worker-kind">{worker.kind}</span>
        {target ? (
          <button
            type="button"
            className="btn btn-sm worker-open"
            aria-pressed={watching === target}
            onClick={() => onWatch(watching === target ? null : target)}
          >
            {worker.detail}
          </button>
        ) : (
          <span className="worker-detail">{worker.detail}</span>
        )}
        {target ? <span className="muted worker-ref">{shortId(target)}</span> : null}
        {open ? null : null}
      </li>
      {node.children.map((child) => (
        <Row key={child.worker.ref} node={child} watching={watching} onWatch={onWatch} nested />
      ))}
    </>
  )
}
```

- [ ] **Step 4: Mount it and style it**

In `frontend/src/presentation/course/CourseView.tsx`, above the existing `run-panel` section (line ~66), add:

```tsx
      <section className="worker-panel" aria-label="Working now">
        <Workers projectId={projectId} watching={watching} onWatch={onWatch} />
      </section>
```

`watching` and `onWatch` come from the route in Task 8. Until then, thread `watching={null}` and `onWatch={() => {}}` from `CourseView`'s own props so this task compiles and is reviewable on its own.

In `frontend/src/styles/course.css`, add rules for `.worker-panel`, `.worker-head`, `.worker-title`, `.worker-list`, `.worker-row`, `.worker-child` (indent with a left margin and a rule), `.worker-dot` plus a colour per kind, `.worker-kind`, `.worker-detail`, `.worker-ref`, `.worker-sub`. Use the existing custom properties from `tokens.css` — no new literal colours.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/presentation/course/Workers.test.tsx && npm run typecheck`
Expected: PASS, clean typecheck.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/presentation/course/Workers.tsx frontend/src/presentation/course/Workers.test.tsx frontend/src/presentation/course/CourseView.tsx frontend/src/styles/course.css
git commit -m "feat: show what is working on a course page"
```

---

## Task 7: The `watching` route segment

**Files:**
- Modify: `frontend/src/presentation/routing/routes.ts` (route shape, `parseRoute`, `courseHref`), `frontend/src/app/App.tsx` (pass it down), `frontend/src/presentation/course/CourseView.tsx` (accept and forward)
- Test: `frontend/src/presentation/routing/routes.test.ts` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: `Route` gains `watching: SessionId | null` on the `course` variant; `courseHref(projectId, watching?)`.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/presentation/routing/routes.test.ts`:

```ts
describe('the watched session', () => {
  it('reads a watched session out of the course route', () => {
    const route = parseRoute('#/p/11111111-1111-1111-1111-111111111111/course/watching/22222222-2222-2222-2222-222222222222')

    expect(route).toEqual({
      name: 'course',
      id: '11111111-1111-1111-1111-111111111111',
      watching: '22222222-2222-2222-2222-222222222222',
    })
  })

  it('leaves it null on a plain course route', () => {
    const route = parseRoute('#/p/11111111-1111-1111-1111-111111111111/course')
    expect(route).toEqual({
      name: 'course',
      id: '11111111-1111-1111-1111-111111111111',
      watching: null,
    })
  })

  it('ignores a watching segment with no session after it', () => {
    // A hand-truncated URL is still a course route. Falling through to the
    // tree would send somebody somewhere they did not ask for.
    const route = parseRoute('#/p/11111111-1111-1111-1111-111111111111/course/watching')
    expect(route).toEqual({
      name: 'course',
      id: '11111111-1111-1111-1111-111111111111',
      watching: null,
    })
  })

  it('round-trips through courseHref', () => {
    const href = courseHref(
      ProjectId('11111111-1111-1111-1111-111111111111'),
      SessionId('22222222-2222-2222-2222-222222222222'),
    )
    expect(parseRoute(href)).toEqual({
      name: 'course',
      id: '11111111-1111-1111-1111-111111111111',
      watching: '22222222-2222-2222-2222-222222222222',
    })
  })
})
```

Add `courseHref`, `ProjectId` and `SessionId` to the file's existing imports.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/routing/routes.test.ts`
Expected: FAIL — existing `course` routes have no `watching`, and `courseHref` may not take a second argument.

- [ ] **Step 3: Change the route**

In `frontend/src/presentation/routing/routes.ts`, change the `course` variant:

```ts
  | {
      readonly name: 'course'
      readonly id: ProjectId
      /** The session whose transcript is open in the drawer, or null.
       *
       * In the URL for the reason the scrub point and the open file are: a
       * reader watching one worker should be able to send somebody the exact
       * screen, and a reload should not close the drawer. A path segment
       * rather than a query string because this parser handles segments and
       * has no query handling at all. */
      readonly watching: SessionId | null
    }
```

In `parseRoute`, replace the course branch:

```ts
  if (parts[0] === 'p' && parts[1] && parts[2] === 'course') {
    // A truncated `watching` with no id after it is still a course route: a
    // hand-edited URL should drop the drawer, not send somebody to the tree.
    const watching = parts[3] === 'watching' && parts[4] ? SessionId(parts[4]) : null
    return { name: 'course', id: ProjectId(parts[1]), watching }
  }
```

Update `courseHref` (or add it, following how `sessionHref` is written):

```ts
export const courseHref = (projectId: ProjectId, watching: SessionId | null = null): string =>
  watching
    ? `#/p/${encodeURIComponent(projectId)}/course/watching/${encodeURIComponent(watching)}`
    : `#/p/${encodeURIComponent(projectId)}/course`
```

- [ ] **Step 4: Thread it through**

In `frontend/src/app/App.tsx`, where the `course` route renders `CourseView`, pass `watching={route.watching}` and an `onWatch` that navigates:

```tsx
        onWatch={(sessionId) => navigate(courseHref(route.id, sessionId))}
```

In `CourseView.tsx`, accept `watching: SessionId | null` and `onWatch: (sessionId: SessionId | null) => void` as props and forward both to `<Workers>` (replacing the placeholders from Task 6).

Fix any other call site of `courseHref` or construction of a `course` route that the typechecker flags.

- [ ] **Step 5: Run the tests and the typechecker**

Run: `cd frontend && npx vitest run src/presentation/routing/routes.test.ts && npm run typecheck`
Expected: PASS, clean typecheck.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/presentation/routing/ frontend/src/app/App.tsx frontend/src/presentation/course/CourseView.tsx
git commit -m "feat: the watched session is in the URL"
```

---

## Task 8: The drawer

**Files:**
- Create: `frontend/src/presentation/course/WorkerDrawer.tsx`
- Modify: `frontend/src/presentation/course/CourseView.tsx` (render it), `frontend/src/styles/course.css`
- Test: `frontend/src/presentation/course/WorkerDrawer.test.tsx`

**Interfaces:**
- Consumes: `createSessionStore` (`@application/session/session-store.ts`), `useSessionStream`, `Conversation`, `ActivityFeed`, `currentView`.
- Produces: `<WorkerDrawer sessionId onClose />`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/presentation/course/WorkerDrawer.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SessionId } from '@domain/shared/identifier.ts'

import { WorkerDrawer } from './WorkerDrawer.tsx'

const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

it('opens the session it was given', async () => {
  const open = vi.fn().mockResolvedValue(undefined)

  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />, { open })

  expect(open).toHaveBeenCalledWith(SESSION, expect.anything())
})

it('closes on escape', async () => {
  const onClose = vi.fn()

  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={onClose} />)
  await userEvent.keyboard('{Escape}')

  expect(onClose).toHaveBeenCalled()
})

it('offers no composer, because it is for watching', () => {
  // Typing into a session you opened in order to observe is a different
  // intention, and it should cost a navigation.
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  expect(screen.queryByRole('textbox')).toBeNull()
})

it('links out to the session rather than answering an approval in place', () => {
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />, {
    approvals: [{ approvalId: 'a-1', tool: 'fetch' }],
  })

  const link = screen.getByRole('link', { name: /open the session/i })
  expect(link).toHaveAttribute('href', expect.stringContaining(SESSION))
})

it('closes the store it opened when it unmounts', () => {
  const close = vi.fn()

  const { unmount } = renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />, {
    close,
  })
  unmount()

  expect(close).toHaveBeenCalled()
})
```

Write a `renderDrawer` helper in this file that supplies a fake session store (a zustand-shaped object whose `getState()` returns the injected `open`/`close` and a minimal `SessionState`) plus the container context, and injects it via the component's `makeStore` prop (see Step 3).

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/course/WorkerDrawer.test.tsx`
Expected: FAIL — cannot resolve `./WorkerDrawer.tsx`

- [ ] **Step 3: Write the drawer**

Create `frontend/src/presentation/course/WorkerDrawer.tsx`:

```tsx
import { useEffect, useMemo } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import { createSessionStore, currentView, type SessionStore } from '@application/session/session-store.ts'
import { useContainer } from '@app/container-context.tsx'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { shortId, type SessionId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'
import { ActivityFeed } from '../session/ActivityFeed.tsx'
import { Conversation } from '../session/Conversation.tsx'
import { useSessionStream } from '../session/use-session-stream.ts'

/** A worker's real transcript, over the course page.
 *
 * Builds **its own** session store rather than borrowing the shell's, which
 * belongs to the session route: `createSessionStore` is a factory, so two
 * stores over the same log cost one extra subscription and cannot interfere.
 * The store is closed on unmount.
 *
 * **Read-only, deliberately.** No composer, and a pending approval links out
 * rather than being answerable here. Typing into a session you opened in order
 * to observe is a different intention and should cost a navigation. (An
 * unattended run does not produce approvals at all — the driver floors `fetch`
 * at `ask` and works read-only precisely so it cannot deadlock on one — so a
 * pending approval belongs to a human's joined session, and to whoever is
 * driving it.)
 */
export const WorkerDrawer = ({
  sessionId,
  onClose,
  makeStore = createSessionStore,
}: {
  sessionId: SessionId
  onClose: () => void
  /** Injected so a test can drive the drawer without a real store. */
  makeStore?: typeof createSessionStore
}) => {
  const container = useContainer()

  const store: SessionStore = useMemo(
    () =>
      makeStore({
        sessions: container.sessions,
        turns: container.turns,
        approvals: container.approvals,
        now: container.now,
        notify,
      }),
    [container, makeStore],
  )

  useEffect(() => {
    void store.getState().open(sessionId, ScrubPoint.head())
    return () => store.getState().close()
  }, [sessionId, store])

  useSessionStream(store)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const state = store()
  const view = currentView(state)
  const pending = state.approvals.length > 0

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-label={`Watching session ${shortId(sessionId)}`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-head">
          <h3 className="drawer-title">Watching {shortId(sessionId)}</h3>
          {pending ? (
            <Chip tone="run-short" title="Answering it belongs to whoever is driving that session">
              waiting on an approval
            </Chip>
          ) : null}
          <span className="drawer-spacer" />
          <a className="btn btn-sm" href={sessionHref(sessionId)}>
            Open the session
          </a>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="drawer-body">
          <Conversation store={store} view={view} />
          <ActivityFeed store={store} />
        </div>
      </aside>
    </div>
  )
}
```

Match `Conversation`'s and `ActivityFeed`'s **actual** props — read both components and pass what they take. If either requires something the drawer has no business supplying (a scrub handler, a composer callback), pass a no-op and comment why rather than widening the component's contract.

- [ ] **Step 4: Render it**

In `CourseView.tsx`, after the existing panes:

```tsx
      {watching ? <WorkerDrawer sessionId={watching} onClose={() => onWatch(null)} /> : null}
```

In `course.css`, add `.drawer-backdrop` (fixed, full-viewport, translucent), `.drawer` (right-anchored panel, `max-width` in relative units, its own scroll), `.drawer-head`, `.drawer-title`, `.drawer-spacer`, `.drawer-body`. Use `tokens.css` custom properties. Add a `@media` rule in `responsive.css` making the drawer full-width on a narrow viewport.

- [ ] **Step 5: Run the tests**

Run: `cd frontend && npx vitest run src/presentation/course/ && npm run typecheck`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/presentation/course/WorkerDrawer.tsx frontend/src/presentation/course/WorkerDrawer.test.tsx frontend/src/presentation/course/CourseView.tsx frontend/src/styles/
git commit -m "feat: a read-only drawer for watching a worker"
```

---

## Task 9: Build and commit the console

Part A is complete and usable at this point. `web.py` serves committed build output, so the change has to be built to be real.

**Files:**
- Modify: `research_team/interfaces/web/static/**` (build output)

- [ ] **Step 1: Run the full frontend verification**

Run: `cd frontend && npm run verify`
Expected: PASS — format, lint, typecheck, coverage, build, size.

- [ ] **Step 2: Run the Python suite**

Run: `uv run pytest`
Expected: PASS.

- [ ] **Step 3: Look at it**

Run: `uv run web.py`, open a project's course page, and confirm: the panel says "Nothing is running" with the attached session count; starting a run makes a `run` row and a `turn` row appear within 2s; clicking the turn row opens the drawer with the live transcript; Escape closes it; a reload with the drawer open reopens it.

- [ ] **Step 4: Commit**

```bash
git add research_team/interfaces/web/static
git commit -m "build: the console, with the worker roster and drawer"
```

---

# Part B — extraction telemetry

## Task 10: The reporter port

**Files:**
- Modify: `research_team/application/knowledge.py` (`ExtractionNote`, `ExtractionReporter`, `ingest` signature), `research_team/application/__init__.py` (export)
- Test: `tests/application/test_knowledge.py` (append)

**Interfaces:**
- Consumes: nothing.
- Produces: `ExtractionNote`, `ExtractionReporter`; `KnowledgePort.ingest(source, *, report=None)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/application/test_knowledge.py`:

```python
def test_an_extraction_note_defaults_everything_it_does_not_know():
    """A note carries only what its stage actually established.

    Counts default to None rather than 0 because the difference matters: a
    `storing` note has no entity count, and reporting one as `0` would say
    extraction found nothing.
    """
    from research_team.application.knowledge import ExtractionNote

    note = ExtractionNote(source_id="notes", stage="storing")

    assert note.entities is None
    assert note.relationships is None
    assert note.domain_confidence is None
    assert note.index is None
    assert note.detail == ""


def test_a_note_keeps_a_zero_confidence_distinct_from_an_absent_one():
    """`0.0` means the classifier gave up; `None` means none ran.

    Collapsing them would report a fallback as a confident choice, which is
    the one thing `IngestReport.domain_confidence` exists to prevent.
    """
    from research_team.application.knowledge import ExtractionNote

    gave_up = ExtractionNote(source_id="n", stage="extracted", domain="x", domain_confidence=0.0)
    never_ran = ExtractionNote(source_id="n", stage="extracted", domain="x")

    assert gave_up.domain_confidence == 0.0
    assert never_ran.domain_confidence is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/application/test_knowledge.py -k extraction_note -v`
Expected: FAIL — `ImportError: cannot import name 'ExtractionNote'`

- [ ] **Step 3: Add the types**

In `research_team/application/knowledge.py`, add near the top (after `SourceRef`), and add `Callable` and `Literal` to the existing imports:

```python
ExtractionStage = Literal[
    "storing", "extracting", "extracted", "consolidating", "consolidated", "failed"
]


@dataclass(frozen=True)
class ExtractionNote:
    """Where one `remember` call has got to.

    **Provisional, and never a domain event.** The log is the replay
    substrate: `rebuild_graph` refuses to serve a partial graph and forbids
    model calls on the replay path, so that a session refolded years from now
    does not depend on a live endpoint. Progress is not a fact about the
    domain -- it is a fact about one attempt, at one moment, that a later
    reader has no use for and cannot act on. `DocumentExtracted` and
    `EntitiesMerged` remain the entire durable record.

    Every count defaults to None rather than 0, because the two say different
    things: a `storing` note has established no entity count, and reporting
    one as `0` would claim extraction found nothing.
    """

    source_id: str
    stage: ExtractionStage
    detail: str = ""
    """Free text for the stage: the entity being consolidated, or why it
    failed. Never the document's own content."""
    entities: int | None = None
    relationships: int | None = None
    domain: str | None = None
    domain_confidence: float | None = None
    """`0.0` means the classifier gave up and fell back; `None` means no
    classifier ran. Kept distinct for the reason `IngestReport` keeps them
    distinct -- a fallback is otherwise indistinguishable from a confident
    choice."""
    index: int | None = None
    """Which item of `total` this note is about, 1-based."""
    total: int | None = None
    model_calls: int | None = None
    """Model calls made so far in this ingest. Calls rather than chunks: the
    chunk count is not knowable before extraction runs, and a denominator
    invented here would be a number nobody could check."""


#: Told where an ingest has got to. Synchronous and must not raise -- see
#: `KnowledgePort.ingest`.
ExtractionReporter = Callable[[ExtractionNote], None]
```

Change the protocol method:

```python
    async def ingest(
        self, source: SourceRef, *, report: ExtractionReporter | None = None
    ) -> IngestReport:
```

and add to its docstring:

```
        `report`, when given, is told where the ingest has got to. It is
        called synchronously and **an implementation must not let it fail the
        ingest**: a listener that raises must not cost a document that has
        already been fetched and paid for. Optional so every existing caller
        is unaffected.
```

- [ ] **Step 4: Export the names**

Add `ExtractionNote`, `ExtractionReporter` and `ExtractionStage` to `research_team/application/__init__.py`'s imports and `__all__`.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/application/test_knowledge.py tests/test_architecture.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add research_team/application/knowledge.py research_team/application/__init__.py tests/application/test_knowledge.py
git commit -m "feat: a reporter port for extraction progress"
```

---

## Task 11: Instrument the adapter

The valuable task. A real ingest over a fake provider and an in-memory graph store, asserting the note sequence.

**Files:**
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py`
- Test: `tests/infrastructure/test_redstring_adapter.py` (append)

**Interfaces:**
- Consumes: `ExtractionNote`, `ExtractionReporter` (Task 10).
- Produces: `RedstringKnowledge.ingest(source, *, report=None)` emitting the documented stage sequence.

- [ ] **Step 1: Write the failing test**

Append to `tests/infrastructure/test_redstring_adapter.py`. The `build_adapter` fixture already exists at the top of this file — reuse it.

```python
@pytest.mark.asyncio
async def test_ingest_reports_its_stages_in_order(tmp_path, build_adapter):
    """The stage sequence, pinned.

    This is what stops a refactor from quietly silencing the pane: the
    sequence is the contract, not the individual calls.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    stages = [note.stage for note in notes]
    assert stages[0] == "storing"
    assert stages[1] == "extracting"
    assert "extracted" in stages
    assert stages[-1] == "consolidated"
    # Consolidation is per entity, and the fake extracts two.
    consolidating = [note for note in notes if note.stage == "consolidating"]
    assert [note.index for note in consolidating] == [1, 2]
    assert all(note.total == 2 for note in consolidating)
    assert all(note.source_id == "notes" for note in notes)


@pytest.mark.asyncio
async def test_the_extracted_note_carries_the_counts_and_the_schema(tmp_path, build_adapter):
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    extracted = next(note for note in notes if note.stage == "extracted")
    assert extracted.entities == report.entity_count
    assert extracted.relationships == report.relationship_count
    assert extracted.domain == report.domain


@pytest.mark.asyncio
async def test_model_calls_are_counted_from_inside_extraction(tmp_path, build_adapter):
    """`build_graph` takes no callbacks, so the provider is the way in.

    Without this the pane has nothing to show during the longest part of an
    ingest, and a slow model looks identical to a hung one.
    """
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=notes.append,
    )

    counted = [note.model_calls for note in notes if note.model_calls]
    assert counted, "no note reported a model call"
    assert max(counted) >= 1


@pytest.mark.asyncio
async def test_a_reporter_that_raises_does_not_fail_the_ingest(tmp_path, build_adapter):
    """A listener must not cost a document already fetched and paid for."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)

    def explode(note):
        raise RuntimeError("the listener is broken")

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage."),
        report=explode,
    )

    assert report.entity_count > 0


@pytest.mark.asyncio
async def test_a_failed_extraction_reports_a_failed_stage(tmp_path, build_adapter):
    """The pane must be able to say "it broke", not just stop updating."""
    project_id = uuid4()
    adapter, _, _ = build_adapter(tmp_path, project_id)
    notes = []

    with pytest.raises(KnowledgeError):
        await adapter.ingest(
            SourceRef(source_id="notes", text="x" * 200_001), report=notes.append
        )

    assert notes[-1].stage == "failed"
    assert notes[-1].detail
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -k "stages or model_calls or reporter or failed_stage or schema" -v`
Expected: FAIL — `ingest() got an unexpected keyword argument 'report'`

- [ ] **Step 3: Add the reporting provider and the report points**

In `research_team/infrastructure/knowledge/redstring_adapter.py`, add after the imports:

```python
class _CountingProvider:
    """An `LlmProvider` that says how many calls have been made through it.

    `build_graph` takes no callbacks and is one opaque await containing domain
    classification, chunking and a call per chunk -- the longest part of an
    ingest, and the part a watcher most needs to see moving. `LlmProvider` is
    a single-method protocol, so wrapping it is the whole cost of getting
    inside.

    It counts **calls, not chunks.** The chunk count is not knowable before
    extraction runs, and "chunk 4 of 9" would be a denominator invented here
    that nobody could check.
    """

    def __init__(self, inner: LlmProvider, announce) -> None:
        self._inner = inner
        self._announce = announce
        self._calls = 0

    @property
    def model(self) -> str:
        return self._inner.model

    @property
    def calls(self) -> int:
        return self._calls

    async def extract(self, text, schema, *, system_prompt=None):
        self._calls += 1
        self._announce(self._calls)
        return await self._inner.extract(text, schema, system_prompt=system_prompt)
```

Add a module-level helper:

```python
def _reporting(report: ExtractionReporter | None, source_id: str):
    """A guarded `report`, or a no-op.

    Guarded rather than trusted: a listener that raises must not cost a
    document that has already been fetched and paid for. Same posture as
    `AutoResearchDriver._record_look`, and for the same reason -- the work is
    what matters, the telling about it is not.
    """

    def announce(stage: str, **fields: Any) -> None:
        if report is None:
            return
        try:
            report(ExtractionNote(source_id=source_id, stage=stage, **fields))
        except Exception:  # noqa: BLE001 -- see the docstring
            logger.warning("an extraction reporter raised; carrying on", exc_info=True)

    return announce
```

Add `import logging` and `logger = logging.getLogger(__name__)` if the module lacks them, and import `ExtractionNote` and `ExtractionReporter` from `research_team.application.knowledge`.

Change `ingest`'s signature to `async def ingest(self, source: SourceRef, *, report: ExtractionReporter | None = None) -> IngestReport:` and thread the announcements through:

- Build `announce = _reporting(report, source.source_id)` immediately after the two validation raises. **After**, so a blank `source_id` still raises before anything is announced about a document that has no identity.
- Wrap the blank-id and length raises' bodies unchanged; then for the rest of the method, wrap the whole `try` so a `KnowledgeError` announces `failed` with `str(error)` before re-raising. The length cap raise happens before `announce` exists, so announce that one explicitly: restructure so `announce` is built first from `source.source_id` **after** the blank check, and the length check announces `failed` before raising.
- `announce("storing")` after `await self._store_document(source)`.
- `announce("extracting")` before `build_graph`.
- Wrap the provider: `counting = _CountingProvider(self._provider, lambda calls: announce("extracting", model_calls=calls))`, and pass `provider=counting` to `build_graph`. Pass `counting` to the adjudicator path too if the adjudicator is constructed per-ingest; if it is constructed in `__init__` (it is), leave it — the adjudicator's calls go through the provider given at construction, so note in a comment that adjudicator calls are not counted and why that is acceptable (they are per-merge and already reported by the `consolidating` notes).
- After `build_graph` returns and the `report.event is None` early-return is handled: `announce("extracted", entities=len(report.event.entities), relationships=len(report.event.relationships), domain=report.domain, domain_confidence=report.domain_confidence)`. For the `report.event is None` branch, announce `extracted` with `entities=0, relationships=0` and the domain, then `consolidated`, before returning — a no-op re-ingest must still close its pane.
- Pass `announce` into `_consolidate` and, in its per-entity loop, `announce("consolidating", index=position, total=len(entities), detail=entity.name)` before each `resolve`, and after a merge lands `announce("consolidating", index=position, total=len(entities), detail=f"{canonical} absorbed {absorbed} -- {reason}")`. Read `_consolidate`'s existing body and keep its failure handling exactly as it is; only add announcements.
- `announce("consolidated", entities=..., relationships=...)` immediately before the final `return IngestReport(...)`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -v`
Expected: PASS — the new tests and every pre-existing test in the file, unchanged.

- [ ] **Step 5: Confirm the tool text has not moved**

Run: `uv run pytest tests/infrastructure/test_knowledge_tools.py -v`
Expected: PASS. If anything here fails, `format_ingest`'s output has changed and the change must be undone — a global constraint.

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/knowledge/redstring_adapter.py tests/infrastructure/test_redstring_adapter.py
git commit -m "feat: report where an extraction has got to"
```

---

## Task 12: `ExtractionActivity`

**Files:**
- Create: `research_team/interfaces/web/extraction.py`
- Test: `tests/interfaces/test_extraction_activity.py`

**Interfaces:**
- Consumes: `ExtractionNote` (Task 10), `ExtractionSnapshot` (Task 1).
- Produces: `EXTRACTION` frame type; `ExtractionActivity` with `reporter(project_id)`, `in_flight(project_id)`, `current(project_id)`, `last(project_id)`, `listen()`, `stop_listening(queue)`.

- [ ] **Step 1: Write the failing test**

Create `tests/interfaces/test_extraction_activity.py`. Read `tests/interfaces/test_turn_activity.py` first and follow its shape.

```python
from uuid import uuid4

import pytest

from research_team.application.knowledge import ExtractionNote
from research_team.interfaces.web.extraction import EXTRACTION, ExtractionActivity


def note(**over) -> ExtractionNote:
    return ExtractionNote(**{"source_id": "notes", "stage": "extracting", **over})


def test_a_reporter_broadcasts_to_every_listener():
    activity = ExtractionActivity()
    project_id = uuid4()
    one, two = activity.listen(), activity.listen()

    activity.reporter(project_id)(note())

    for queue in (one, two):
        frame = queue.get_nowait()
        assert frame["type"] == EXTRACTION
        assert frame["project_id"] == str(project_id)
        assert frame["stage"] == "extracting"


def test_in_flight_answers_the_roster_with_the_latest_stage():
    activity = ExtractionActivity()
    project_id = uuid4()
    report = activity.reporter(project_id)

    report(note(stage="storing"))
    report(note(stage="consolidating", index=7, total=23, detail="Roediger"))

    snapshot = activity.in_flight(project_id)
    assert snapshot is not None
    assert snapshot.source_id == "notes"
    assert snapshot.stage == "consolidating"
    assert (snapshot.index, snapshot.total) == (7, 23)
    assert snapshot.detail == "Roediger"


def test_a_finished_extraction_is_no_longer_in_flight_but_is_still_readable():
    """The catch-up route must be able to show the last one.

    A pane that emptied the moment an extraction finished would throw away
    the only summary of what just happened.
    """
    activity = ExtractionActivity()
    project_id = uuid4()
    report = activity.reporter(project_id)

    report(note(stage="extracting"))
    report(note(stage="consolidated", entities=2, relationships=1))

    assert activity.in_flight(project_id) is None
    assert activity.current(project_id) == []
    last = activity.last(project_id)
    assert last and last[-1]["stage"] == "consolidated"


def test_a_failed_extraction_is_kept_rather_than_dropped():
    """What streamed is the only trace of it that exists.

    Same reasoning as `TurnActivity.discarded`: nothing durable was written,
    so discarding the frames would discard the whole record.
    """
    activity = ExtractionActivity()
    project_id = uuid4()
    report = activity.reporter(project_id)

    report(note(stage="extracting"))
    report(note(stage="failed", detail="the model refused"))

    assert activity.in_flight(project_id) is None
    last = activity.last(project_id)
    assert last and last[-1]["stage"] == "failed"
    assert last[-1]["detail"] == "the model refused"


def test_a_new_extraction_replaces_what_the_last_one_left_running():
    activity = ExtractionActivity()
    project_id = uuid4()
    report = activity.reporter(project_id)

    report(note(source_id="first", stage="extracting"))
    report(note(source_id="second", stage="storing"))

    snapshot = activity.in_flight(project_id)
    assert snapshot is not None and snapshot.source_id == "second"
    assert [frame["source_id"] for frame in activity.current(project_id)] == ["second"]


def test_projects_do_not_see_each_other():
    activity = ExtractionActivity()
    mine, theirs = uuid4(), uuid4()

    activity.reporter(mine)(note())

    assert activity.in_flight(mine) is not None
    assert activity.in_flight(theirs) is None


def test_a_listener_that_has_stopped_gets_nothing_more():
    activity = ExtractionActivity()
    project_id = uuid4()
    queue = activity.listen()
    activity.stop_listening(queue)

    activity.reporter(project_id)(note())

    assert queue.empty()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/interfaces/test_extraction_activity.py -v`
Expected: FAIL — `ModuleNotFoundError: research_team.interfaces.web.extraction`

- [ ] **Step 3: Write the module**

Create `research_team/interfaces/web/extraction.py`:

```python
"""Where an extraction has got to, while it is getting there.

`remember` runs for minutes -- domain classification, a model call per chunk,
then a consolidation decision per entity -- and until now said nothing until
it finished. This is the channel that carries the middle.

Keyed by **project**, not session: extraction is a project-level fact, the
graph is tenant-scoped by project, and the adapter that produces these notes
is scoped to a project and knows nothing about sessions.

**Provisional, and never durable.** These frames carry no feed position, so
`Last-Event-ID` cannot replay them -- which is exactly why the buffer and the
catch-up route exist rather than being an optimisation. An SSE connection
drops routinely (sleep, a network change, a proxy closing an idle socket), and
without somewhere to catch up from a lossy reconnect would look identical to a
stalled extraction: a frozen pane either way.

Shaped deliberately like `activity.py`, which is itself shaped like
`approvals.py`. Three modules, one problem: content that matters now, leaves
no event behind, and has to survive a reconnect.
"""

import asyncio
from typing import Any
from uuid import UUID

from research_team.application.knowledge import ExtractionNote, ExtractionReporter
from research_team.application.workers import ExtractionSnapshot

EXTRACTION = "Extraction"
"""The frame type on the live feed.

PascalCase like the event names beside it, because the browser switches on one
`type` field for everything it receives. It is *not* a domain event and must
never become one -- the log has no such entry, and that is the point.
"""

#: Stages after which nothing more will arrive for that source.
_TERMINAL = ("consolidated", "failed")


class ExtractionActivity:
    """Extraction progress, keyed by project, plus the feed that carries it."""

    def __init__(self) -> None:
        self._running: dict[UUID, list[dict[str, Any]]] = {}
        self._finished: dict[UUID, list[dict[str, Any]]] = {}
        self._source: dict[UUID, str] = {}
        self._listeners: set[asyncio.Queue] = set()

    # ---------------- what the ingest drives ----------------

    def reporter(self, project_id: UUID) -> ExtractionReporter:
        """An `ExtractionReporter` that buffers and broadcasts for one project."""

        def report(note: ExtractionNote) -> None:
            self._record(project_id, note)

        return report

    # ---------------- what the roster and HTTP drive ----------------

    def in_flight(self, project_id: UUID) -> ExtractionSnapshot | None:
        """The running extraction as the roster wants it, or None.

        Satisfies `ExtractionsInFlight`. The latest note wins: a snapshot is
        "where it has got to", not a history.
        """
        frames = self._running.get(project_id)
        if not frames:
            return None
        latest = frames[-1]
        return ExtractionSnapshot(
            source_id=latest["source_id"],
            stage=latest["stage"],
            detail=latest.get("detail", ""),
            index=latest.get("index"),
            total=latest.get("total"),
        )

    def current(self, project_id: UUID) -> list[dict[str, Any]]:
        """The running extraction's frames, for a tab that arrived mid-ingest."""
        return list(self._running.get(project_id, []))

    def last(self, project_id: UUID) -> list[dict[str, Any]]:
        """The most recently finished extraction's frames.

        Kept rather than dropped for the reason `TurnActivity.discarded` keeps
        a failed turn's content: nothing durable records the stages, so these
        frames are the only account of what just happened, and a pane that
        emptied on completion would discard the summary a reader wants most.
        """
        return list(self._finished.get(project_id, []))

    # ---------------- the feed ----------------

    def listen(self) -> asyncio.Queue:
        """Subscribe to extraction frames.

        Unbounded, matching the approvals and activity feeds: a dropped frame
        leaves a gap in a progress account with nothing to reconcile it.
        """
        queue: asyncio.Queue = asyncio.Queue()
        self._listeners.add(queue)
        return queue

    def stop_listening(self, queue: asyncio.Queue) -> None:
        self._listeners.discard(queue)

    # ---------------- internals ----------------

    def _record(self, project_id: UUID, note: ExtractionNote) -> None:
        if self._source.get(project_id) != note.source_id:
            # A different document: whatever the last one left running is over,
            # and keeping its frames under the new source would attribute one
            # document's stages to another.
            self._running[project_id] = []
            self._source[project_id] = note.source_id

        frame = {
            "type": EXTRACTION,
            "project_id": str(project_id),
            "source_id": note.source_id,
            "stage": note.stage,
            "detail": note.detail,
            "entities": note.entities,
            "relationships": note.relationships,
            "domain": note.domain,
            "domain_confidence": note.domain_confidence,
            "index": note.index,
            "total": note.total,
            "model_calls": note.model_calls,
        }
        self._running.setdefault(project_id, []).append(frame)

        if note.stage in _TERMINAL:
            self._finished[project_id] = self._running.pop(project_id, [])
            self._source.pop(project_id, None)

        self._announce(frame)

    def _announce(self, payload: dict[str, Any]) -> None:
        for queue in self._listeners:
            queue.put_nowait(payload)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/interfaces/test_extraction_activity.py tests/test_architecture.py -v`
Expected: PASS — all seven, and the architecture suite green.

- [ ] **Step 5: Commit**

```bash
git add research_team/interfaces/web/extraction.py tests/interfaces/test_extraction_activity.py
git commit -m "feat: carry extraction progress on the live feed"
```

---

## Task 13: Wire extraction end to end

**Files:**
- Modify: `research_team/composition.py` (`build_application(extractions=...)`, `open_graph`, roster), `research_team/infrastructure/agent/knowledge_tools.py` (thread the reporter), `research_team/interfaces/web/app.py` (`create_app` parameter, catch-up route, third SSE listener), `web.py` (build and pass `ExtractionActivity`)
- Test: `tests/interfaces/test_web.py` (append), `tests/infrastructure/test_knowledge_tools.py` (append)

**Interfaces:**
- Consumes: `ExtractionActivity` (Task 12), `ExtractionReporter` (Task 10), `WorkerRoster` (Task 1).
- Produces: `GET /api/projects/{project_id}/extraction`; `create_app(..., extraction: ExtractionActivity | None = None)`; `build_application(..., extractions: ExtractionReporterFactory | None = None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/infrastructure/test_knowledge_tools.py`:

```python
@pytest.mark.asyncio
async def test_remember_passes_the_reporter_through_to_the_port():
    """The tool is the only caller of `ingest` in a real turn.

    A reporter that the composition root wires but the tool drops would leave
    the pane silent with nothing in the logs to say why.
    """
    seen = {}

    class RecordingKnowledge:
        async def ingest(self, source, *, report=None):
            seen["report"] = report
            return IngestReport(
                source_id=source.source_id,
                entity_count=0,
                relationship_count=0,
                domain=None,
                domain_confidence=None,
            )

    def reporter(note):
        pass

    tools = {tool.name: tool for tool in build_knowledge_tools(RecordingKnowledge(), report=reporter)}
    await tools[REMEMBER_TOOL].ainvoke({"source_id": "notes", "text": "some text"})

    assert seen["report"] is reporter
```

Match the file's existing conventions for invoking a tool and for the `IngestReport` import; read it first.

Append to `tests/interfaces/test_web.py`:

```python
@pytest.mark.asyncio
async def test_extraction_catch_up_is_empty_before_anything_runs(client):
    project_id = await make_project(client)

    response = await client.get(f"/api/projects/{project_id}/extraction")

    assert response.status_code == 200
    assert response.json() == {"current": [], "last": []}


@pytest.mark.asyncio
async def test_extraction_catch_up_shows_the_running_ingest(client, extraction):
    """A tab that arrived mid-ingest can catch up.

    The frames carry no feed position, so this route is the only way back to
    a pane's state after a reconnect.
    """
    project_id = await make_project(client)
    extraction.reporter(project_id)(
        ExtractionNote(source_id="notes", stage="consolidating", index=3, total=9)
    )

    response = await client.get(f"/api/projects/{project_id}/extraction")

    body = response.json()
    assert [frame["stage"] for frame in body["current"]] == ["consolidating"]
    assert body["current"][0]["total"] == 9
    assert body["last"] == []


@pytest.mark.asyncio
async def test_the_roster_shows_a_running_extraction(client, extraction):
    project_id = await make_project(client)
    extraction.reporter(project_id)(
        ExtractionNote(source_id="notes", stage="consolidating", index=3, total=9)
    )

    body = (await client.get(f"/api/projects/{project_id}/workers")).json()

    assert [worker["kind"] for worker in body["workers"]] == ["extraction"]
    assert body["workers"][0]["detail"] == "consolidating 3/9"
```

Add an `extraction` fixture beside the existing client fixture: build one `ExtractionActivity`, pass it to `create_app(extraction=...)` **and** to the `WorkerRoster` the fixture builds, and yield it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/interfaces/test_web.py -k extraction tests/infrastructure/test_knowledge_tools.py -k reporter -v`
Expected: FAIL — no `extraction` route; `build_knowledge_tools` takes no `report`.

- [ ] **Step 3: Thread the reporter through the tools**

In `research_team/infrastructure/agent/knowledge_tools.py`, add a keyword-only `report: ExtractionReporter | None = None` to `build_knowledge_tools`, and pass `report=report` at the `ingest` call inside the `remember` tool. Document why it is optional: a build with no web layer has nobody to tell.

- [ ] **Step 4: Wire composition**

In `research_team/composition.py`:

Add a type alias near the other injected callables:

```python
#: Makes the reporter one project's ingests should announce through. Injected
#: so this module names no web class: the buffer that satisfies it lives in
#: `interfaces`, and only a front end that has one supplies it.
ExtractionReporterFactory = Callable[[UUID], ExtractionReporter]
```

Add `extractions: ExtractionReporterFactory | None = None` to `build_application`'s keyword parameters, beside `approvals`.

Inside `open_graph`, after `knowledge` is built, pass the reporter into the tools:

```python
            *build_knowledge_tools(
                knowledge,
                report=extractions(target_project_id) if extractions is not None else None,
            ),
```

Pass the same collaborator to the roster built in Task 3, so `WorkerRoster` can nest a running extraction:

```python
    worker_roster = WorkerRoster(
        service, turns=turns, runs=research_supervisor, extractions=extraction_source
    )
```

`build_application` needs the buffer itself for the roster, not only its factory. Rather than two parameters for one collaborator, accept one: change the parameter to `extractions: ExtractionsInFlight | None = None` where the object also exposes `reporter(project_id)`, and document that `ExtractionActivity` satisfies both — `ExtractionsInFlight` for the roster and the reporter factory for the tools. Declare the combined protocol in `application/workers.py`:

```python
class ExtractionChannel(ExtractionsInFlight, Protocol):
    """Both halves of the extraction channel: what is running, and how to say so.

    One collaborator rather than two parameters, because they are two views of
    one buffer and a composition root that passed mismatched halves would show
    a roster that disagreed with its own pane.
    """

    def reporter(self, project_id: UUID): ...
```

Use `ExtractionChannel` as `build_application`'s parameter type, and export it from `research_team/application/__init__.py`.

- [ ] **Step 5: Wire the web layer**

In `research_team/interfaces/web/app.py`:

Add `extraction: ExtractionActivity | None = None` to `create_app`'s parameters and import `ExtractionActivity` from `research_team.interfaces.web.extraction`.

Add the catch-up route beside the workers route:

```python
    @app.get("/api/projects/{project_id}/extraction")
    async def get_extraction(project_id: UUID):
        """What the running extraction has done so far, and the last one's account.

        A tab that arrived mid-ingest, or one whose connection dropped, has no
        other way back: these frames carry no feed position, so
        `Last-Event-ID` cannot replay them. 200 with two empty lists when
        nothing has run -- an absent extraction is a state, not a missing
        resource.
        """
        await _require_project(project_id)
        if extraction is None:
            return {"current": [], "last": []}
        return {
            "current": extraction.current(project_id),
            "last": extraction.last(project_id),
        }
```

Add the third listener in `_sse`, following the `pump_activity` block exactly:

```python
    extracting = None
    if extraction is not None:
        extracting = extraction.listen()

        async def pump_extraction() -> None:
            while True:
                await queue.put(("extraction", await extracting.get()))

        pumps.append(asyncio.create_task(pump_extraction()))
```

Add `extraction` to the `_sse` signature, add `"extraction"` to the `if kind in ("approval", "activity")` tuple so the frame is emitted verbatim with no feed id, add `extraction.stop_listening(extracting)` wherever the existing teardown calls `stop_listening` for the other two, and pass `extraction=extraction` from the `/api/stream` route.

Extend `_sse`'s docstring to name the third channel alongside approvals and activity, giving the same reason: no event behind it, so no id, so a reconnecting browser refetches instead of replaying.

- [ ] **Step 6: Wire `web.py`**

In `web.py`, build one `ExtractionActivity`, pass it to `build_application(extractions=...)` and to `create_app(extraction=...)`. One instance, both places — two would give the roster and the pane different answers.

- [ ] **Step 7: Run the tests**

Run: `uv run pytest -v`
Expected: PASS — the whole suite, including `test_architecture.py`.

- [ ] **Step 8: Commit**

```bash
git add research_team/composition.py research_team/infrastructure/agent/knowledge_tools.py research_team/interfaces/web/app.py research_team/application/workers.py research_team/application/__init__.py web.py tests/
git commit -m "feat: wire extraction progress from the adapter to the feed"
```

---

## Task 14: The frontend extraction model

**Files:**
- Create: `frontend/src/domain/knowledge/extraction.ts`, `frontend/src/domain/knowledge/extraction.test.ts`

**Interfaces:**
- Produces: `ExtractionFrame`, `Extraction`, `StageEntry`, `emptyExtraction`, `applyNote`, `isExtractionFrame`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/domain/knowledge/extraction.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { applyNote, emptyExtraction, isExtractionFrame, type ExtractionFrame } from './extraction.ts'

const frame = (over: Partial<ExtractionFrame> = {}): ExtractionFrame => ({
  type: 'Extraction',
  projectId: '11111111-1111-1111-1111-111111111111',
  sourceId: 'notes',
  stage: 'extracting',
  detail: '',
  entities: null,
  relationships: null,
  domain: null,
  domainConfidence: null,
  index: null,
  total: null,
  modelCalls: null,
  ...over,
})

describe('applyNote', () => {
  it('records each stage once, in arrival order', () => {
    let extraction = emptyExtraction('notes')
    extraction = applyNote(extraction, frame({ stage: 'storing' }))
    extraction = applyNote(extraction, frame({ stage: 'extracting' }))
    extraction = applyNote(extraction, frame({ stage: 'extracting', modelCalls: 2 }))

    expect(extraction.stages.map((entry) => entry.stage)).toEqual(['storing', 'extracting'])
    expect(extraction.stage).toBe('extracting')
    expect(extraction.modelCalls).toBe(2)
  })

  it('keeps the counts and the schema from the extracted note', () => {
    const extraction = applyNote(
      emptyExtraction('notes'),
      frame({ stage: 'extracted', entities: 12, relationships: 30, domain: 'psychology', domainConfidence: 0.87 }),
    )

    expect(extraction.entities).toBe(12)
    expect(extraction.relationships).toBe(30)
    expect(extraction.domain).toBe('psychology')
    expect(extraction.domainConfidence).toBe(0.87)
  })

  it('keeps a zero confidence distinct from an absent one', () => {
    // 0.0 means the classifier gave up and fell back. Rendering that as
    // "no classifier ran" would present a fallback as a decision.
    const gaveUp = applyNote(
      emptyExtraction('notes'),
      frame({ stage: 'extracted', domain: 'psychology', domainConfidence: 0 }),
    )
    const neverRan = applyNote(
      emptyExtraction('notes'),
      frame({ stage: 'extracted', domain: 'psychology' }),
    )

    expect(gaveUp.domainConfidence).toBe(0)
    expect(neverRan.domainConfidence).toBeNull()
  })

  it('collects consolidation progress and the merges it reports', () => {
    let extraction = emptyExtraction('notes')
    extraction = applyNote(
      extraction,
      frame({ stage: 'consolidating', index: 1, total: 2, detail: 'Ada Lovelace' }),
    )
    extraction = applyNote(
      extraction,
      frame({
        stage: 'consolidating',
        index: 1,
        total: 2,
        detail: 'Ada Lovelace absorbed Ada -- name and structure agree',
      }),
    )

    expect(extraction.index).toBe(1)
    expect(extraction.total).toBe(2)
    expect(extraction.merges).toHaveLength(2)
    expect(extraction.merges[1]).toContain('absorbed')
  })

  it('marks a failure and keeps why', () => {
    const extraction = applyNote(
      emptyExtraction('notes'),
      frame({ stage: 'failed', detail: 'the model refused' }),
    )

    expect(extraction.failed).toBe(true)
    expect(extraction.stages.at(-1)?.detail).toBe('the model refused')
  })
})

describe('isExtractionFrame', () => {
  it('accepts an extraction frame and rejects anything else', () => {
    expect(isExtractionFrame({ type: 'Extraction' })).toBe(true)
    expect(isExtractionFrame({ type: 'TurnActivity' })).toBe(false)
    expect(isExtractionFrame(null)).toBe(false)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/domain/knowledge/extraction.test.ts`
Expected: FAIL — cannot resolve `./extraction.ts`

- [ ] **Step 3: Write the model**

Create `frontend/src/domain/knowledge/extraction.ts`:

```ts
/** Where one `remember` call has got to.
 *
 * Provisional: nothing durable records these stages, so a reconnect refetches
 * them from the catch-up route rather than replaying them off the feed. The
 * graph's own record is `DocumentExtracted` and `EntitiesMerged`, and neither
 * is visible here.
 */
export type ExtractionStage =
  | 'storing'
  | 'extracting'
  | 'extracted'
  | 'consolidating'
  | 'consolidated'
  | 'failed'

export interface ExtractionFrame {
  readonly type: 'Extraction'
  readonly projectId: string
  readonly sourceId: string
  readonly stage: ExtractionStage
  readonly detail: string
  readonly entities: number | null
  readonly relationships: number | null
  readonly domain: string | null
  /** `0` means the classifier gave up and fell back; `null` means none ran.
   *  Kept distinct because a fallback presented as a decision is the one
   *  misreading this field exists to prevent. */
  readonly domainConfidence: number | null
  readonly index: number | null
  readonly total: number | null
  readonly modelCalls: number | null
}

export interface StageEntry {
  readonly stage: ExtractionStage
  readonly detail: string
}

export interface Extraction {
  readonly sourceId: string
  readonly stage: ExtractionStage | null
  readonly stages: readonly StageEntry[]
  readonly entities: number | null
  readonly relationships: number | null
  readonly domain: string | null
  readonly domainConfidence: number | null
  readonly index: number | null
  readonly total: number | null
  readonly modelCalls: number | null
  /** Every consolidation line, in arrival order: the entity being considered,
   *  then the verdict and its reason. The judgement is the interesting part of
   *  an ingest, so it is kept in full rather than counted. */
  readonly merges: readonly string[]
  readonly failed: boolean
}

export const emptyExtraction = (sourceId: string): Extraction => ({
  sourceId,
  stage: null,
  stages: [],
  entities: null,
  relationships: null,
  domain: null,
  domainConfidence: null,
  index: null,
  total: null,
  modelCalls: null,
  merges: [],
  failed: false,
})

export const isExtractionFrame = (frame: unknown): boolean =>
  typeof frame === 'object' && frame !== null && (frame as { type?: unknown }).type === 'Extraction'

/** Fold one frame into an extraction.
 *
 * A stage is listed once even though `extracting` and `consolidating` each
 * arrive many times: the list is the shape of the work, and the repeats are
 * progress within a stage. `??` rather than `||` throughout, so a real `0`
 * count survives.
 */
export const applyNote = (extraction: Extraction, frame: ExtractionFrame): Extraction => {
  const known = extraction.stages.some((entry) => entry.stage === frame.stage)
  const stages = known
    ? extraction.stages.map((entry) =>
        entry.stage === frame.stage && frame.detail ? { ...entry, detail: frame.detail } : entry,
      )
    : [...extraction.stages, { stage: frame.stage, detail: frame.detail }]

  return {
    ...extraction,
    sourceId: frame.sourceId,
    stage: frame.stage,
    stages,
    entities: frame.entities ?? extraction.entities,
    relationships: frame.relationships ?? extraction.relationships,
    domain: frame.domain ?? extraction.domain,
    domainConfidence: frame.domainConfidence ?? extraction.domainConfidence,
    index: frame.index ?? extraction.index,
    total: frame.total ?? extraction.total,
    modelCalls: frame.modelCalls ?? extraction.modelCalls,
    merges:
      frame.stage === 'consolidating' && frame.detail
        ? [...extraction.merges, frame.detail]
        : extraction.merges,
    failed: extraction.failed || frame.stage === 'failed',
  }
}
```

- [ ] **Step 4: Run the test**

Run: `cd frontend && npx vitest run src/domain/knowledge/extraction.test.ts`
Expected: PASS — all seven.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/domain/knowledge/
git commit -m "feat: extraction progress as a frontend domain model"
```

---

## Task 15: The extraction store and pane

**Files:**
- Create: `frontend/src/application/knowledge/extraction-store.ts`, `frontend/src/application/knowledge/extraction-store.test.ts`, `frontend/src/presentation/course/ExtractionPane.tsx`
- Modify: `frontend/src/infrastructure/http/mappers.ts` (`toExtractionFrame`), `frontend/src/infrastructure/http/dto.ts`, `frontend/src/application/ports/repositories.ts` (`ExtractionRepository`), `frontend/src/infrastructure/http/project-repository.ts`, `frontend/src/app/container.ts`, `frontend/src/presentation/course/CourseView.tsx`, `frontend/src/styles/course.css`

**Interfaces:**
- Consumes: `applyNote`, `emptyExtraction`, `isExtractionFrame` (Task 14); `useStream` (`@presentation/shell/StreamProvider.tsx`).
- Produces: `createExtractionStore({ extractions, projectId })` with `handleFrame`, `catchUp`; `<ExtractionPane projectId />`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/application/knowledge/extraction-store.test.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { createExtractionStore } from './extraction-store.ts'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const OTHER = ProjectId('99999999-9999-9999-9999-999999999999')

const frame = (over: Record<string, unknown> = {}) => ({
  type: 'Extraction',
  project_id: PROJECT,
  source_id: 'notes',
  stage: 'extracting',
  detail: '',
  entities: null,
  relationships: null,
  domain: null,
  domain_confidence: null,
  index: null,
  total: null,
  model_calls: null,
  ...over,
})

const store = (extractions = { on: vi.fn().mockResolvedValue({ current: [], last: [] }) }) =>
  createExtractionStore({ extractions, projectId: PROJECT })

it('folds a frame for this project', () => {
  const extraction = store()
  extraction.getState().handleFrame(frame({ stage: 'storing' }))

  expect(extraction.getState().current?.stage).toBe('storing')
})

it('ignores a frame for another project', () => {
  // The SSE connection is global — every project's frames arrive here.
  // Folding another project's extraction would show one course's work on
  // another's page.
  const extraction = store()
  extraction.getState().handleFrame(frame({ project_id: OTHER, stage: 'storing' }))

  expect(extraction.getState().current).toBeNull()
})

it('ignores frames that are not extraction frames', () => {
  const extraction = store()
  extraction.getState().handleFrame({ type: 'TurnActivity', session_id: 'x' })

  expect(extraction.getState().current).toBeNull()
})

it('moves a finished extraction to last and clears current', () => {
  const extraction = store()
  extraction.getState().handleFrame(frame({ stage: 'extracting' }))
  extraction.getState().handleFrame(frame({ stage: 'consolidated', entities: 2 }))

  expect(extraction.getState().current).toBeNull()
  expect(extraction.getState().last?.entities).toBe(2)
})

it('keeps a failed extraction as the last one', () => {
  const extraction = store()
  extraction.getState().handleFrame(frame({ stage: 'failed', detail: 'the model refused' }))

  expect(extraction.getState().last?.failed).toBe(true)
})

it('starts a new extraction when the source changes', () => {
  const extraction = store()
  extraction.getState().handleFrame(frame({ source_id: 'first', stage: 'extracting' }))
  extraction.getState().handleFrame(frame({ source_id: 'second', stage: 'storing' }))

  expect(extraction.getState().current?.sourceId).toBe('second')
  expect(extraction.getState().current?.stages.map((s) => s.stage)).toEqual(['storing'])
})

it('rebuilds from the catch-up route after a reconnect', async () => {
  // The frames carry no feed position, so this is the only recovery path.
  const extractions = {
    on: vi.fn().mockResolvedValue({
      current: [frame({ stage: 'consolidating', index: 3, total: 9 })],
      last: [],
    }),
  }
  const extraction = store(extractions)

  await extraction.getState().catchUp()

  expect(extractions.on).toHaveBeenCalledWith(PROJECT)
  expect(extraction.getState().current?.index).toBe(3)
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/application/knowledge/extraction-store.test.ts`
Expected: FAIL — cannot resolve `./extraction-store.ts`

- [ ] **Step 3: Write the store**

Create `frontend/src/application/knowledge/extraction-store.ts`:

```ts
import { create } from 'zustand'

import {
  applyNote,
  emptyExtraction,
  isExtractionFrame,
  type Extraction,
  type ExtractionFrame,
} from '@domain/knowledge/extraction.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import type { ExtractionRepository } from '../ports/repositories.ts'

/** One project's extraction progress.
 *
 * Project-keyed rather than folded into the session store, because these
 * frames are addressed to a project: extraction is a project-level fact and
 * the graph is tenant-scoped by project. Filing them under whichever session
 * happened to be open would attribute a project's work to a session that may
 * not have caused it.
 *
 * The SSE connection is global, so every project's frames arrive here.
 * Filtering by project is this store's first job, not an optimisation.
 */
export interface ExtractionState {
  readonly current: Extraction | null
  readonly last: Extraction | null
  handleFrame(frame: unknown): void
  /** Rebuild from the catch-up route.
   *
   * The only recovery path there is: these frames carry no feed position, so a
   * reconnect cannot replay them, and without this a dropped connection would
   * leave the pane frozen — indistinguishable from a stalled extraction. */
  catchUp(): Promise<void>
}

const TERMINAL = ['consolidated', 'failed']

export const createExtractionStore = ({
  extractions,
  projectId,
}: {
  extractions: ExtractionRepository
  projectId: ProjectId
}) =>
  create<ExtractionState>((set, get) => {
    const fold = (frames: readonly ExtractionFrame[]): Extraction | null =>
      frames.reduce<Extraction | null>(
        (extraction, frame) =>
          applyNote(extraction ?? emptyExtraction(frame.sourceId), frame),
        null,
      )

    return {
      current: null,
      last: null,

      handleFrame(raw) {
        if (!isExtractionFrame(raw)) return
        const frame = toFrame(raw)
        if (frame.projectId !== projectId) return

        const running = get().current
        // A different document means the last one is over: keeping its stages
        // under the new source would attribute one document's work to another.
        const base =
          running && running.sourceId === frame.sourceId
            ? running
            : emptyExtraction(frame.sourceId)
        const next = applyNote(base, frame)

        if (TERMINAL.includes(frame.stage)) set({ current: null, last: next })
        else set({ current: next })
      },

      async catchUp() {
        const { current, last } = await extractions.on(projectId)
        set({ current: fold(current), last: fold(last) })
      },
    }
  })
```

Write `toFrame` in `frontend/src/infrastructure/http/mappers.ts` as an exported `toExtractionFrame` (snake_case wire → camelCase domain) and import it here, matching how the other mappers are arranged. Add the matching `ExtractionFrameDto` and `ExtractionCatchUpDto` to `dto.ts`, an `ExtractionRepository` with `on(projectId): Promise<{ current: ExtractionFrame[]; last: ExtractionFrame[] }>` to `repositories.ts`, an `HttpExtractionRepository` to `project-repository.ts`, and register it in `container.ts`.

- [ ] **Step 4: Write the pane**

Create `frontend/src/presentation/course/ExtractionPane.tsx`. It should:

- build one `createExtractionStore` for the project, memoised on `projectId` and the container
- call `catchUp()` on mount and on `onReconnect` from `useStream()`
- subscribe with `stream.onFrame((frame) => store.getState().handleFrame(frame))`
- render, for the running extraction: the stage list with the current one marked, `model calls: N` while `extracting`, the `entities / relationships` and `domain (confidence)` once `extracted` has arrived, then the consolidation list — `index/total` as a heading and `merges` as the lines beneath it
- render `domainConfidence === 0` as `fallback — treat the shape as unverified` rather than `0.00`, and a null confidence as no confidence text at all
- render the last extraction, collapsed, beneath the running one, with a `failed` tone when `failed` is true
- say `No extraction has run on this project yet.` when both are null

Mount it in `CourseView.tsx` beside `<Workers>` — the roster row is the summary, this is the detail — and style it in `course.css` with `tokens.css` custom properties.

- [ ] **Step 5: Run the tests and verify**

Run: `cd frontend && npx vitest run src/application/knowledge/ src/domain/knowledge/ && npm run verify`
Expected: PASS throughout.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/application/knowledge/ frontend/src/presentation/course/ExtractionPane.tsx frontend/src/infrastructure/http/ frontend/src/application/ports/repositories.ts frontend/src/app/container.ts frontend/src/presentation/course/CourseView.tsx frontend/src/styles/course.css
git commit -m "feat: watch the knowledge graph being extracted"
```

---

## Task 16: Build, verify, and see it work

**Files:**
- Modify: `research_team/interfaces/web/static/**`, `README.md`

- [ ] **Step 1: Run both suites**

Run: `uv run pytest && cd frontend && npm run verify`
Expected: PASS.

- [ ] **Step 2: Watch it work end to end**

Run `uv run web.py`, open a project with a corpus, and start an autonomous run. Confirm:

- the roster shows the run, its turn, and — when a round calls `remember` — a nested extraction row
- the extraction pane advances through `storing` → `extracting` (with the model-call count climbing) → `extracted` (counts and schema) → `consolidating N/M` with a line per entity and its verdict → `consolidated`
- reloading mid-extraction rebuilds the pane from the catch-up route rather than showing an empty one
- the drawer opens on the run's session and shows the same turn the roster named

- [ ] **Step 3: Confirm the log did not grow a new event type**

Run: `uv run pytest tests/infrastructure/test_knowledge_rebuild.py tests/integration -v`
Expected: PASS. A replay that now sees an unknown event type would fail here, which is the check that the global constraint held.

- [ ] **Step 4: Update the README**

Add a short paragraph to the web-UI section describing the roster, the drawer, and the extraction pane, in the register of the surrounding prose. Say plainly that extraction progress is provisional and not part of the log.

- [ ] **Step 5: Commit**

```bash
git add research_team/interfaces/web/static README.md
git commit -m "build: the console, with the extraction pane"
```

---

# Self-review

**Spec coverage.** Part A's surface → Tasks 4, 6; the roster service → 1; the route → 2; composition → 3; the drawer → 8; the URL → 7; the poll-not-push decision → 1, 2, 6; the stale-not-empty rule → 6. Part B's port → 10; adapter instrumentation and the provider decorator → 11; `ExtractionActivity` and the catch-up route → 12, 13; the third SSE listener → 13; the pane → 15; the frames-are-provisional constraint → Global Constraints, asserted in 16 Step 3. The extraction nesting rule → 1 (`_parent_for`), tested four ways. Deferred Part C appears nowhere, correctly.

**One gap found and closed:** the spec's file list named `frontend/src/domain/knowledge/extraction.ts` but nothing that turned a wire frame into it. Task 15 adds `toExtractionFrame` to `mappers.ts` and the `ExtractionRepository` for the catch-up route.

**One design wrinkle found and resolved in Task 13:** `build_application` needs the extraction buffer for *two* purposes — the roster reads it, the tools report through it. Two parameters could be given mismatched halves, so it takes one `ExtractionChannel` and `application/workers.py` declares the combined protocol.

**Type consistency.** `ExtractionSnapshot` (Task 1) is produced by `ExtractionActivity.in_flight` (Task 12) and consumed by `WorkerRoster` (Task 1) — same field names throughout. `ExtractionNote`'s fields (Task 10) map to frame keys (Task 12) to `ExtractionFrame` (Task 14) with a snake/camel change and no renames. `Worker.ref`/`parent`/`sessionId` are consistent across Tasks 1, 2, 4, 5, 6. `nest` is called only in Task 6, as defined in Task 4.

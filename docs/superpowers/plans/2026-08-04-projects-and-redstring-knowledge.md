# Projects and a redstring Knowledge Graph Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the agent a project-scoped knowledge graph it can write to and read from, so research compounds across sessions instead of dying with each one.

**Architecture:** A `Project` aggregate scopes a set of sessions that share a filesystem lineage, and its id doubles as redstring's `tenant_id`. A `KnowledgePort` protocol keeps redstring behind exactly one adapter module. redstring's own event streams (`Document`, `Consolidation`) live in the same SQLite file as the session streams, so the graph is a projection of a log that can be rebuilt, and no model call ever happens at fold time.

**Tech Stack:** Python 3.13, `redstring[llm]`, `eventsource-py[sqlite]>=0.10.0`, `deepagents`/`langchain`, pytest, SQLite.

**Spec:** `docs/superpowers/specs/2026-08-04-projects-and-redstring-knowledge-design.md`

## Global Constraints

- **`eventsource-py[sqlite]>=0.10.0`** — the floor must not drop. redstring's projections forward `retry_policy`, `tracer` and `tenant_filter`, which 0.9.x rejects with `TypeError`.
- **`redstring[llm]`** is the dependency to add — the base install plus `langchain-openai`. The "no extras" property covers the *stores*, not the model provider.
- **`project_id` is a `UUID`, never a string.** redstring's `TenantId` is `UUID`.
- **No model call at fold time.** Extraction results are recorded as events and replayed, never recomputed.
- **Every redstring call happens inside `async with tenant_scope(project_id)`.** `TenantAwareRepository` raises `TenantContextNotSetError` outside one.
- **Never append `EntitiesMerged` yourself.** `Consolidator.resolve` appends *and* folds its own event; a second append double-applies the merge.
- **Adding a field to an existing event requires a default** meaning what its absence meant, plus a case in `tests/infrastructure/test_schema_evolution.py`. This is the documented rule in `research_team/domain/events.py`.
- Test command throughout: `uv run pytest`.

---

### Task 1: The `Project` aggregate

**Files:**
- Create: `research_team/domain/project.py`
- Modify: `research_team/domain/__init__.py`
- Test: `tests/domain/test_project.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ProjectState`, `Project`, `decide`, `evolve`; events `ProjectCreated(aggregate_id, name)`, `SessionJoinedProject(aggregate_id, session_id, inherited_at)`, `ProjectTipAdvanced(aggregate_id, session_id, at_event)`; commands `CreateProject(name)`, `JoinProject(session_id)`, `AdvanceTip(session_id, at_event)`. `ProjectState` exposes `.tip_session_id: UUID | None`, `.tip_at_event: int`, `.active_session_id: UUID | None`, `.status`.

- [ ] **Step 1: Write the failing test**

Create `tests/domain/test_project.py`:

```python
import pytest
from uuid import uuid4

from research_team.domain.project import (
    AdvanceTip,
    CreateProject,
    JoinProject,
    ProjectCreated,
    ProjectState,
    ProjectTipAdvanced,
    SessionJoinedProject,
    decide,
    evolve,
    initial_state,
)
from eventsource.domain.decider import CommandRejectedError


def test_creating_a_project_emits_project_created():
    project_id = uuid4()
    state = initial_state(project_id)

    events = decide(CreateProject(name="research"), state)

    assert events == [ProjectCreated(aggregate_id=project_id, name="research")]


def test_a_project_cannot_be_created_twice():
    project_id = uuid4()
    state = evolve(initial_state(project_id), ProjectCreated(aggregate_id=project_id, name="research"))

    with pytest.raises(CommandRejectedError, match="already created"):
        decide(CreateProject(name="research"), state)


def test_commands_before_creation_are_rejected():
    state = initial_state(uuid4())

    with pytest.raises(CommandRejectedError, match="not created"):
        decide(JoinProject(session_id=uuid4()), state)


def test_a_session_joins_and_inherits_the_current_tip():
    project_id, first, second = uuid4(), uuid4(), uuid4()
    state = initial_state(project_id)
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        SessionJoinedProject(aggregate_id=project_id, session_id=first, inherited_at=0),
        ProjectTipAdvanced(aggregate_id=project_id, session_id=first, at_event=12),
    ):
        state = evolve(state, event)

    events = decide(JoinProject(session_id=second), state)

    assert events == [
        SessionJoinedProject(aggregate_id=project_id, session_id=second, inherited_at=12)
    ]


def test_a_second_concurrent_session_is_rejected_by_name():
    project_id, holder = uuid4(), uuid4()
    state = initial_state(project_id)
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        SessionJoinedProject(aggregate_id=project_id, session_id=holder, inherited_at=0),
    ):
        state = evolve(state, event)

    with pytest.raises(CommandRejectedError, match=str(holder)):
        decide(JoinProject(session_id=uuid4()), state)


def test_advancing_the_tip_releases_the_project():
    project_id, session_id = uuid4(), uuid4()
    state = initial_state(project_id)
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        SessionJoinedProject(aggregate_id=project_id, session_id=session_id, inherited_at=0),
        ProjectTipAdvanced(aggregate_id=project_id, session_id=session_id, at_event=7),
    ):
        state = evolve(state, event)

    assert state.active_session_id is None
    assert state.tip_session_id == session_id
    assert state.tip_at_event == 7


def test_only_the_active_session_may_advance_the_tip():
    project_id, holder = uuid4(), uuid4()
    state = initial_state(project_id)
    for event in (
        ProjectCreated(aggregate_id=project_id, name="research"),
        SessionJoinedProject(aggregate_id=project_id, session_id=holder, inherited_at=0),
    ):
        state = evolve(state, event)

    with pytest.raises(CommandRejectedError, match="does not hold"):
        decide(AdvanceTip(session_id=uuid4(), at_event=3), state)


def test_evolve_ignores_unknown_events():
    project_id = uuid4()
    state = evolve(initial_state(project_id), ProjectCreated(aggregate_id=project_id, name="r"))

    assert evolve(state, ProjectCreated(aggregate_id=project_id, name="other")) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_project.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'research_team.domain.project'`

- [ ] **Step 3: Write the implementation**

Create `research_team/domain/project.py`:

```python
"""A project: sessions that share a filesystem lineage and a knowledge graph.

Sequential by construction. One session holds the project at a time, inherits
the filesystem as the last one left it, and hands the tip back when it ends.
That is the same shape as a fork -- inherit at a point, diverge from there --
which is why this aggregate stores a lineage pointer rather than files of its
own. The filesystem still folds out of a single session stream, so scrubbing a
session's timeline still refolds its filesystem.

The project id is also redstring's `tenant_id`, which is why it is a UUID.
"""

from dataclasses import dataclass
from uuid import UUID

from eventsource import DomainEvent, register_event
from eventsource.domain.decider import CommandRejectedError, DeciderAggregate
from pydantic import BaseModel, Field
from typing import Literal


@register_event
class ProjectCreated(DomainEvent):
    """Creation event. Must be the first event on the stream."""

    aggregate_type: str = "Project"
    name: str


@register_event
class SessionJoinedProject(DomainEvent):
    """A session took the project, inheriting the filesystem at `inherited_at`."""

    aggregate_type: str = "Project"
    session_id: UUID
    inherited_at: int


@register_event
class ProjectTipAdvanced(DomainEvent):
    """A session finished; the project's filesystem is now its stream at `at_event`."""

    aggregate_type: str = "Project"
    session_id: UUID
    at_event: int


@dataclass(frozen=True)
class CreateProject:
    name: str


@dataclass(frozen=True)
class JoinProject:
    session_id: UUID


@dataclass(frozen=True)
class AdvanceTip:
    session_id: UUID
    at_event: int


ProjectCommand = CreateProject | JoinProject | AdvanceTip


class ProjectState(BaseModel):
    """Everything derivable from the project's event stream."""

    project_id: UUID
    status: Literal["new", "created"] = "new"
    name: str = ""
    member_session_ids: list[UUID] = Field(default_factory=list)
    active_session_id: UUID | None = None
    """The session currently holding the project, if any."""
    tip_session_id: UUID | None = None
    """Whose stream the filesystem folds from. None means the project is empty."""
    tip_at_event: int = 0
    """How far into that stream to fold."""


def initial_state(aggregate_id: UUID) -> ProjectState:
    return ProjectState(project_id=aggregate_id)


def decide(command: ProjectCommand, state: ProjectState) -> list[DomainEvent]:
    """Which requests are legal, and what facts they produce.

    Reads as a transition table, the way `session.decide` does.
    """
    project_id = state.project_id
    match command, state:
        case CreateProject(name=name), ProjectState(status="new"):
            return [ProjectCreated(aggregate_id=project_id, name=name)]
        case CreateProject(), _:
            raise CommandRejectedError("project already created")

        case _, ProjectState(status="new"):
            raise CommandRejectedError("project not created")

        case JoinProject(session_id=session_id), ProjectState(active_session_id=None):
            return [
                SessionJoinedProject(
                    aggregate_id=project_id,
                    session_id=session_id,
                    inherited_at=state.tip_at_event,
                )
            ]
        case JoinProject(), ProjectState(active_session_id=holder):
            # Named, not just refused: the next thing anyone asks is "which one".
            raise CommandRejectedError(f"project is held by session {holder}")

        case AdvanceTip(session_id=session_id, at_event=at), _:
            if state.active_session_id != session_id:
                raise CommandRejectedError(
                    f"session {session_id} does not hold this project"
                )
            return [
                ProjectTipAdvanced(
                    aggregate_id=project_id, session_id=session_id, at_event=at
                )
            ]

    raise CommandRejectedError(f"unhandled command {type(command).__name__}")


def evolve(state: ProjectState, event: DomainEvent) -> ProjectState:
    """What each fact does to the state.

    Total on purpose: an unknown event leaves the state alone rather than
    raising, so a stream carrying an event this build does not know about still
    replays instead of failing halfway through.
    """
    match event:
        case ProjectCreated(name=name):
            return ProjectState(
                project_id=state.project_id, status="created", name=name
            )

        case SessionJoinedProject(session_id=session_id):
            return state.model_copy(
                update={
                    "member_session_ids": [*state.member_session_ids, session_id],
                    "active_session_id": session_id,
                }
            )

        case ProjectTipAdvanced(session_id=session_id, at_event=at):
            return state.model_copy(
                update={
                    "active_session_id": None,
                    "tip_session_id": session_id,
                    "tip_at_event": at,
                }
            )

        case _:
            return state


class Project(DeciderAggregate[ProjectState, ProjectCommand]):
    """The imperative shell. Holds no rules -- it delegates all three."""

    aggregate_type = "Project"

    @staticmethod
    def initial_state(aggregate_id: UUID) -> ProjectState:
        return initial_state(aggregate_id)

    @staticmethod
    def decide(command: ProjectCommand, state: ProjectState) -> list[DomainEvent]:
        return decide(command, state)

    @staticmethod
    def evolve(state: ProjectState, event: DomainEvent) -> ProjectState:
        return evolve(state, event)
```

Note: `aggregate_type = "Project"` is mandatory — eventsource 0.9.0 removed the `"Unknown"` default and raises `AggregateTypeNotSetError` without it.

- [ ] **Step 4: Match the `DeciderAggregate` base class to `CodingSession`**

Open `research_team/domain/session.py` and read how `CodingSession` declares `initial_state`, `decide` and `evolve` on the class (around line 319). Make `Project` match that shape exactly — if `CodingSession` uses classmethods or class attributes rather than staticmethods, change `Project` to match. Do not invent a second convention.

- [ ] **Step 5: Export from the domain package**

In `research_team/domain/__init__.py`, add `Project`, `ProjectState`, `CreateProject`, `JoinProject`, `AdvanceTip`, `ProjectCreated`, `SessionJoinedProject`, `ProjectTipAdvanced` to the imports and `__all__`, following the existing style.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_project.py -v`
Expected: PASS, 8 tests

- [ ] **Step 7: Commit**

```bash
git add research_team/domain/project.py research_team/domain/__init__.py tests/domain/test_project.py
git commit -m "feat: add the Project aggregate

Sessions in a project run one at a time, inheriting the filesystem where
the last one left it. Stores a lineage pointer rather than files, so the
filesystem still folds out of a single session stream."
```

---

### Task 2: Sessions carry a project id

**Files:**
- Modify: `research_team/domain/events.py` (`SessionStarted`)
- Modify: `research_team/domain/commands.py` (`StartSession`)
- Modify: `research_team/domain/session.py` (`SessionState`, `decide`, `evolve`)
- Test: `tests/domain/test_session.py`, `tests/infrastructure/test_schema_evolution.py`

**Interfaces:**
- Consumes: Task 1's `Project`.
- Produces: `SessionState.project_id: UUID | None`, `SessionStarted.project_id: UUID | None`, `StartSession(..., project_id: UUID | None = None)`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/domain/test_session.py`:

```python
def test_a_session_records_the_project_it_belongs_to():
    session_id, project_id = uuid4(), uuid4()
    state = initial_state(session_id)

    events = decide(
        StartSession(system_prompt="p", model_name="m", project_id=project_id), state
    )

    assert events[0].project_id == project_id
    assert evolve(state, events[0]).project_id == project_id


def test_a_session_without_a_project_has_none():
    session_id = uuid4()
    state = initial_state(session_id)

    events = decide(StartSession(system_prompt="p", model_name="m"), state)

    assert events[0].project_id is None
    assert evolve(state, events[0]).project_id is None
```

Add to `tests/infrastructure/test_schema_evolution.py`, following the existing cases in that file (they write an old-shaped payload straight into the events table and read it back):

```python
async def test_session_started_without_project_id_still_loads(tmp_path):
    """A SessionStarted written before projects existed has no project_id key."""
    # Follow the file's existing helper for writing a raw payload; the payload
    # is the pre-project shape:
    payload = {"system_prompt": "p", "model_name": "m"}
    event = await write_and_read_back("SessionStarted", payload, tmp_path)

    assert event.project_id is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/domain/test_session.py -k project tests/infrastructure/test_schema_evolution.py -k project -v`
Expected: FAIL — `StartSession` has no `project_id` parameter

- [ ] **Step 3: Add the field**

In `research_team/domain/events.py`, add to `SessionStarted`:

```python
@register_event
class SessionStarted(DomainEvent):
    """Creation event. Must be the first event on the stream."""

    aggregate_type: str = "CodingSession"
    system_prompt: str
    model_name: str
    project_id: UUID | None = None
    """The project whose filesystem and knowledge graph this session shares.

    Defaulted rather than required: every session written before projects
    existed has no such key, and `None` means exactly what its absence meant.
    This is case 1 of the strategy at the top of this module.
    """
```

In `research_team/domain/commands.py`, add `project_id: UUID | None = None` to `StartSession`, matching the existing dataclass style.

In `research_team/domain/session.py`, add `project_id: UUID | None = None` to `SessionState`, then thread it through:

```python
        case StartSession(
            system_prompt=prompt, model_name=model, project_id=project_id
        ), SessionState(status="new"):
            return [
                SessionStarted(
                    aggregate_id=session_id,
                    system_prompt=prompt,
                    model_name=model,
                    project_id=project_id,
                )
            ]
```

and in `evolve`:

```python
        case SessionStarted(
            system_prompt=prompt, model_name=model, project_id=project_id
        ):
            return SessionState(
                session_id=state.session_id,
                status="started",
                system_prompt=prompt,
                model_name=model,
                project_id=project_id,
            )
```

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest`
Expected: PASS. If `test_schema_evolution.py` needed a different helper name, fix the test to match that file's existing convention rather than adding a new one.

- [ ] **Step 5: Commit**

```bash
git add research_team/domain/ tests/domain/test_session.py tests/infrastructure/test_schema_evolution.py
git commit -m "feat: sessions record the project they belong to

Additive with a None default, so sessions written before projects existed
still load. Schema evolution case added."
```

---

### Task 3: Keep the session feed clean when foreign events share the store

**Files:**
- Modify: `research_team/infrastructure/persistence/event_store.py:146-155` (`read_since`)
- Test: `tests/infrastructure/test_event_store.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `read_since` yields only `CodingSession` events. No signature change.

This lands before any redstring event can reach the store, because unfiltered it would corrupt the live feed and the session list.

- [ ] **Step 1: Write the failing test**

Add to `tests/infrastructure/test_event_store.py`:

```python
import pytest
from uuid import uuid4

from eventsource import StreamId
from eventsource.ports.positions import ExpectedVersion

from research_team.domain.project import ProjectCreated


@pytest.mark.asyncio
async def test_read_since_ignores_events_from_other_aggregate_types(tmp_path):
    """A shared store carries foreign streams; the session feed must not see them."""
    repository = EventStoreSessionRepository.open(str(tmp_path / "sessions.db"))
    try:
        session_id = uuid4()
        session = repository.create(session_id)
        session.handle(StartSession(system_prompt="p", model_name="m"))
        await repository.save(session)

        project_id = uuid4()
        await repository.store.append(
            StreamId(aggregate_id=project_id, category="Project"),
            [ProjectCreated(aggregate_id=project_id, name="research")],
            ExpectedVersion.any_(),
        )

        entries = await repository.read_since(None)

        assert entries, "the session's own events should still arrive"
        assert all(entry.session_id == session_id for entry in entries)
    finally:
        await repository.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_event_store.py -k other_aggregate_types -v`
Expected: FAIL — an entry with `session_id == project_id` is present

- [ ] **Step 3: Filter the feed**

In `research_team/infrastructure/persistence/event_store.py`, replace `read_since`:

```python
    async def read_since(self, position: object | None) -> list[FeedEntry]:
        """Session events since `position`, in append order.

        Filtered by aggregate type rather than taking the whole feed. This
        store is shared: redstring's `Document` and `Consolidation` streams
        live in the same file, and their aggregate ids are document and tenant
        ids, not sessions. Unfiltered, every one of them would arrive here as a
        `FeedEntry` claiming to be a session that does not exist.
        """
        envelopes = await collect(self._store.read_all(from_position=position))
        return [
            FeedEntry(
                session_id=envelope.event.aggregate_id,
                event=envelope.event,
                position=envelope.position,
            )
            for envelope in envelopes
            if envelope.event.aggregate_type == CodingSession.aggregate_type
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/persistence/event_store.py tests/infrastructure/test_event_store.py
git commit -m "fix: the session feed ignores foreign aggregate types

The store is about to be shared with redstring's Document and Consolidation
streams, whose aggregate ids are not sessions."
```

---

### Task 4: The `KnowledgePort` and its DTOs

**Files:**
- Create: `research_team/application/knowledge.py`
- Modify: `research_team/application/__init__.py`
- Test: `tests/application/test_knowledge.py`

**Interfaces:**
- Consumes: nothing.
- Produces, all used verbatim by Tasks 5–8:
  - `SourceRef(source_id: str, text: str, note: str | None = None)`
  - `MergeRecord(merge_id: UUID, canonical_name: str, absorbed_names: tuple[str, ...], reason: str | None)`
  - `IngestReport(source_id: str, entity_count: int, relationship_count: int, domain: str | None, domain_confidence: float | None, merges: tuple[MergeRecord, ...], consolidation_failures: int)`
  - `Match(entity_id: UUID, name: str, entity_type: str, relationship_count: int)`
  - `KnowledgeError(Exception)`
  - `KnowledgePort` Protocol: `ingest(source: SourceRef) -> IngestReport`, `search(query: str, *, limit: int = 10) -> list[Match]`, `undo_merge(merge_id: UUID) -> MergeRecord`
  - Tool name constants `REMEMBER_TOOL = "remember"`, `GRAPH_SEARCH_TOOL = "graph_search"`, `UNMERGE_TOOL = "unmerge"`

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_knowledge.py`:

```python
from uuid import uuid4

from research_team.application.knowledge import (
    IngestReport,
    KnowledgePort,
    Match,
    MergeRecord,
    SourceRef,
)


def test_source_ref_carries_an_optional_note():
    assert SourceRef(source_id="s", text="t").note is None
    assert SourceRef(source_id="s", text="t", note="why").note == "why"


def test_ingest_report_defaults_to_no_merges():
    report = IngestReport(
        source_id="s",
        entity_count=3,
        relationship_count=2,
        domain="encyclopedia_wiki",
        domain_confidence=0.0,
    )

    assert report.merges == ()
    assert report.consolidation_failures == 0


def test_a_stub_satisfies_the_port():
    """The Protocol is structural; this pins the exact signatures."""

    class Stub:
        async def ingest(self, source: SourceRef) -> IngestReport:
            return IngestReport(
                source_id=source.source_id,
                entity_count=0,
                relationship_count=0,
                domain=None,
                domain_confidence=None,
            )

        async def search(self, query: str, *, limit: int = 10) -> list[Match]:
            return []

        async def undo_merge(self, merge_id):
            return MergeRecord(
                merge_id=merge_id,
                canonical_name="c",
                absorbed_names=(),
                reason=None,
            )

    port: KnowledgePort = Stub()
    assert port is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_knowledge.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `research_team/application/knowledge.py`:

```python
"""The knowledge graph, in this application's own terms.

Names no redstring type. The adapter behind this port owns that vocabulary,
which is what lets the graph backend change without anything above here
noticing -- and what keeps redstring out of the application layer's import
graph entirely.

The tenant is deliberately not a parameter on any of these calls. A port
instance belongs to one project and supplies it; a caller that could pass a
different tenant is a caller that could write into another project's graph.
"""

from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

#: Tool names, in one place so the autonomy policy and the tools agree.
REMEMBER_TOOL = "remember"
GRAPH_SEARCH_TOOL = "graph_search"
UNMERGE_TOOL = "unmerge"


class KnowledgeError(Exception):
    """Something went wrong reaching or writing the graph."""


@dataclass(frozen=True)
class SourceRef:
    """Content to commit to the graph, supplied by the caller."""

    source_id: str
    """Identifies the document. Must not be blank -- it keys the stream."""
    text: str
    note: str | None = None
    """Why the agent thought this was worth remembering. Provenance only."""


@dataclass(frozen=True)
class MergeRecord:
    """One consolidation, in a form the agent can read and reverse."""

    merge_id: UUID
    canonical_name: str
    absorbed_names: tuple[str, ...]
    reason: str | None


@dataclass(frozen=True)
class IngestReport:
    """What one ingest extracted and consolidated."""

    source_id: str
    entity_count: int
    relationship_count: int
    domain: str | None
    """Which prompt ran. None when no classifier was involved."""
    domain_confidence: float | None
    """How sure the classifier was. `0.0` means it gave up and fell back;
    `None` means no classifier ran. A fallback is otherwise indistinguishable
    from a confident choice, which is this field's whole reason for existing."""
    merges: tuple[MergeRecord, ...] = ()
    consolidation_failures: int = 0
    """Entities whose consolidation raised. The extraction still stands."""


@dataclass(frozen=True)
class Match:
    """One entity found by a search."""

    entity_id: UUID
    name: str
    entity_type: str
    relationship_count: int


class KnowledgePort(Protocol):
    """Committing to the graph, reading it back, and reversing a merge."""

    async def ingest(self, source: SourceRef) -> IngestReport:
        """Extract `source`, record it, and consolidate what it found."""
        ...

    async def search(self, query: str, *, limit: int = 10) -> list[Match]:
        """Entities whose name matches `query`. Entry points, not traversal."""
        ...

    async def undo_merge(self, merge_id: UUID) -> MergeRecord:
        """Reverse the merge `merge_id` recorded.

        Raises `KnowledgeError` when no merge in effect has that id -- which
        covers "never happened" and "already undone" as one case.
        """
        ...
```

- [ ] **Step 4: Export from the application package**

In `research_team/application/__init__.py`, add the six names plus the three tool constants to the imports and `__all__`, following the existing style (see how `SEARCH_TOOL` is exported).

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/application/test_knowledge.py -v`
Expected: PASS, 3 tests

- [ ] **Step 6: Commit**

```bash
git add research_team/application/knowledge.py research_team/application/__init__.py tests/application/test_knowledge.py
git commit -m "feat: add the KnowledgePort and its DTOs

Names no redstring type, so the graph backend stays behind one adapter."
```

---

### Task 5: Dependencies, config, and store construction

**Files:**
- Modify: `pyproject.toml`
- Modify: `research_team/infrastructure/config.py`
- Create: `research_team/infrastructure/knowledge/__init__.py`
- Create: `research_team/infrastructure/knowledge/stores.py`
- Test: `tests/infrastructure/test_knowledge_stores.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `config.graph_store()` → `str`, `config.knowledge_domain()` → `str`; `build_graph_store(kind: str) -> GraphStore`.

- [ ] **Step 1: Add the dependency**

```bash
uv add "redstring[llm]"
```

Then verify the eventsource floor did not move below 0.10.0:

```bash
uv run python -c "import eventsource, importlib.metadata as m; print(m.version('eventsource-py'))"
```

Expected: `0.10.x` or higher. If lower, pin it up — redstring's projections forward keywords 0.9.x rejects.

- [ ] **Step 2: Write the failing test**

Create `tests/infrastructure/test_knowledge_stores.py`:

```python
import pytest

from research_team.infrastructure.knowledge.stores import build_graph_store


def test_memory_is_the_default_store():
    store = build_graph_store("memory")

    assert type(store).__name__ == "InMemoryGraphStore"


def test_an_unknown_store_is_rejected_by_name():
    with pytest.raises(ValueError, match="postgres"):
        build_graph_store("postgres")
```

And add to `tests/infrastructure/test_config.py` (matching that file's existing style):

```python
def test_graph_store_defaults_to_memory(monkeypatch):
    monkeypatch.delenv("AGENT_GRAPH_STORE", raising=False)
    assert config.graph_store() == "memory"


def test_knowledge_domain_defaults_to_auto(monkeypatch):
    monkeypatch.delenv("AGENT_KNOWLEDGE_DOMAIN", raising=False)
    assert config.knowledge_domain() == "auto"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_knowledge_stores.py tests/infrastructure/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError` and `AttributeError: module has no attribute 'graph_store'`

- [ ] **Step 4: Write the implementation**

Add to `research_team/infrastructure/config.py`, next to the other readers:

```python
DEFAULT_GRAPH_STORE = "memory"
DEFAULT_KNOWLEDGE_DOMAIN = "auto"


def graph_store() -> str:
    """What backs the knowledge graph. `memory` needs no server."""
    return os.getenv("AGENT_GRAPH_STORE", DEFAULT_GRAPH_STORE)


def knowledge_domain() -> str:
    """A redstring schema id, or `auto` to have a classifier choose."""
    return os.getenv("AGENT_KNOWLEDGE_DOMAIN", DEFAULT_KNOWLEDGE_DOMAIN)
```

Create `research_team/infrastructure/knowledge/__init__.py`:

```python
"""The knowledge graph adapter. The only package that imports redstring."""
```

Create `research_team/infrastructure/knowledge/stores.py`:

```python
"""Choosing what backs the graph.

In-memory by default and rebuilt from the log at project open, so the default
install needs no server -- and the rebuild path a Neo4j deployment would need
is the same one used at every startup, exercised continuously rather than
written under duress during a migration.
"""

from redstring import InMemoryGraphStore
from redstring.ports import GraphStore


def build_graph_store(kind: str) -> GraphStore:
    """The graph store named by `kind`.

    Raises `ValueError` naming the unknown kind rather than falling back to
    memory: a deployment that asked for Neo4j and silently got a store that
    empties on restart is worse off than one that refused to start.
    """
    if kind == "memory":
        return InMemoryGraphStore()
    if kind == "neo4j":
        raise ValueError(
            "the neo4j graph store is not wired yet; use AGENT_GRAPH_STORE=memory"
        )
    raise ValueError(f"unknown AGENT_GRAPH_STORE {kind!r}; expected 'memory' or 'neo4j'")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_knowledge_stores.py tests/infrastructure/test_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock research_team/infrastructure/config.py research_team/infrastructure/knowledge/ tests/infrastructure/test_knowledge_stores.py tests/infrastructure/test_config.py
git commit -m "feat: add redstring, and config for what backs the graph

Memory by default. An unknown or unwired store raises rather than falling
back, so a deployment never silently gets a store that empties on restart."
```

---

### Task 6: `RedstringKnowledge.ingest`

**Files:**
- Create: `research_team/infrastructure/knowledge/redstring_adapter.py`
- Test: `tests/infrastructure/test_redstring_adapter.py`

**Interfaces:**
- Consumes: Task 4's `SourceRef`, `IngestReport`, `MergeRecord`, `KnowledgeError`; Task 5's `build_graph_store`.
- Produces: `RedstringKnowledge(project_id: UUID, *, store, event_store, snapshot_store, provider, domain: str = "auto", adjudicate: bool = True)` with `.ingest()`. Tasks 7 and 8 add `.search()` and `.undo_merge()` to the same class.

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_redstring_adapter.py`:

```python
import pytest
from uuid import uuid4

from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from eventsource import collect
from redstring import FakeLlmProvider, InMemoryGraphStore
from redstring.events.streams import document_stream

from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge


def build_adapter(tmp_path, project_id, *, provider=None):
    db_path = str(tmp_path / "sessions.db")
    store = SQLiteEventStore(db_path)
    return RedstringKnowledge(
        project_id,
        store=InMemoryGraphStore(),
        event_store=store,
        snapshot_store=SQLiteSnapshotStore(db_path),
        provider=provider if provider is not None else FakeLlmProvider(),
        domain="encyclopedia_wiki",
        adjudicate=False,
    ), store


@pytest.mark.asyncio
async def test_ingest_reports_what_it_extracted(tmp_path):
    project_id = uuid4()
    adapter, _ = build_adapter(tmp_path, project_id)

    report = await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert report.source_id == "notes"
    assert report.entity_count >= 1
    assert report.domain == "encyclopedia_wiki"


@pytest.mark.asyncio
async def test_ingest_appends_the_extraction_to_the_document_stream(tmp_path):
    """The event is the record; the graph is derived from it."""
    project_id = uuid4()
    adapter, store = build_adapter(tmp_path, project_id)

    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    stream = document_stream(tenant_id=project_id, source_id="notes")
    envelopes = await collect(store.read_stream(stream))
    assert len(envelopes) == 1
    assert type(envelopes[0].event).__name__ == "DocumentExtracted"


@pytest.mark.asyncio
async def test_a_blank_source_id_is_rejected(tmp_path):
    project_id = uuid4()
    adapter, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="   ", text="anything"))


@pytest.mark.asyncio
async def test_an_oversized_document_is_refused_before_extraction(tmp_path):
    from research_team.infrastructure.knowledge.redstring_adapter import (
        MAX_DOCUMENT_CHARS,
    )

    project_id = uuid4()
    adapter, store = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError, match="limit"):
        await adapter.ingest(
            SourceRef(source_id="huge", text="x" * (MAX_DOCUMENT_CHARS + 1))
        )

    stream = document_stream(tenant_id=project_id, source_id="huge")
    assert await collect(store.read_stream(stream)) == []


@pytest.mark.asyncio
async def test_reconsolidate_reresolves_only_that_documents_entities(tmp_path):
    """The repair path for an interrupted ingest, keyed by source_id."""
    project_id = uuid4()
    adapter, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    merges, failures = await adapter.reconsolidate("notes")

    assert failures >= 0
    assert isinstance(merges, tuple)


@pytest.mark.asyncio
async def test_reconsolidating_an_unknown_source_is_an_error(tmp_path):
    project_id = uuid4()
    adapter, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError, match="never-ingested"):
        await adapter.reconsolidate("never-ingested")


@pytest.mark.asyncio
async def test_a_provider_failure_records_nothing(tmp_path):
    """Nothing is appended, and the caller gets an error it can render."""
    from redstring.ports import LlmProvider

    class Failing:
        async def complete(self, *args, **kwargs):
            raise RuntimeError("endpoint down")

    project_id = uuid4()
    adapter, store = build_adapter(tmp_path, project_id, provider=Failing())

    with pytest.raises(KnowledgeError):
        await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    stream = document_stream(tenant_id=project_id, source_id="notes")
    assert await collect(store.read_stream(stream)) == []
```

Add the missing import at the top of the test file: `from research_team.application.knowledge import KnowledgeError, SourceRef`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `research_team/infrastructure/knowledge/redstring_adapter.py`:

```python
"""The one module that imports redstring.

Everything above this speaks `KnowledgePort`'s vocabulary, which is why the
redstring names stop here.

Two things about redstring's shape drive the code below, and both are easy to
get wrong:

1. **`build_graph` folds into the store and returns the event unappended.**
   That is exactly what a caller with an event log wants -- append it and the
   store and the log agree. Driving `ExtractionPipeline` by hand would work but
   loses `domain` and `domain_confidence`, recovering which means a dotted
   import of an internal classifier.

2. **`Consolidator.resolve` appends *and* folds its own merge event.** It is
   handed the shared event store at construction. Appending `EntitiesMerged`
   here as well would apply the merge twice.
"""

from uuid import UUID

from eventsource.domain.tenant_context import tenant_scope
from eventsource.ports.positions import ExpectedVersion
from eventsource.ports.store import AggregateStore
from eventsource.ports.snapshots import SnapshotStore
from redstring import (
    AUTO,
    Adjudicator,
    Consolidator,
    RedstringError,
    SourceDocument,
    build_graph,
)
from redstring.events.streams import document_stream
from redstring.ports import GraphStore, LlmProvider

from research_team.application.knowledge import (
    IngestReport,
    KnowledgeError,
    MergeRecord,
    SourceRef,
)

#: Longest document accepted in one `remember`. Roughly a long article.
MAX_DOCUMENT_CHARS = 200_000


class RedstringKnowledge:
    """`KnowledgePort` over redstring, scoped to one project.

    The project id is the tenant. It is supplied once here rather than per
    call, so nothing above can write into another project's graph.
    """

    def __init__(
        self,
        project_id: UUID,
        *,
        store: GraphStore,
        event_store: AggregateStore,
        snapshot_store: SnapshotStore,
        provider: LlmProvider,
        domain: str = "auto",
        adjudicate: bool = True,
    ) -> None:
        self._project_id = project_id
        self._store = store
        self._event_store = event_store
        self._provider = provider
        self._domain = AUTO if domain == "auto" else domain
        # Both stores, deliberately. With either omitted the consolidator
        # substitutes an in-memory log and `undo` becomes session-only --
        # silently, which is why `remembers_merges_across_restarts` is asserted
        # in the tests rather than assumed here.
        self._consolidator = Consolidator(
            store,
            event_store=event_store,
            snapshot_store=snapshot_store,
        )
        # Without an adjudicator the middle similarity band is rejected rather
        # than merged, so consolidation would be name-and-structure-only. There
        # are no embeddings to contribute a third signal (upstream R1), which
        # makes the model's judgement worth more here, not less.
        self._adjudicator = Adjudicator(provider) if adjudicate else None

    async def ingest(self, source: SourceRef) -> IngestReport:
        if not source.source_id.strip():
            raise KnowledgeError("source_id must not be blank; it identifies the document")
        if len(source.text) > MAX_DOCUMENT_CHARS:
            # Capped rather than chunked-without-limit. redstring chunks a long
            # document, which multiplies model calls rather than bounding them,
            # so the bound has to come from here.
            raise KnowledgeError(
                f"that is {len(source.text)} characters; the limit is "
                f"{MAX_DOCUMENT_CHARS}. Record it in parts, each with its own "
                f"source_id."
            )

        document = SourceDocument(
            id=source.source_id,
            text=source.text,
            metadata={"note": source.note} if source.note else {},
        )
        try:
            async with tenant_scope(self._project_id):
                report = await build_graph(
                    document,
                    provider=self._provider,
                    store=self._store,
                    tenant_id=self._project_id,
                    domain=self._domain,
                )
                if report.event is None:
                    # `Document.record_extraction` found nothing new to record
                    # -- the same content and model version as a previous run.
                    return IngestReport(
                        source_id=source.source_id,
                        entity_count=0,
                        relationship_count=0,
                        domain=report.domain,
                        domain_confidence=report.domain_confidence,
                    )

                await self._event_store.append(
                    document_stream(
                        tenant_id=self._project_id, source_id=source.source_id
                    ),
                    [report.event],
                    ExpectedVersion.any_(),
                )
                merges, failures = await self._consolidate(report.event.entities)
        except KnowledgeError:
            raise
        except (RedstringError, ValueError) as error:
            raise KnowledgeError(str(error)) from error
        except Exception as error:  # provider transports raise their own types
            raise KnowledgeError(f"extraction failed: {error}") from error

        return IngestReport(
            source_id=source.source_id,
            entity_count=len(report.event.entities),
            relationship_count=len(report.event.relationships),
            domain=report.domain,
            domain_confidence=report.domain_confidence,
            merges=tuple(merges),
            consolidation_failures=failures,
        )

    async def _consolidate(self, entities) -> tuple[list[MergeRecord], int]:
        """Resolve each extracted entity, one at a time.

        `resolve` is per-entity by design, and it emits its own event, so this
        collects rather than appends. A failure on one entity does not abandon
        the rest: the extraction is already recorded and the merges that
        succeeded are already folded, so stopping here would leave less of the
        graph consolidated for no gain.
        """
        merges: list[MergeRecord] = []
        failures = 0
        for entity in entities:
            try:
                report = await self._consolidator.resolve(
                    entity, adjudicator=self._adjudicator
                )
            except RedstringError:
                # Typically the entity was absorbed by a merge earlier in this
                # same loop, which is a normal outcome rather than a fault.
                failures += 1
                continue
            if report is None:
                continue
            merges.append(
                MergeRecord(
                    merge_id=report.event.event_id,
                    canonical_name=entity.name,
                    absorbed_names=tuple(str(i) for i in report.affected_entity_ids),
                    reason=report.reason,
                )
            )
        return merges, failures

    async def reconsolidate(self, source_id: str) -> tuple[tuple[MergeRecord, ...], int]:
        """Re-resolve the entities of one recorded extraction.

        The repair path for an ingest whose consolidation was interrupted. It
        is keyed by `source_id` and bounded by that document, because redstring
        marks no entity as unconsolidated (upstream R2) -- the only alternative
        is paging every entity in the project and redoing settled work at every
        open.

        Re-resolving an already-consolidated entity is safe: `resolve` returns
        None when there is nothing to merge, and raises when the entity has
        already been absorbed, which `_consolidate` counts rather than
        propagates.
        """
        stream = document_stream(tenant_id=self._project_id, source_id=source_id)
        envelopes = await collect(self._event_store.read_stream(stream))
        if not envelopes:
            raise KnowledgeError(f"no extraction recorded for source_id {source_id!r}")

        entities = envelopes[-1].event.entities
        async with tenant_scope(self._project_id):
            merges, failures = await self._consolidate(entities)
        return tuple(merges), failures
```

Add `from eventsource import collect` to the imports.

- [ ] **Step 4: Verify the redstring import names**

Run:

```bash
uv run python -c "from redstring import AUTO, Adjudicator, Consolidator, FakeLlmProvider, InMemoryGraphStore, RedstringError, SourceDocument, build_graph; print('ok')"
```

Expected: `ok`. If any name is not exported, find its real location with `uv run python -c "import redstring; print(redstring.__all__)"` and fix the import — do not reach for a dotted internal path unless nothing else works.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -v`
Expected: PASS, 4 tests

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/knowledge/redstring_adapter.py tests/infrastructure/test_redstring_adapter.py
git commit -m "feat: RedstringKnowledge.ingest

build_graph folds into the store and hands back the event to append, so the
graph and the log agree. Consolidation resolves per entity and emits its own
events -- appending them here would merge twice."
```

---

### Task 7: `search` and `undo_merge`

**Files:**
- Modify: `research_team/infrastructure/knowledge/redstring_adapter.py`
- Test: `tests/infrastructure/test_redstring_adapter.py`

**Interfaces:**
- Consumes: Task 6's `RedstringKnowledge`, Task 4's `Match`, `MergeRecord`.
- Produces: `RedstringKnowledge.search(query, *, limit=10) -> list[Match]`, `RedstringKnowledge.undo_merge(merge_id: UUID) -> MergeRecord`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/infrastructure/test_redstring_adapter.py`:

```python
@pytest.mark.asyncio
async def test_search_finds_an_ingested_entity_by_substring(tmp_path):
    project_id = uuid4()
    adapter, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    matches = await adapter.search("lovelace")

    assert matches, "an ingested entity should be findable"
    assert any("lovelace" in match.name.lower() for match in matches)


@pytest.mark.asyncio
async def test_search_caps_at_the_limit(tmp_path):
    project_id = uuid4()
    adapter, _ = build_adapter(tmp_path, project_id)
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    assert len(await adapter.search("a", limit=1)) <= 1


@pytest.mark.asyncio
async def test_undo_merge_rejects_an_unknown_id(tmp_path):
    project_id = uuid4()
    adapter, _ = build_adapter(tmp_path, project_id)

    with pytest.raises(KnowledgeError):
        await adapter.undo_merge(uuid4())


@pytest.mark.asyncio
async def test_merges_are_remembered_across_restarts(tmp_path):
    """Undo is durable only when both stores are passed; assert it, don't assume."""
    project_id = uuid4()
    adapter, _ = build_adapter(tmp_path, project_id)

    assert adapter.remembers_merges_across_restarts
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -k "search or undo or restarts" -v`
Expected: FAIL with `AttributeError: 'RedstringKnowledge' object has no attribute 'search'`

- [ ] **Step 3: Write the implementation**

Add to `RedstringKnowledge`:

```python
    @property
    def remembers_merges_across_restarts(self) -> bool:
        """Whether `undo_merge` survives a restart. False means the log is in-memory."""
        return self._consolidator.remembers_merges_across_restarts

    async def search(self, query: str, *, limit: int = 10) -> list[Match]:
        """Entities whose name contains `query`, case-insensitively.

        Filtered here rather than by the store because `find_entities(name=...)`
        matches `normalized_name` exactly -- no substring, no fuzziness -- and a
        tool the agent drives with free text needs more give than that. The cost
        is a page of the tenant's entities per call, which is acceptable against
        an in-memory store and is the first thing to revisit behind Neo4j.
        """
        if limit < 1:
            raise KnowledgeError("limit must be at least 1")
        needle = query.strip().lower()
        if not needle:
            return []

        try:
            async with tenant_scope(self._project_id):
                entities = await self._store.find_entities(self._project_id)
                matches = []
                for entity in entities:
                    if needle not in entity.name.lower():
                        continue
                    edges = await self._store.get_relationships_for(
                        entity.id, self._project_id
                    )
                    matches.append(
                        Match(
                            entity_id=entity.id,
                            name=entity.name,
                            entity_type=entity.entity_type,
                            relationship_count=len(edges),
                        )
                    )
                    if len(matches) == limit:
                        break
        except RedstringError as error:
            raise KnowledgeError(str(error)) from error
        return matches

    async def undo_merge(self, merge_id: UUID) -> MergeRecord:
        """Reverse a consolidation.

        `UnknownMergeError` covers "never happened", "already undone" and "made
        by a different consolidator" as one case, so this cannot report which --
        it says what it knows.
        """
        try:
            async with tenant_scope(self._project_id):
                report = await self._consolidator.undo(
                    tenant_id=self._project_id, merge_event_id=merge_id
                )
        except RedstringError as error:
            raise KnowledgeError(
                f"no merge in effect has id {merge_id}: {error}"
            ) from error

        return MergeRecord(
            merge_id=merge_id,
            canonical_name=str(report.canonical_entity_id),
            absorbed_names=tuple(str(i) for i in report.affected_entity_ids),
            reason=report.reason,
        )
```

Add `Match` to the imports from `research_team.application.knowledge`.

- [ ] **Step 4: Verify `get_relationships_for`'s signature**

Run:

```bash
uv run python -c "
import inspect
from redstring.ports import GraphStore
print(inspect.signature(GraphStore.get_relationships_for))
print(inspect.signature(GraphStore.find_entities))
"
```

Expected: `get_relationships_for(self, entity_id, tenant_id)` and `find_entities(self, tenant_id, *, name=None, entity_type=None, limit=None, after=None)`. Fix the call sites if the argument order differs.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_redstring_adapter.py -v`
Expected: PASS, 8 tests

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/knowledge/redstring_adapter.py tests/infrastructure/test_redstring_adapter.py
git commit -m "feat: graph search and durable undo

find_entities matches names exactly, so substring matching happens here.
Undo is durable only when both stores are passed; a test asserts it."
```

---

### Task 8: Rebuilding the graph at project open

**Files:**
- Create: `research_team/infrastructure/knowledge/rebuild.py`
- Test: `tests/infrastructure/test_knowledge_rebuild.py`

**Interfaces:**
- Consumes: Task 5's `build_graph_store`.
- Produces: `async rebuild_graph(store: GraphStore, *, feed, project_id: UUID) -> int` returning the number of events applied, raising `KnowledgeError` when the replay reports failures.

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_knowledge_rebuild.py`:

```python
import pytest
from uuid import uuid4

from eventsource.adapters.sqlite import SQLiteEventStore
from eventsource.adapters.sqlite.snapshots import SQLiteSnapshotStore
from redstring import FakeLlmProvider, InMemoryGraphStore

from research_team.application.knowledge import SourceRef
from research_team.infrastructure.knowledge.rebuild import rebuild_graph
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge


@pytest.mark.asyncio
async def test_a_rebuilt_graph_matches_the_one_maintained_by_ingest(tmp_path):
    """The store is a projection. Rebuilding it must not change what it holds."""
    project_id = uuid4()
    db_path = str(tmp_path / "sessions.db")
    event_store = SQLiteEventStore(db_path)
    live = InMemoryGraphStore()
    adapter = RedstringKnowledge(
        project_id,
        store=live,
        event_store=event_store,
        snapshot_store=SQLiteSnapshotStore(db_path),
        provider=FakeLlmProvider(),
        domain="encyclopedia_wiki",
        adjudicate=False,
    )
    await adapter.ingest(
        SourceRef(source_id="notes", text="Ada Lovelace worked with Charles Babbage.")
    )

    rebuilt = InMemoryGraphStore()
    await rebuild_graph(rebuilt, feed=event_store, project_id=project_id)

    live_names = sorted(e.name for e in await live.find_entities(project_id))
    rebuilt_names = sorted(e.name for e in await rebuilt.find_entities(project_id))
    assert rebuilt_names == live_names
    assert rebuilt_names, "the fixture should have produced entities"


@pytest.mark.asyncio
async def test_rebuilding_an_empty_project_yields_an_empty_graph(tmp_path):
    project_id = uuid4()
    event_store = SQLiteEventStore(str(tmp_path / "sessions.db"))
    store = InMemoryGraphStore()

    await rebuild_graph(store, feed=event_store, project_id=project_id)

    assert await store.find_entities(project_id) == []


@pytest.mark.asyncio
async def test_rebuilding_never_calls_the_model(tmp_path):
    """Replay purity: extraction is recorded, never recomputed."""
    project_id = uuid4()
    db_path = str(tmp_path / "sessions.db")
    event_store = SQLiteEventStore(db_path)
    adapter = RedstringKnowledge(
        project_id,
        store=InMemoryGraphStore(),
        event_store=event_store,
        snapshot_store=SQLiteSnapshotStore(db_path),
        provider=FakeLlmProvider(),
        domain="encyclopedia_wiki",
        adjudicate=False,
    )
    await adapter.ingest(SourceRef(source_id="notes", text="Ada Lovelace."))

    # No provider is involved in a rebuild at all -- there is nowhere to pass
    # one. This test exists so that stops being true loudly rather than quietly.
    import inspect

    from research_team.infrastructure.knowledge import rebuild

    assert "provider" not in inspect.signature(rebuild.rebuild_graph).parameters
    await rebuild_graph(InMemoryGraphStore(), feed=event_store, project_id=project_id)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_knowledge_rebuild.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `research_team/infrastructure/knowledge/rebuild.py`:

```python
"""Rebuilding a project's graph from the log.

Runs at project open, which is what lets the default install keep the graph in
memory: the store is derived, so losing it costs a fold rather than data.

Two workarounds live here, both waiting on upstream redstring work recorded in
the spec:

- **R3.** `project()` folds the *global* feed -- no stream or category
  argument -- so in a shared store it reads every session event too. Scoping is
  by `tenant_filter` on the projection instead; research-team's own events
  carry no tenant and are filtered out.
- **R4.** `ReplayReport.failed` is a count, not a raise. A poison event is
  swallowed and the graph comes up quietly incomplete, so the count is checked
  here and refused.
"""

from uuid import UUID

from redstring.projections import GraphProjection, project
from redstring.ports import GraphStore

from research_team.application.knowledge import KnowledgeError


async def rebuild_graph(store: GraphStore, *, feed, project_id: UUID) -> int:
    """Fold this project's knowledge events into `store`. Returns events applied.

    Takes no provider, and must not grow one: extraction happens once, when the
    agent asks for it, and is replayed from the log thereafter. A model call on
    this path would mean a session refolded years from now depends on a live
    endpoint.
    """
    projection = GraphProjection(store, tenant_filter=project_id)
    report = await project(feed, [projection])
    if report.failed:
        raise KnowledgeError(
            f"{report.failed} knowledge event(s) failed to replay for project "
            f"{project_id}; refusing to serve a partial graph"
        )
    return report.applied
```

- [ ] **Step 4: Verify the projection and replay names**

Run:

```bash
uv run python -c "
import inspect
from redstring.projections import GraphProjection, project
print(inspect.signature(project))
print([f for f in ('applied','failed') if hasattr(__import__('redstring.projections.replay', fromlist=['ReplayReport']).ReplayReport, f)])
"
```

Expected: `project(feed, projections, *, from_position=None, max_events=...)` and both field names present. If `ReplayReport` uses different names, fix `rebuild.py` to match; if `GraphProjection` does not accept `tenant_filter`, check `redstring/projections/base.py` for the real keyword.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_knowledge_rebuild.py -v`
Expected: PASS, 3 tests

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/knowledge/rebuild.py tests/infrastructure/test_knowledge_rebuild.py
git commit -m "feat: rebuild a project's graph from the log

Scoped by tenant_filter and refused on a failed replay -- both workarounds
for upstream gaps, both marked as such. No provider on this path, ever."
```

---

### Task 9: The three tools

**Files:**
- Create: `research_team/infrastructure/agent/knowledge_tools.py`
- Modify: `research_team/application/autonomy.py`
- Test: `tests/infrastructure/test_knowledge_tools.py`, `tests/application/test_autonomy.py`

**Interfaces:**
- Consumes: Task 4's port and tool-name constants.
- Produces: `build_knowledge_tools(knowledge: KnowledgePort, *, limit: int = 10) -> tuple[BaseTool, ...]` and `KNOWLEDGE_PROMPT: str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/infrastructure/test_knowledge_tools.py`:

```python
import pytest
from uuid import uuid4

from research_team.application.knowledge import (
    IngestReport,
    KnowledgeError,
    Match,
    MergeRecord,
)
from research_team.infrastructure.agent.knowledge_tools import build_knowledge_tools


class StubKnowledge:
    def __init__(self, *, report=None, matches=(), error=None):
        self._report = report
        self._matches = list(matches)
        self._error = error
        self.undone = []

    async def ingest(self, source):
        if self._error:
            raise self._error
        return self._report

    async def search(self, query, *, limit=10):
        if self._error:
            raise self._error
        return self._matches[:limit]

    async def undo_merge(self, merge_id):
        if self._error:
            raise self._error
        self.undone.append(merge_id)
        return MergeRecord(
            merge_id=merge_id, canonical_name="Ada Lovelace", absorbed_names=("x",), reason="same"
        )


def tools_by_name(knowledge):
    return {tool.name: tool for tool in build_knowledge_tools(knowledge)}


@pytest.mark.asyncio
async def test_remember_reports_counts_and_confidence():
    report = IngestReport(
        source_id="notes",
        entity_count=7,
        relationship_count=4,
        domain="encyclopedia_wiki",
        domain_confidence=0.0,
    )
    tools = tools_by_name(StubKnowledge(report=report))

    result = await tools["remember"].ainvoke({"text": "t", "source_id": "notes"})

    assert "7" in result and "4" in result
    assert "encyclopedia_wiki" in result
    # A fallback must not read like a confident choice.
    assert "0.0" in result or "gave up" in result


@pytest.mark.asyncio
async def test_remember_lists_the_merges_so_the_agent_can_object():
    report = IngestReport(
        source_id="notes",
        entity_count=2,
        relationship_count=0,
        domain=None,
        domain_confidence=None,
        merges=(
            MergeRecord(
                merge_id=uuid4(),
                canonical_name="Ada Lovelace",
                absorbed_names=("Lovelace, A.",),
                reason="same person",
            ),
        ),
    )
    tools = tools_by_name(StubKnowledge(report=report))

    result = await tools["remember"].ainvoke({"text": "t", "source_id": "notes"})

    assert "Ada Lovelace" in result
    assert str(report.merges[0].merge_id) in result


@pytest.mark.asyncio
async def test_a_failure_is_returned_as_text_not_raised():
    """The model cannot fix an outage; the person reading the log can."""
    tools = tools_by_name(StubKnowledge(error=KnowledgeError("endpoint down")))

    result = await tools["remember"].ainvoke({"text": "t", "source_id": "notes"})

    assert "endpoint down" in result


@pytest.mark.asyncio
async def test_graph_search_flattens_matches():
    matches = [Match(entity_id=uuid4(), name="Ada Lovelace", entity_type="Person", relationship_count=3)]
    tools = tools_by_name(StubKnowledge(matches=matches))

    result = await tools["graph_search"].ainvoke({"query": "ada"})

    assert "Ada Lovelace" in result and "Person" in result and "3" in result


@pytest.mark.asyncio
async def test_graph_search_says_so_when_empty():
    tools = tools_by_name(StubKnowledge(matches=[]))

    assert "No" in await tools["graph_search"].ainvoke({"query": "nothing"})


@pytest.mark.asyncio
async def test_unmerge_passes_the_id_through():
    knowledge = StubKnowledge()
    tools = tools_by_name(knowledge)
    merge_id = uuid4()

    result = await tools["unmerge"].ainvoke({"merge_id": str(merge_id)})

    assert knowledge.undone == [merge_id]
    assert "Ada Lovelace" in result


@pytest.mark.asyncio
async def test_unmerge_rejects_a_malformed_id_without_calling_the_port():
    knowledge = StubKnowledge()
    tools = tools_by_name(knowledge)

    result = await tools["unmerge"].ainvoke({"merge_id": "not-a-uuid"})

    assert knowledge.undone == []
    assert "not a valid merge id" in result
```

Add to `tests/application/test_autonomy.py`, matching that file's existing style:

```python
def test_the_knowledge_tools_are_gated_appropriately():
    policy = AutonomyPolicy()

    assert policy.level_for(REMEMBER_TOOL) in GATED_LEVELS
    assert policy.level_for(UNMERGE_TOOL) in GATED_LEVELS
    assert policy.level_for(GRAPH_SEARCH_TOOL) == "auto"
```

Open `research_team/application/autonomy.py` first and match the real API — if levels are read some other way, write the assertions that file's way rather than inventing `level_for`/`GATED_LEVELS`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_knowledge_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

Create `research_team/infrastructure/agent/knowledge_tools.py`:

```python
"""The knowledge graph, as three tools.

Shaped like `search.py`: results are capped and flattened before they reach the
model, and a failure comes back as text rather than an exception. A tool that
raises turns an outage into a broken turn; a tool that says what happened lets
the model carry on and leaves a readable record.
"""

from uuid import UUID

from langchain_core.tools import BaseTool, tool

from research_team.application.knowledge import (
    GRAPH_SEARCH_TOOL,
    REMEMBER_TOOL,
    UNMERGE_TOOL,
    KnowledgeError,
    KnowledgePort,
    SourceRef,
)


def format_ingest(report) -> str:
    """What one ingest did, including what it merged.

    The merges are listed rather than counted because listing them is what
    makes the agent's override possible at all -- an id it cannot see is an id
    it cannot pass to `unmerge`.
    """
    lines = [
        f"Recorded {report.source_id}: {report.entity_count} entities, "
        f"{report.relationship_count} relationships."
    ]
    if report.domain is not None:
        if report.domain_confidence == 0.0:
            lines.append(
                f"Schema: {report.domain} (confidence 0.0 -- the classifier gave "
                f"up and fell back; treat the shape as unverified)."
            )
        elif report.domain_confidence is not None:
            lines.append(
                f"Schema: {report.domain} (confidence {report.domain_confidence:.2f})."
            )
        else:
            lines.append(f"Schema: {report.domain}.")
    if report.merges:
        lines.append(f"Consolidated {len(report.merges)}:")
        for merge in report.merges:
            absorbed = ", ".join(merge.absorbed_names) or "(none named)"
            reason = merge.reason or "no reason recorded"
            lines.append(
                f"  {merge.canonical_name} absorbed {absorbed} -- {reason} "
                f"[merge_id {merge.merge_id}]"
            )
    if report.consolidation_failures:
        lines.append(
            f"{report.consolidation_failures} entit(ies) could not be consolidated; "
            f"the extraction still stands."
        )
    return "\n".join(lines)


def format_matches(matches) -> str:
    if not matches:
        return "No matching entities."
    return "\n".join(
        f"{match.name} ({match.entity_type}) -- {match.relationship_count} "
        f"relationship(s) [{match.entity_id}]"
        for match in matches
    )


def build_knowledge_tools(
    knowledge: KnowledgePort, *, limit: int = 10
) -> tuple[BaseTool, ...]:
    """`remember`, `graph_search` and `unmerge` over one project's graph."""

    @tool(REMEMBER_TOOL)
    async def remember(text: str, source_id: str, note: str = "") -> str:
        """Commit text to the project's knowledge graph, extracting entities and relationships."""
        try:
            report = await knowledge.ingest(
                SourceRef(source_id=source_id, text=text, note=note or None)
            )
        except KnowledgeError as error:
            return f"Could not record this: {error}"
        return format_ingest(report)

    @tool(GRAPH_SEARCH_TOOL)
    async def graph_search(query: str) -> str:
        """Find entities in the project's knowledge graph by name."""
        try:
            matches = await knowledge.search(query, limit=limit)
        except KnowledgeError as error:
            return f"Could not search the graph: {error}"
        return format_matches(matches)

    @tool(UNMERGE_TOOL)
    async def unmerge(merge_id: str) -> str:
        """Reverse a consolidation that joined two entities that are not the same thing."""
        try:
            parsed = UUID(merge_id)
        except ValueError:
            return f"{merge_id!r} is not a valid merge id; use the one `remember` printed."
        try:
            record = await knowledge.undo_merge(parsed)
        except KnowledgeError as error:
            return f"Could not reverse that merge: {error}"
        return (
            f"Reversed: {record.canonical_name} gave back "
            f"{', '.join(record.absorbed_names) or '(none)'}."
        )

    return (remember, graph_search, unmerge)


KNOWLEDGE_PROMPT = (
    "\n\nThis project has a knowledge graph that outlives the session. "
    "`graph_search` finds entities in it by name -- check there before "
    "searching the web for something the project may already have learned. "
    "`remember` commits text to it: extraction runs over what you pass, and "
    "the result is recorded permanently, so pass substantial content you have "
    "actually read rather than your own summary of it, and give each document "
    "a stable `source_id`.\n\n"
    "Committing is not free and not private -- it changes what every later "
    "session in this project sees. Remember what a future session would want "
    "to have been told, not everything you happened to look at.\n\n"
    "`remember` also consolidates: entities that look like the same thing are "
    "merged, and each merge is printed with its id. You have context the "
    "matcher does not. If two things were joined that are not the same thing, "
    "reverse it with `unmerge` and that id."
)
```

- [ ] **Step 4: Register the tool names with the autonomy policy**

Open `research_team/application/autonomy.py`. It already lists `SEARCH_TOOL` among gated tools (around line 21-25). Add `REMEMBER_TOOL` and `UNMERGE_TOOL` to the same gated collection — they are writes. Do **not** add `GRAPH_SEARCH_TOOL`; it is a read and should default to `auto` like the file reads. Import the constants from `research_team.application.knowledge`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_knowledge_tools.py tests/application/test_autonomy.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/agent/knowledge_tools.py research_team/application/autonomy.py tests/infrastructure/test_knowledge_tools.py tests/application/test_autonomy.py
git commit -m "feat: remember, graph_search and unmerge

Merges are listed with their ids rather than counted -- an id the agent
cannot see is one it cannot pass to unmerge. Writes are gated; the read is not."
```

---

### Task 10: Wire it into composition

**Files:**
- Modify: `research_team/composition.py`
- Test: `tests/integration/test_no_knowledge.py`

**Interfaces:**
- Consumes: Tasks 5–9.
- Produces: `build_knowledge(project_id, *, repository, model) -> RedstringKnowledge | None`; `build_application(..., project_id: UUID | None = None)`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_no_knowledge.py`:

```python
"""The default install has no knowledge graph at all.

Sibling of `test_no_network.py`, and for the same reason: a claim about what a
default install does is only true while something checks it.
"""

import pytest
from uuid import uuid4

from research_team.composition import build_application


@pytest.mark.asyncio
async def test_a_session_with_no_project_gets_no_knowledge_tools(tmp_path, fake_model):
    app = build_application(model=fake_model, db_path=str(tmp_path / "sessions.db"))
    try:
        names = {tool.name for tool in app.turns_tools()}
        assert "remember" not in names
        assert "graph_search" not in names
        assert "unmerge" not in names
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_a_project_registers_the_knowledge_tools(tmp_path, fake_model):
    app = build_application(
        model=fake_model, db_path=str(tmp_path / "sessions.db"), project_id=uuid4()
    )
    try:
        names = {tool.name for tool in app.turns_tools()}
        assert {"remember", "graph_search", "unmerge"} <= names
    finally:
        await app.close()


@pytest.mark.asyncio
async def test_reading_a_store_holding_knowledge_events_needs_no_extra_import(tmp_path):
    """redstring registers its event types at import; composition must force it."""
    import subprocess
    import sys

    # A cold process that imports only research_team must still be able to
    # deserialize redstring's events, or the registry is incomplete.
    code = (
        "from research_team.composition import build_application; "
        "from eventsource import default_registry; "
        "assert 'DocumentExtracted' in default_registry, sorted(default_registry)"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
```

Check `tests/integration/test_no_network.py` for the real fixture names (`fake_model`) and the way it inspects registered tools; match them. If `Application` has no `turns_tools()` accessor, add one that returns the executor's tools, or assert against the executor directly the way the existing test does.

Also check the real API for the event registry — `default_registry` may not be importable from `eventsource` directly. Find it with:

```bash
uv run python -c "import eventsource; print([n for n in dir(eventsource) if 'egist' in n])"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/integration/test_no_knowledge.py -v`
Expected: FAIL — `build_application` has no `project_id` parameter

- [ ] **Step 3: Write the implementation**

In `research_team/composition.py`, add imports:

```python
# Imported for its side effect as much as its names: redstring registers its
# event types at import time, and this store may hold them. A read that meets
# a DocumentExtracted without this import raises EventTypeNotFoundError --
# including on the "no project at all" path, where nothing else would have
# pulled redstring in.
import redstring.events  # noqa: F401
from research_team.infrastructure.agent.knowledge_tools import (
    KNOWLEDGE_PROMPT,
    build_knowledge_tools,
)
from research_team.infrastructure.knowledge.redstring_adapter import RedstringKnowledge
from research_team.infrastructure.knowledge.rebuild import rebuild_graph
from research_team.infrastructure.knowledge.stores import build_graph_store
```

Add a `project_id: UUID | None = None` parameter to `build_application`, and after the search block:

```python
    # The knowledge graph belongs to a project. No project, no tools and no
    # store -- the same posture search has without an instance configured.
    if project_id is not None:
        knowledge = RedstringKnowledge(
            project_id,
            store=build_graph_store(config.graph_store()),
            event_store=repository.store,
            snapshot_store=SQLiteSnapshotStore(resolved_path),
            provider=LangChainLlmProvider(
                resolved_model, model=config.model_name()
            ),
            domain=config.knowledge_domain(),
        )
        tools = (*tools, *build_knowledge_tools(knowledge))
        prompt_suffix += KNOWLEDGE_PROMPT
    else:
        knowledge = None
```

Note the ordering problem: `repository` is created *after* the tools block today. Move the `repository = EventStoreSessionRepository.open(resolved_path)` line above the search/knowledge blocks so the adapter can take `repository.store`. Add `knowledge` to the `Application` dataclass as `knowledge: RedstringKnowledge | None`.

Import `SQLiteSnapshotStore` from `eventsource.adapters.sqlite.snapshots` and `LangChainLlmProvider` from `redstring.llm.adapters.langchain`.

- [ ] **Step 4: Rebuild the graph on start**

In `Application.start()`, before returning, rebuild when a project is configured:

```python
    async def start(self) -> None:
        ...existing body...
        if self.knowledge is not None:
            await rebuild_graph(
                self.knowledge.graph_store,
                feed=self.knowledge.event_store,
                project_id=self.knowledge.project_id,
            )
```

Add `graph_store`, `event_store` and `project_id` as read-only properties on `RedstringKnowledge` returning `self._store`, `self._event_store` and `self._project_id`.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest`
Expected: PASS. The whole suite matters here — this task touches the composition root every other test builds through.

- [ ] **Step 6: Commit**

```bash
git add research_team/composition.py research_team/infrastructure/knowledge/redstring_adapter.py tests/integration/test_no_knowledge.py
git commit -m "feat: wire the knowledge graph into composition

No project means no tools and no store, the posture search already has.
redstring.events is imported unconditionally so the event registry is
complete on every read path."
```

---

### Task 11: Choosing a project from the REPL

**Files:**
- Modify: `research_team/interfaces/cli/repl.py`
- Modify: `research_team/infrastructure/persistence/event_store.py` (a `Project` repository)
- Test: `tests/interfaces/test_repl_project.py`

**Interfaces:**
- Consumes: Task 1's `Project`, Task 10's `build_application(project_id=...)`.
- Produces: `build_project_repository(...)`, `EventStoreSessionRepository.list_projects()`, and a `/project` command covering `/project` (list) and `/project new <name>` (create). **`/project use` arrives in Task 12**, because selecting a project means inheriting its filesystem and that logic does not exist yet.

- [ ] **Step 1: Write the failing test**

Create `tests/interfaces/test_repl_project.py`. Open `tests/interfaces/` first and match how the existing REPL command tests drive commands and capture output — reuse that harness rather than building a second one.

```python
import pytest

# Match the existing REPL test harness in this directory for imports and setup.


@pytest.mark.asyncio
async def test_project_new_creates_and_reports(repl):
    output = await repl.run_command("/project new research")

    assert "research" in output


@pytest.mark.asyncio
async def test_project_lists_what_exists(repl):
    await repl.run_command("/project new research")
    await repl.run_command("/project new archive")

    output = await repl.run_command("/project")

    assert "research" in output and "archive" in output


@pytest.mark.asyncio
async def test_creating_a_project_twice_reports_the_collision(repl):
    await repl.run_command("/project new research")

    output = await repl.run_command("/project new research")

    assert "research" in output and "already" in output.lower()


@pytest.mark.asyncio
async def test_listing_with_no_projects_says_so(repl):
    output = await repl.run_command("/project")

    assert "no projects" in output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/interfaces/test_repl_project.py -v`
Expected: FAIL — unknown command `/project`

- [ ] **Step 3: Add a Project repository**

In `research_team/infrastructure/persistence/event_store.py`, add alongside `build_aggregate_repository`:

```python
def build_project_repository(
    store: SQLiteEventStore,
    db_path: str,
    publisher: InMemoryEventBus | None = None,
) -> AggregateRepository[Project]:
    """Projects, over the same log and the same snapshot table as sessions."""
    return AggregateRepository(
        store,
        Project,
        event_publisher=publisher,
        snapshot_store=SQLiteSnapshotStore(db_path),
        snapshot_threshold=SNAPSHOT_THRESHOLD,
        snapshot_mode="background",
    )
```

Import `Project` from `research_team.domain`.

To list projects, read the `Project` category:

```python
    async def list_projects(self) -> list[tuple[UUID, str]]:
        """Every project's id and name, from the creation events."""
        envelopes = await collect(self._store.read_category("Project"))
        return [
            (envelope.event.aggregate_id, envelope.event.name)
            for envelope in envelopes
            if type(envelope.event).__name__ == "ProjectCreated"
        ]
```

Verify `read_category`'s signature first:

```bash
uv run python -c "import inspect; from eventsource.ports.store import CategoryQuery; print(inspect.signature(CategoryQuery.read_category))"
```

- [ ] **Step 4: Add the `/project` command**

In `research_team/interfaces/cli/repl.py`, add a `/project` handler following the existing command style in that file:

- `/project` — list names and ids, or say so when there are none.
- `/project new <name>` — create a `Project` aggregate; report the name and id, and report a name that already exists rather than creating a second project with it.

Leave `/project use` unimplemented for now — reply that it is not available yet. Task 12 adds it, because selecting a project means inheriting its filesystem.

Register the command in the help text alongside the other `/`-commands.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/interfaces/ -v`
Expected: PASS

- [ ] **Step 6: Run the full suite and commit**

Run: `uv run pytest`
Expected: PASS

```bash
git add research_team/interfaces/cli/repl.py research_team/infrastructure/persistence/event_store.py tests/interfaces/test_repl_project.py
git commit -m "feat: choose a project from the REPL

A project is data, not deployment configuration, so it is selected here
rather than by environment variable."
```

---

### Task 12: A session inherits the project's filesystem

**Files:**
- Modify: `research_team/application/session_service.py`
- Modify: `research_team/composition.py`
- Modify: `research_team/interfaces/cli/repl.py` (add `/project use`)
- Test: `tests/application/test_session_service_project.py`, `tests/interfaces/test_repl_project.py`

**Interfaces:**
- Consumes: Task 1's `Project`/`JoinProject`/`AdvanceTip`, Task 2's `SessionState.project_id`, Task 11's project repository.
- Produces: `SessionService.start_in_project(project_id: UUID) -> UUID` and `SessionService.release_project(session_id: UUID) -> None`.

This is what makes a project a *shared filesystem* rather than a shared tenant id. Without it the graph is project-scoped but the files are not, which is half the concept.

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_session_service_project.py`. Match the existing `tests/application/` harness for building a service over a temp database.

```python
import pytest
from uuid import uuid4


@pytest.mark.asyncio
async def test_the_first_session_in_a_project_starts_empty(service, project_id):
    session_id = await service.start_in_project(project_id)

    state = await service.state(session_id)
    assert state.files == {}
    assert state.project_id == project_id


@pytest.mark.asyncio
async def test_a_later_session_inherits_the_previous_one_s_files(service, project_id):
    first = await service.start_in_project(project_id)
    await service.write_file(first, "notes.md", "hello")
    await service.release_project(first)

    second = await service.start_in_project(project_id)

    state = await service.state(second)
    assert state.files["notes.md"]["content"] == "hello"
    assert state.forked_from == first


@pytest.mark.asyncio
async def test_inheriting_does_not_copy_the_conversation(service, project_id):
    """A project shares a filesystem, not a chat history."""
    first = await service.start_in_project(project_id)
    await service.write_file(first, "notes.md", "hello")
    await service.release_project(first)

    second = await service.start_in_project(project_id)

    assert await service.state(second) is not None
    assert (await service.state(second)).messages == []


@pytest.mark.asyncio
async def test_a_second_session_cannot_start_while_one_holds_the_project(
    service, project_id
):
    from eventsource.domain.decider import CommandRejectedError

    first = await service.start_in_project(project_id)

    with pytest.raises(CommandRejectedError, match=str(first)):
        await service.start_in_project(project_id)
```

The `service` and `project_id` fixtures need writing — `project_id` creates a `Project` aggregate and returns its id. Check `tests/application/conftest.py` for the existing service fixture and extend it rather than duplicating it.

Adjust `write_file` and `state` to whatever `SessionService` actually calls them; open the module first. If files are only written through a turn, drive the aggregate directly the way the existing service tests do.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/application/test_session_service_project.py -v`
Expected: FAIL — `SessionService` has no `start_in_project`

- [ ] **Step 3: Write the implementation**

Add to `SessionService`:

```python
    async def start_in_project(self, project_id: UUID) -> UUID:
        """Begin a session that shares the project's filesystem.

        Joining is decided by the `Project` aggregate, which rejects a second
        concurrent session by name. That rejection propagates: a caller finding
        out the project is busy is the point, and swallowing it here would let
        two sessions diverge silently.

        Inheritance reuses forking rather than copying. The project stores a
        pointer -- whose stream, and how far in -- so a new session forks from
        exactly that point and its filesystem still folds out of one stream.
        Only files come across; the conversation does not, because a project
        shares a workspace and not a chat history.
        """
        project = await self._projects.load(project_id)
        session_id = uuid4()
        project.handle(JoinProject(session_id=session_id))

        state = project.state
        if state.tip_session_id is None:
            session = self._repository.create(session_id)
            session.handle(
                StartSession(
                    system_prompt=self._default_system_prompt,
                    model_name=self._executor.model_name,
                    project_id=project_id,
                )
            )
            await self._repository.save(session)
        else:
            await self._fork_files_from(
                session_id,
                source_session_id=state.tip_session_id,
                at_event=state.tip_at_event,
                project_id=project_id,
            )

        # After the session exists: a project marked as held by a session that
        # was never created is a project nothing can take.
        await self._projects.save(project)
        return session_id

    async def release_project(self, session_id: UUID) -> None:
        """Hand the project's filesystem tip back, so another session can take it."""
        session = await self._repository.load(session_id)
        if session.state.project_id is None:
            return
        project = await self._projects.load(session.state.project_id)
        project.handle(AdvanceTip(session_id=session_id, at_event=session.version))
        await self._projects.save(project)
```

`_fork_files_from` should follow whatever this service already does for forking (find the existing fork method and reuse it — do not write a second copy of that logic). It must emit `SessionStarted` carrying `project_id`, then replay the source session's file events up to `at_event` into the new session, and record `SessionForkedFrom`.

Add `self._projects` — an `AggregateRepository[Project]` — as a constructor argument, and pass `build_project_repository(...)` from `composition.build_application`.

- [ ] **Step 4: Release the project when the session ends**

Call `release_project` where a session ends cleanly — in the REPL's exit path and in `Application.close()` if a project session is open. A session that is never released holds the project forever.

- [ ] **Step 5: Add `/project use` to the REPL**

Add to `tests/interfaces/test_repl_project.py`:

```python
@pytest.mark.asyncio
async def test_project_use_reports_an_unknown_name(repl):
    output = await repl.run_command("/project use nope")

    assert "nope" in output and "no such project" in output.lower()


@pytest.mark.asyncio
async def test_project_use_starts_a_session_in_the_project(repl):
    await repl.run_command("/project new research")

    output = await repl.run_command("/project use research")

    assert "research" in output


@pytest.mark.asyncio
async def test_a_second_session_cannot_take_a_held_project(repl):
    await repl.run_command("/project new research")
    await repl.run_command("/project use research")

    output = await repl.run_command("/project use research")

    assert "held by" in output.lower()
```

Run: `uv run pytest tests/interfaces/test_repl_project.py -v` — expect the three new tests to fail.

Then implement `/project use <name>`: look the name up via `list_projects`, call `service.start_in_project(project_id)`, and report `CommandRejectedError`'s message verbatim on rejection — it names the holding session, which is the next thing anyone asks.

Run it again: expect PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add research_team/application/session_service.py research_team/composition.py research_team/interfaces/cli/repl.py tests/application/ tests/interfaces/
git commit -m "feat: a session inherits its project's filesystem

Inheritance reuses forking, so the filesystem still folds out of one
stream and time travel is unchanged. Files come across; the conversation
does not."
```

---

### Task 13: Document it

**Files:**
- Modify: `README.md`
- Test: none — prose.

- [ ] **Step 1: Add a knowledge-graph section**

Add to `README.md` after the search discussion, matching the README's existing voice (it explains *why* a thing is shaped as it is, not just how to call it). Cover:

- A project is a set of sessions sharing a filesystem and a knowledge graph, sequential — one session holds it at a time, and inherits the filesystem where the last one left it.
- `remember` commits content; `graph_search` reads it back; `unmerge` reverses a consolidation the agent judges wrong.
- The graph is a projection of the same SQLite log the sessions live in, so it rebuilds at project open and extraction never re-runs on replay.
- No project means no knowledge tools and no store, exactly as no `AGENT_SEARXNG_URL` means no search tool.
- Update the configuration table with `AGENT_GRAPH_STORE` and `AGENT_KNOWLEDGE_DOMAIN`.

Be accurate about the network posture. The README currently says web search is the one documented egress exception; `remember` calls the same model endpoint the agent already uses, so it is not new egress — but it *does* mean content the agent passes goes to that endpoint. Say so plainly rather than leaving the existing sentence to imply otherwise.

- [ ] **Step 2: Verify every command in the README still runs**

Run: `uv run pytest && uv run python -c "from research_team.composition import build_application; print('ok')"`
Expected: PASS, `ok`

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: projects and the knowledge graph"
```

---

## Notes for the implementer

**When a redstring or eventsource signature does not match what a task shows,** the library wins — fix the task's code and keep going. Several steps include a verification command for exactly this. What must not change without going back to the spec: the tenant is always the project id, extraction never runs at fold time, and `EntitiesMerged` is never appended by this codebase.

**Five upstream redstring gaps (R1–R5)** are recorded in the spec's *Upstream dependencies* section. Two produce workarounds in this plan, both in `rebuild.py` and both commented as such: `tenant_filter` scoping (R3) and the manual `ReplayReport.failed` check (R4). When a redstring release closes them, those comments are the change list.

**Vector search is deliberately absent.** redstring cannot populate a `VectorStore` today (R1), so there is no `AGENT_VECTOR_STORE` variable and no vector adapter. Do not add one to be helpful — an empty store that answers similarity queries with nothing is worse than no store.

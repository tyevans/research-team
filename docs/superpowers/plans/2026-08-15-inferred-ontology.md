# Inferred Ontology Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover the classes a document states outright — "There are six difficulties available in the game: EASY, NORMAL, HARD, EXPERT, MASTER, and APPEND" — as inspectable, attributable, re-runnable structure on the knowledge graph, marked inferred and never confused with what a document asserted.

**Architecture:** A persisted pass, not read-path inference. A model call reads one document's full text and proposes classes; verification drops anything not in the text; an `OntologyDiscovered` event is appended; a projection writes two read-model tables; `ProjectGraphReader` joins them in on read as `inferred` class nodes and `instance_of` edges. Extraction is untouched — this pass runs separately and can be re-run without re-extracting.

**Tech Stack:** Python 3.13, pydantic, eventsource-py (`DomainEvent`, `DeclarativeProjection`, `SubscriptionManager`), aiosqlite + SQLAlchemy async, FastAPI, redstring (read only, via the existing adapter). Frontend: React + TypeScript, vitest, `react-force-graph-2d`.

**Spec:** `docs/superpowers/specs/2026-08-15-inferred-ontology-design.md` — read it first. This plan argues from it and does not repeat its reasoning.

## Global Constraints

- **Four verification gates, and passing three is not passing.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository, not the files you touched.
- **Never run two vitest processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- **Do not run `pytest` and `npm run verify` concurrently** for the same reason in reverse — a timing-sensitive test under load produces failures absent on a quiet machine. Two consecutive identical results is the bar for "this is real".
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, and say when something was measured rather than reasoned. Commit messages carry what was considered and rejected.
- **If a test would pass with the change reverted, say so in its docstring** rather than leaving it as reassurance.
- **No backwards compatibility is required.** Pre-release: break data, events and contracts rather than migrating.
- **`entity_type` for a class node is the literal string `"class"`.** `relationship_type` for a membership edge is the literal string `"instance_of"`. Both are fixed vocabulary; do not vary them between tasks.
- **Do not build a shared type with the temporal lane's `temporal_expression`.** The two share a principle — when a pipeline stage discards model output, record what was discarded and why, or the discard rate cannot be measured — and temporal loses output at the *parse* step where discovery loses it at the *verify* step. The payloads differ (a raw string against a name-and-reason pair) and the two are being built concurrently in separate lanes, so a shared abstraction agreed mid-flight would couple two subsystems on a noticed similarity rather than a shared requirement. See the spec's §6 for the full argument and the cheaper convergence available later.
- **Every inferred artefact carries `inferred=True`.** A derived thing that draws like an asserted thing is the defect this whole feature is arranged to avoid.

---

## File Structure

**Created:**

| File | Responsibility |
|---|---|
| `research_team/domain/ontology.py` | The `OntologyDiscovered` event and its three payload models. Its own module, not `events.py`, because `events.py` is documented as "domain events for a coding session" and this is not one — `corpus.py` sets the precedent for a second event module. |
| `research_team/application/ontology_discovery.py` | The use case: ports, prompt, parsing, verification, `OntologyDiscoveryService`. |
| `research_team/infrastructure/agent/ontology_model.py` | `OntologyTextPort` over a LangChain chat model. Four lines, beside `definition_model.py`. |
| `research_team/infrastructure/knowledge/ontology_recorder.py` | `OntologyRecordPort` over the event store — the only place this feature appends. |
| `tests/application/test_ontology_discovery.py` | Prompt, parsing, verification, service. |
| `tests/infrastructure/test_ontology_read_models.py` | Rows, store, projection, runner. |
| `tests/interfaces/test_ontology_routes.py` | The three routes. |
| `frontend/src/domain/knowledge/ontology.ts` | Ontology view types and the pure fold from the API shape. |
| `frontend/src/presentation/research/OntologyPane.tsx` | The class-layer rendering. |

**Modified:**

| File | Change |
|---|---|
| `research_team/infrastructure/persistence/read_models.py` | Two rows, one store, one projection, one runner. |
| `research_team/application/graph_read.py` | `GraphEntity.inferred`; `MAX_ONTOLOGY_CLASSES`. |
| `research_team/infrastructure/knowledge/graph_reader.py` | Join classes into `whole` and `neighborhood`. |
| `research_team/application/document_extraction.py` | `ungrouped(project_id)`. |
| `research_team/composition.py` | Runner construction, `Application` field, `start`/`caught_up`/`stop`, service factory. |
| `research_team/interfaces/web/app.py` | Three routes. |
| `tests/infrastructure/test_schema_evolution.py` | One case for the new event. |
| `frontend/src/domain/knowledge/graph.ts` | `GraphNode.inferred`. |

**A note on task boundaries.** Tasks 1–3 are backend storage, 4–6 are the pass itself, 7–8 are the read path, 9–10 are the frontend, 11 is the measurement that gates layer 3.

## STOP: the layer 3 checkpoint

**This plan ends at Task 11. Do not build layer 3 — schema refinement — as part of it.**

The user approved this gate explicitly. Layer 3 needs per-project schema selection, which does not exist today: `config.knowledge_domain()` reads one process-wide env var (`config.py:207`), nothing on the `Project` aggregate carries a schema id, and adding one is the largest single cost in the design. It is only worth paying if more than one project actually produces classes.

**Task 11 produces the number. Then stop, report it, and wait for a decision.** The order is: build the counting → look at the number → only then decide whether to build the machinery. An executor who finishes Task 10, sees "schema refinement" in the spec and starts writing YAML generators has skipped the gate — which is exactly the failure this checkpoint is placed to prevent, and it is placed here, in the file structure section, rather than in a footnote at the bottom for that reason.

The prediction on record, so it can be scored rather than quietly forgotten: SEKAI yields a handful of classes, Ancient Rome and budgeting yield near zero. The evidence is in the spec's opening section — five Ancient Rome documents contain **zero** enumerating sentences, measured 2026-08-15. If the prediction holds, the recommendation is to defer layer 3 indefinitely. If it does not hold, say so plainly.

---

### Task 1: The `OntologyDiscovered` event

**Files:**
- Create: `research_team/domain/ontology.py`
- Modify: `tests/infrastructure/test_schema_evolution.py`
- Test: `tests/domain/test_ontology_event.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `OntologyDiscovered`, `DiscoveredClass`, `DiscoveredMember`, `RejectedMember`, `EvidenceSpan`. Every later task uses these names and field spellings exactly.

**Why its own aggregate and not the `Corpus` decider.** `Corpus` is a `DeciderAggregate` (`domain/corpus.py:273`); routing through it means a command, a `decide` arm and an `evolve` arm, and it would fold derived data into the aggregate that owns the source text. This event enforces no invariant — the pass replaces a source's classes wholesale and is idempotent by construction — so there is nothing for a decider to decide. It is appended directly to the store, exactly as redstring appends `DocumentExtracted` without consulting any aggregate of this application's. The stream is one per project: `aggregate_id` is the project id.

- [ ] **Step 1: Write the failing test**

```python
# tests/domain/test_ontology_event.py
"""The ontology event's shape, which every later layer spells out by hand."""

from uuid import uuid4

from research_team.domain.ontology import (
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    OntologyDiscovered,
    RejectedMember,
)


def test_a_discovered_class_carries_members_evidence_and_the_count_it_claimed():
    project_id = uuid4()
    event = OntologyDiscovered(
        aggregate_id=project_id,
        project_id=project_id,
        source_id="sekaipedia-songs",
        model_version="test-model",
        classes=[
            DiscoveredClass(
                name="Difficulty",
                kind="ordered_scale",
                declared_count=6,
                parent_name=None,
                evidence=EvidenceSpan(source_id="sekaipedia-songs", start=100, end=180),
                members=[
                    DiscoveredMember(name="EASY", ordinal=0),
                    DiscoveredMember(name="NORMAL", ordinal=1),
                ],
                rejected_members=[
                    RejectedMember(name="LEGEND", reason="not found in the document")
                ],
            )
        ],
    )

    assert event.aggregate_type == "Ontology"
    assert event.classes[0].members[1].name == "NORMAL"
    assert event.classes[0].declared_count == 6
    assert event.classes[0].rejected_members[0].reason == "not found in the document"


def test_a_class_may_state_no_count_and_no_parent():
    """The ordinary case. A table names its class without counting its rows,
    and most classes nest under nothing -- so both fields default rather than
    forcing every construction site to say `None` explicitly."""
    klass = DiscoveredClass(
        name="Rank",
        kind="ordered_scale",
        evidence=EvidenceSpan(source_id="s", start=0, end=10),
        members=[DiscoveredMember(name="S rank", ordinal=0)],
    )

    assert klass.declared_count is None
    assert klass.parent_name is None
    assert klass.rejected_members == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_ontology_event.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'research_team.domain.ontology'`

- [ ] **Step 3: Write the implementation**

```python
# research_team/domain/ontology.py
"""The event a discovery pass appends, and the shapes inside it.

Its own module rather than `events.py`, whose docstring scopes that file to
"domain events for a coding session" -- this is a fact about a project's
corpus, not about a conversation. `corpus.py` already establishes that a
second event module is the shape here.

**Names, not entity ids.** A member is carried as the surface string the
document used, and resolution to an entity happens in the projection and
again on read. Storing ids would make the log record a fact about a graph
state that re-extraction can invalidate, which is the durable-log-of-derived-
facts mistake redstring's ADR 0005 is about -- and re-extraction remints ids
routinely.

Changing a shape here obeys `events.py`'s strategy: a new field gets a
default meaning what its absence meant, a restructure gets a
`model_validator(mode="before")` and an `event_version` bump, and either way
`tests/infrastructure/test_schema_evolution.py` grows a case. The field most
likely to need it is `kind`, whose vocabulary is expected to grow.
"""

from typing import Literal
from uuid import UUID

from eventsource import DomainEvent, register_event
from pydantic import BaseModel, Field


class EvidenceSpan(BaseModel):
    """Where in a document the class was stated, as half-open offsets.

    Deliberately the same `source_id` + two integers shape
    `application/corpus_spans.Span` and `entity_definitions.Citation` already
    use, and deliberately not a chunk id: chunks are an index detail that gets
    rebuilt, and a citation that survives re-chunking is one a reader can
    still follow a month later.
    """

    source_id: str
    start: int
    end: int


class DiscoveredMember(BaseModel):
    """One member of a class, as the document spelled it.

    `ordinal` is `None` for an unordered set and is the position counting from
    0 for an ordered one. It is not derived from list order: a reader sorting
    an `unordered_set` by arrival would be reading a sequence into a bag, so
    the absence of an ordinal has to be expressible.
    """

    name: str
    ordinal: int | None = None


class RejectedMember(BaseModel):
    """A member the model proposed and verification refused, and why.

    Recorded rather than dropped because a class that found five of a declared
    six with no explanation is unjudgeable -- the reader cannot tell an
    invented member from a document that is genuinely short one, and those are
    opposite conclusions about whether to trust the pass at all.
    """

    name: str
    reason: str


class DiscoveredClass(BaseModel):
    """One class, its members, and the sentence that stated it."""

    name: str
    kind: Literal["ordered_scale", "unordered_set", "taxonomy"]
    evidence: EvidenceSpan
    members: list[DiscoveredMember]
    declared_count: int | None = None
    """The count the text stated, when it stated one -- "There are **six**
    difficulties". A checksum, not a length: it is compared against the
    members actually found, and a disagreement is shown rather than resolved.
    Most classes state no count, so `None` is ordinary rather than an error."""
    parent_name: str | None = None
    rejected_members: list[RejectedMember] = Field(default_factory=list)


@register_event
class OntologyDiscovered(DomainEvent):
    """The classes one discovery pass found in one document.

    Appended directly rather than through a `DeciderAggregate`, unlike
    `Corpus`: this enforces no invariant, because a pass replaces a source's
    classes wholesale and re-running it is idempotent by construction. There
    is nothing for a decider to decide, and routing through `Corpus` would
    fold derived data into the aggregate that owns the verbatim source text.

    One stream per project (`aggregate_id` is the project id). `project_id` is
    also a field, because a projection reads the payload and should not have
    to know that the two happen to be equal -- `SessionStarted.project_id`
    carries a project the same way for the same reason.

    An empty `classes` is a real and expected outcome: it records that this
    document was examined and states no classes. That is the difference
    between "grouped, nothing found" and "never grouped", and `ungrouped`
    depends on being able to tell them apart.
    """

    aggregate_type: str = "Ontology"
    project_id: UUID
    source_id: str
    model_version: str
    classes: list[DiscoveredClass] = Field(default_factory=list)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/domain/test_ontology_event.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Add the schema-evolution case**

Open `tests/infrastructure/test_schema_evolution.py`, read how an existing case writes a payload straight into the events table, and add one in that same shape:

```python
async def test_an_ontology_event_written_before_rejected_members_existed_still_loads(...):
    """Writes a payload with no `rejected_members` key -- the shape the first
    build wrote -- and reads it back. Adding a field with a default is case 1
    of `events.py`'s strategy; this pins that the default actually means what
    its absence meant, which is "nothing was rejected", not "unknown".

    Would pass with `rejected_members` reverted to a required field only if
    the fixture also stopped omitting it -- omission is the whole test.
    """
```

Match the file's existing fixtures and helpers exactly; do not invent a new harness.

- [ ] **Step 6: Run the schema-evolution suite**

Run: `uv run pytest tests/infrastructure/test_schema_evolution.py -v`
Expected: PASS, including the new case.

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format research_team/domain/ontology.py tests/domain/test_ontology_event.py tests/infrastructure/test_schema_evolution.py
uv run ruff check .
uv run ruff format --check .
git add research_team/domain/ontology.py tests/domain/test_ontology_event.py tests/infrastructure/test_schema_evolution.py
git commit -m "Record a discovered ontology as its own event, not a corpus command

Appended directly rather than through the Corpus decider. The pass replaces a
source's classes wholesale and is idempotent by construction, so there is no
invariant for a decider to enforce -- and routing through Corpus would fold
derived data into the aggregate that owns the verbatim source text.

Members are names, not entity ids. Storing ids would make the log record a
fact about a graph state that re-extraction invalidates routinely, which is
what redstring ADR 0005 warns against.

An empty classes list is a real outcome, not a no-op: it distinguishes
'examined, nothing found' from 'never examined', which is the whole basis of
the ungrouped listing built later."
```

---

### Task 2: The read-model rows and store

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py`
- Test: `tests/infrastructure/test_ontology_read_models.py`

**Interfaces:**
- Consumes: `DiscoveredClass`, `DiscoveredMember`, `RejectedMember`, `EvidenceSpan` (Task 1).
- Produces:
  - `ONTOLOGY_NAMESPACE: UUID`
  - `OntologyClassRow(ReadModel)` with `.row_id(project_id, source_id, name) -> UUID`
  - `OntologyMembershipRow(ReadModel)` with `.row_id(class_id, member_name) -> UUID`
  - `OntologyStore` with `open(db_path, tracer=None)`, `replace_for_source(project_id, source_id, classes, model, generated_at)`, `classes_for(project_id) -> list[OntologyClassRow]`, `members_for(class_id) -> list[OntologyMembershipRow]`, `sources_with_classes(project_id) -> set[str]`, `mark_stale_for_source(project_id, source_id)`, `close()`

- [ ] **Step 1: Write the failing test**

```python
# tests/infrastructure/test_ontology_read_models.py
"""The ontology tables: what they store and what they refuse to lose."""

import json

import pytest

from research_team.domain.ontology import (
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    RejectedMember,
)
from research_team.infrastructure.persistence.read_models import (
    OntologyClassRow,
    OntologyStore,
)


def _difficulty() -> DiscoveredClass:
    return DiscoveredClass(
        name="Difficulty",
        kind="ordered_scale",
        declared_count=6,
        evidence=EvidenceSpan(source_id="songs", start=10, end=90),
        members=[
            DiscoveredMember(name="EASY", ordinal=0),
            DiscoveredMember(name="NORMAL", ordinal=1),
        ],
        rejected_members=[RejectedMember(name="LEGEND", reason="not in the document")],
    )


@pytest.fixture
async def store(tmp_path):
    opened = await OntologyStore.open(str(tmp_path / "ontology.db"))
    yield opened
    await opened.close()


async def test_a_stored_class_keeps_its_checksum_its_evidence_and_its_rejections(
    store, project_id
):
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="2026-08-15T00:00:00Z"
    )

    (row,) = await store.classes_for(project_id)

    assert row.name == "Difficulty"
    assert row.kind == "ordered_scale"
    # The checksum and what was actually found, both stored. Storing only the
    # difference would make "5 of 6" indistinguishable from "5 of 5".
    assert (row.declared_count, row.member_count) == (6, 2)
    assert (row.evidence_start, row.evidence_end) == (10, 90)
    assert json.loads(row.rejected_members) == [
        {"name": "LEGEND", "reason": "not in the document"}
    ]


async def test_members_keep_the_order_the_text_gave_them(store, project_id):
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    (row,) = await store.classes_for(project_id)

    members = await store.members_for(row.id)

    assert [(m.member_name, m.ordinal) for m in members] == [("EASY", 0), ("NORMAL", 1)]


async def test_re_running_replaces_a_source_rather_than_appending_to_it(store, project_id):
    """The pass is re-run whenever its prompt changes. Without replacement,
    every re-run would double the classes and the graph would grow a duplicate
    hub per attempt. Would pass with `replace_for_source` implemented as an
    append only if this asserted a count of one, which is why it does."""
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m2", generated_at="t2"
    )

    rows = await store.classes_for(project_id)

    assert len(rows) == 1
    assert rows[0].model == "m2"


async def test_replacing_one_source_leaves_another_sources_classes_alone(store, project_id):
    """A pass over one document must not clear a class discovered in another.
    Nothing else in the suite would catch a `DELETE` missing its `source_id`
    predicate, because every other test uses one source."""
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )
    other = _difficulty().model_copy(update={"name": "Rank"})
    await store.replace_for_source(project_id, "ranks", [other], model="m", generated_at="t")

    names = {row.name for row in await store.classes_for(project_id)}

    assert names == {"Difficulty", "Rank"}


async def test_one_projects_classes_are_invisible_to_another(store, project_id, other_project_id):
    await store.replace_for_source(
        project_id, "songs", [_difficulty()], model="m", generated_at="t"
    )

    assert await store.classes_for(other_project_id) == []


async def test_a_source_that_stated_no_classes_is_still_recorded_as_examined(
    store, project_id
):
    """`replace_for_source` with an empty list is how "grouped, found nothing"
    is distinguished from "never grouped". Task 6's `ungrouped` listing is
    built entirely on that distinction, so losing it here would make the sweep
    re-run every barren document forever, at model cost."""
    await store.replace_for_source(project_id, "songs", [], model="m", generated_at="t")

    assert await store.classes_for(project_id) == []
    assert await store.sources_with_classes(project_id) == {"songs"}
```

Add `project_id` / `other_project_id` fixtures to this file if the suite's `conftest.py` does not already supply them:

```python
@pytest.fixture
def project_id():
    return uuid4()


@pytest.fixture
def other_project_id():
    return uuid4()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_ontology_read_models.py -v`
Expected: FAIL with `ImportError: cannot import name 'OntologyClassRow'`

- [ ] **Step 3: Write the rows**

Add to `read_models.py`, after `EntityDefinitionRunner`:

```python
ONTOLOGY_NAMESPACE = UUID("3f7b21c9-6d84-5e02-a1b7-9c4e0f83d216")
"""Distinct from `DEFINITION_NAMESPACE` and `CORPUS_NAMESPACE` for the reason
stated on those: three tables keyed on unrelated things that are all just
strings by the time `uuid5` sees them must not be able to collide on `id`."""


class OntologyClassRow(ReadModel):
    """One class discovered in one document, with what it was derived from.

    Entirely derived: every column here is recomputed by replaying the log,
    unlike `EntityDefinitionRow`, whose text comes from a service's `put`.
    That is why this table's `rebuild` may truncate where the definition
    runner's may not.

    Keyed on `(project_id, source_id, name)`. Two documents each stating
    "six difficulties" therefore produce two rows, deliberately -- merging
    them is the entity-identity problem redstring's `Consolidator` exists for
    and should reuse it, not grow a private version here. See the spec's
    "Deliberately not built".
    """

    __table_name__ = "ontology_classes"

    project_id: UUID
    source_id: str
    name: str
    kind: str
    declared_count: int | None = None
    member_count: int = 0
    """What was actually stored, kept alongside `declared_count` rather than
    computed from the membership table on read. A count derived by a join
    would silently agree with itself after a partial write; two independently
    recorded numbers can disagree, which is the entire point of a checksum."""
    parent_class_id: UUID | None = None
    evidence_start: int = 0
    evidence_end: int = 0
    evidence_text: str = ""
    rejected_members: str = "[]"
    """JSON array of `{name, reason}`. A string column for the same reason
    `EntityDefinitionRow.citations` is one: it is handed whole to a browser
    that renders it, and decoding here would be work with no reader."""
    model: str = ""
    generated_at: str = ""
    stale: bool = False

    @staticmethod
    def row_id(project_id: UUID, source_id: str, name: str) -> UUID:
        return uuid5(ONTOLOGY_NAMESPACE, f"{project_id}:{source_id}:{name}")


class OntologyMembershipRow(ReadModel):
    """One member of one class.

    `entity_id` is nullable on purpose and it is the staleness contract. A
    member the pass named but that resolves to no entity today keeps its row
    with a null id: it is dropped from the drawing, because there is nothing
    to draw it against, and retained in the class, so `member_count` still
    checks out against `declared_count` and a re-run is not needed merely
    because a name drifted. Deleting the row instead would make an unrelated
    re-extraction look like a discovery failure.
    """

    __table_name__ = "ontology_memberships"

    project_id: UUID
    class_id: UUID
    member_name: str
    entity_id: UUID | None = None
    ordinal: int | None = None

    @staticmethod
    def row_id(class_id: UUID, member_name: str) -> UUID:
        return uuid5(ONTOLOGY_NAMESPACE, f"{class_id}:{member_name}")
```

- [ ] **Step 4: Write the store**

```python
class OntologyStore:
    """The two ontology tables and the connection they share.

    One store for two tables, unlike every other store here, because they are
    written and cleared together: replacing a source's classes must delete
    that source's memberships in the same breath, and two stores over two
    connections would make that two transactions with a window between them
    where a class has no members and the graph draws a bare hub.
    """

    def __init__(
        self,
        connection: aiosqlite.Connection,
        classes: ReadModelRepository,
        members: ReadModelRepository,
    ) -> None:
        self._connection = connection
        self._classes = classes
        self._members = members

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "OntologyStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, OntologyClassRow)
        await apply_schema(connection, OntologyMembershipRow)
        # `apply_schema` reconciles columns, not indexes -- the same note as on
        # `EntityDefinitionStore.open`. Every read here is project-scoped, and
        # `members_for` is class-scoped and runs once per class on every graph
        # read, so an unindexed membership table would put a project's whole
        # canvas behind a scan per class.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_ontology_classes_project "
            f"ON {OntologyClassRow.table_name()}(project_id, source_id)"
        )
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_ontology_members_class "
            f"ON {OntologyMembershipRow.table_name()}(class_id)"
        )
        await connection.commit()
        return cls(
            connection,
            SQLiteReadModelRepository(connection, OntologyClassRow, tracer),
            SQLiteReadModelRepository(connection, OntologyMembershipRow, tracer),
        )

    async def replace_for_source(
        self,
        project_id: UUID,
        source_id: str,
        classes: list[DiscoveredClass],
        *,
        model: str,
        generated_at: str,
    ) -> None:
        """Store this source's classes, discarding whatever it had before.

        Replacement rather than upsert: the pass is re-run whenever its prompt
        changes, and a re-run that no longer finds a class must remove it. An
        upsert would leave every class any past prompt ever produced, and the
        graph would accumulate a hub per attempt.

        An empty `classes` still clears and still records the source as
        examined -- see `sources_with_classes`.
        """
        await self._delete_source(project_id, source_id)
        for klass in classes:
            class_id = OntologyClassRow.row_id(project_id, source_id, klass.name)
            await self._classes.save(
                OntologyClassRow(
                    id=class_id,
                    project_id=project_id,
                    source_id=source_id,
                    name=klass.name,
                    kind=klass.kind,
                    declared_count=klass.declared_count,
                    member_count=len(klass.members),
                    parent_class_id=(
                        OntologyClassRow.row_id(project_id, source_id, klass.parent_name)
                        if klass.parent_name
                        else None
                    ),
                    evidence_start=klass.evidence.start,
                    evidence_end=klass.evidence.end,
                    evidence_text="",
                    rejected_members=json.dumps(
                        [r.model_dump() for r in klass.rejected_members]
                    ),
                    model=model,
                    generated_at=generated_at,
                )
            )
            for member in klass.members:
                await self._members.save(
                    OntologyMembershipRow(
                        id=OntologyMembershipRow.row_id(class_id, member.name),
                        project_id=project_id,
                        class_id=class_id,
                        member_name=member.name,
                        entity_id=None,
                        ordinal=member.ordinal,
                    )
                )
        await self._record_examined(project_id, source_id)
```

Implement `_delete_source`, `_record_examined`, `sources_with_classes`, `classes_for`, `members_for`, `mark_stale_for_source` and `close` against the connection directly with parameterised SQL, following `CorpusStore`'s existing style in the same file. `_record_examined` writes to a third, single-column-per-source table `ontology_examined(project_id, source_id)` — a source with no classes has no `OntologyClassRow` to carry the fact that it was looked at, and Task 6's `ungrouped` is built on that distinction.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_ontology_read_models.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Format, lint, commit**

```bash
uv run ruff format research_team/infrastructure/persistence/read_models.py tests/infrastructure/test_ontology_read_models.py
uv run ruff check .
uv run ruff format --check .
git add research_team/infrastructure/persistence/read_models.py tests/infrastructure/test_ontology_read_models.py
git commit -m "Store discovered classes with their checksum and their rejections

member_count is recorded rather than joined. A count derived from the
membership table would silently agree with itself after a partial write; two
independently recorded numbers can disagree, which is the whole point of
keeping the declared count at all.

rejected_members is stored because a class that found five of a declared six
with no explanation is unjudgeable -- the reader cannot distinguish an
invented member from a document genuinely short one, and those are opposite
conclusions about whether to trust the pass.

Replacement, not upsert: the prompt will change repeatedly and a re-run that
stops finding a class has to remove it, or the graph accumulates one hub per
attempt. A third table records that a source was examined, because a document
that states no classes has no row to carry that fact and the ungrouped sweep
would otherwise re-run it forever at model cost.

One store over two tables, against the pattern elsewhere here: they are
cleared together, and two connections would leave a window where a class has
members deleted and the canvas draws a bare hub."
```

---

### Task 3: The projection and the runner

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py`
- Test: `tests/infrastructure/test_ontology_read_models.py`

**Interfaces:**
- Consumes: `OntologyStore` (Task 2), `OntologyDiscovered` (Task 1), `DocumentExtracted` (redstring).
- Produces: `OntologyProjection`, `OntologyRunner` with `start()`, `failures(limit=100)`, `classes_for(project_id)`, `members_for(class_id)`, `sources_with_classes(project_id)`, `rebuild()`, `caught_up(timeout=10.0)`, `stop()`.

- [ ] **Step 1: Write the failing test**

```python
async def test_the_projection_stores_the_classes_an_event_carried(runner, project_id):
    """Asserts the row, not that replay completed. An event no projection
    handles counts as APPLIED, not rejected -- `strict=True` raises only when
    a handler itself raises and has no opinion about an unsubscribed event.
    So a build with `OntologyProjection` never registered replays cleanly and
    serves an empty table, and any assertion weaker than "this row exists with
    this value" passes against it."""
    await append_ontology_discovered(project_id, "songs", [_difficulty()])
    await runner.caught_up()

    (row,) = await runner.classes_for(project_id)

    assert (row.name, row.kind, row.declared_count) == ("Difficulty", "ordered_scale", 6)


async def test_re_extracting_a_grouped_source_stales_its_classes_and_calls_no_model(
    runner, project_id
):
    """Mark, never regenerate. A bulk re-extraction touching every document
    would otherwise fire one paid model call per document for classes nobody
    asked to see. The projection has no model to call by construction -- it is
    not given one -- and this pins that it stays that way."""
    await append_ontology_discovered(project_id, "songs", [_difficulty()])
    await runner.caught_up()

    await append_document_extracted(project_id, "songs")
    await runner.caught_up()

    (row,) = await runner.classes_for(project_id)
    assert row.stale is True
    assert row.name == "Difficulty"  # staled, not deleted


async def test_rebuild_restores_a_table_someone_emptied(runner, project_id):
    """Every column here is derived from the log, unlike the definition cache,
    so this rebuild truncates and replays rather than only resetting the
    checkpoint. Proves it red by emptying the table first."""
    await append_ontology_discovered(project_id, "songs", [_difficulty()])
    await runner.caught_up()
    await empty_ontology_tables()
    assert await runner.classes_for(project_id) == []

    await runner.rebuild()

    assert len(await runner.classes_for(project_id)) == 1
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/infrastructure/test_ontology_read_models.py -k projection or rebuild -v`
Expected: FAIL with `NameError: name 'OntologyProjection' is not defined`

- [ ] **Step 3: Write the projection**

```python
class OntologyProjection(DeclarativeProjection):
    """Writes discovered classes, and stales them when extraction moves under them.

    **Marks, never regenerates**, exactly as `EntityDefinitionProjection`
    does and for the same measured reason: a bulk re-extraction touching two
    hundred documents would otherwise fire two hundred paid model calls for
    classes nobody asked to look at. `stale=True` is a label the next
    discovery run resolves, not a queue this projection drains. It is given no
    model, so it cannot call one even by mistake.
    """

    def __init__(self, ontology: OntologyStore, checkpoint_repo=None, dlq_repo=None, tracer=None):
        self._ontology = ontology
        super().__init__(
            checkpoint_repo=checkpoint_repo,
            dlq_repo=dlq_repo,
            retry_policy=LOCAL_RETRY_POLICY,
            tracer=tracer,
        )

    @handles(OntologyDiscovered)
    async def _on_discovered(self, event: OntologyDiscovered) -> None:
        await self._ontology.replace_for_source(
            event.project_id,
            event.source_id,
            event.classes,
            model=event.model_version,
            generated_at=event.occurred_at.isoformat(),
        )

    @handles(DocumentExtracted)
    async def _on_extracted(self, event: DocumentExtracted) -> None:
        """Stale this source's classes: the entities its memberships name have
        just been reminted, so every resolved id is suspect.

        Keys on `event.tenant_id`, matching `EntityDefinitionProjection`:
        redstring's event arrives here without new wiring and `tenant_id` is
        the project.
        """
        await self._ontology.mark_stale_for_source(event.tenant_id, str(event.source_id))
```

- [ ] **Step 4: Write the runner**

Copy `EntityDefinitionRunner` structurally — same `start`, `failures`, `caught_up`, `stop` — with two differences, each of which needs its comment:

```python
    async def rebuild(self) -> None:
        """Truncate and replay.

        The opposite of `EntityDefinitionRunner.rebuild`, which must not
        truncate, and the difference is which columns come from the log.
        A definition's `text` comes from a service's `put` and replaying
        would not restore it. Every column in `ontology_classes` and
        `ontology_memberships` is written by `_on_discovered` from an event
        payload, so a replay reproduces the table exactly -- and truncating
        first is what removes rows for classes a superseded event no longer
        carries, which a replay alone would leave behind.
        """
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_ontology_read_models.py -v`
Expected: PASS

- [ ] **Step 6: Prove the tests red**

Comment out the `@handles(OntologyDiscovered)` decorator and re-run. Expected: the storing test FAILS. This is the check that matters most in this task — an unsubscribed event applies silently, so a green suite proves nothing until you have seen it go red. Restore the decorator.

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format research_team/infrastructure/persistence/read_models.py tests/infrastructure/test_ontology_read_models.py
uv run ruff check .
uv run ruff format --check .
git add research_team/infrastructure/persistence/read_models.py tests/infrastructure/test_ontology_read_models.py
git commit -m "Project discovered classes, and stale them when extraction moves

Marks, never regenerates -- the projection is handed no model, so a bulk
re-extraction cannot fire a paid call per document. Classes are staled rather
than deleted: the text still describes something a reader may want to see,
labelled, until a discovery run replaces it.

rebuild truncates here, unlike the definition runner's, and the difference is
which columns come from the log. Every column in these two tables is written
from an event payload, so a replay reproduces them exactly -- and the truncate
is what removes rows a superseded event no longer carries.

The storing test was proved red by removing the @handles decorator. That
mattered more than usual: an event no projection handles counts as APPLIED,
so an unregistered projection serves an empty table through a clean replay,
and any assertion weaker than 'this row holds this value' passes against it."
```

---

### Task 4: Prompt, parsing and verification

**Files:**
- Create: `research_team/application/ontology_discovery.py`
- Test: `tests/application/test_ontology_discovery.py`

**Interfaces:**
- Consumes: `DiscoveredClass`, `DiscoveredMember`, `RejectedMember`, `EvidenceSpan` (Task 1).
- Produces:
  - `MAX_DISCOVERY_CHARS: int = 40_000`
  - `PROMPT_HEADER: str`
  - `build_prompt(document_text: str) -> str`
  - `parse_ontology(raw: str) -> list[dict]` — proposals, untrusted
  - `verify_classes(proposals: list[dict], *, document_text: str, source_id: str) -> list[DiscoveredClass]`

These three are module-level functions, not methods, so tests read them without standing up a service — the shape `entity_definitions.build_prompt` established.

- [ ] **Step 1: Write the failing test**

```python
# tests/application/test_ontology_discovery.py
"""Discovery's pure half: what the model is asked, and what is believed back."""

from research_team.application.ontology_discovery import (
    build_prompt,
    parse_ontology,
    verify_classes,
)

SONGS = (
    "There are six difficulties available in the game: EASY, NORMAL, HARD, "
    "EXPERT, MASTER, and APPEND. Achieving combo milestones grants coins."
)


def test_the_prompt_carries_the_document_and_forbids_outside_knowledge():
    prompt = build_prompt(SONGS)

    assert SONGS in prompt
    assert "only" in prompt.lower()


def test_the_prompt_rules_out_open_lists_and_bare_contrasts():
    """Measured 2026-08-15 in `wiki-roman-economy`: "attested for a wide range
    of occupations, including fishermen..." names nine members against a
    declared 268. A class built from it asserts Rome had nine occupations.

    A prompt-content assertion is weak -- a schema shapes prompts and does not
    enforce output -- so this is not the defence, it is the first half of it.
    The second half is the checksum: `9 of 268` reads as a sample on sight,
    and that is what `test_a_class_that_samples_a_larger_set_is_kept_and_shown`
    in Task 10 pins.
    """
    prompt = build_prompt(SONGS)

    assert "including" in prompt
    assert "Official cults" in prompt  # the contrast counter-example


def test_a_fenced_reply_is_read_anyway():
    """'Answer with JSON and nothing else' is followed most of the time and
    not all of it -- the same tolerance `entity_definitions._parse` needs."""
    raw = '```json\n{"classes": [{"name": "Difficulty", "kind": "unordered_set", '
    raw += '"members": [{"name": "EASY"}]}]}\n```'

    assert parse_ontology(raw)[0]["name"] == "Difficulty"


def test_an_unreadable_reply_yields_nothing_rather_than_raising():
    """A reply this cannot read is a reply whose members cannot be checked,
    and the caller treats that exactly like a reply that proposed nothing."""
    assert parse_ontology("I'm afraid I can't do that.") == []


def test_a_member_that_is_not_in_the_document_is_rejected_with_its_reason():
    """The pass's main defence against a model pattern-matching a plausible
    taxonomy onto a document that does not state one. An invented class looks
    exactly like a discovered one, so the check has to be against the text.

    Both halves are asserted: the member is gone from `members`, AND it is
    named in `rejected_members`. An implementation that drops it silently
    passes the first half alone and makes the class unjudgeable."""
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "declared_count": 6,
            "evidence": {"start": 0, "end": 100},
            "members": [{"name": "EASY", "ordinal": 0}, {"name": "LEGEND", "ordinal": 6}],
        }
    ]

    (klass,) = verify_classes(proposals, document_text=SONGS, source_id="songs")

    assert [m.name for m in klass.members] == ["EASY"]
    assert klass.rejected_members[0].name == "LEGEND"
    assert "not found" in klass.rejected_members[0].reason


def test_a_class_whose_evidence_span_is_outside_the_document_is_dropped_whole():
    """An evidence span that does not exist is a span the model produced
    rather than read, and a class nobody can open the source for is exactly
    the unjudgeable artefact this feature exists to avoid. Dropping the class
    is right where dropping a member is not: without evidence there is nothing
    left to judge."""
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": {"start": 9000, "end": 9100},
            "members": [{"name": "EASY"}],
        }
    ]

    assert verify_classes(proposals, document_text=SONGS, source_id="songs") == []


def test_a_class_with_no_surviving_members_is_dropped():
    """A class name with nothing in it is not a discovery."""
    proposals = [
        {
            "name": "Difficulty",
            "kind": "ordered_scale",
            "evidence": {"start": 0, "end": 50},
            "members": [{"name": "LEGEND"}],
        }
    ]

    assert verify_classes(proposals, document_text=SONGS, source_id="songs") == []


def test_an_unknown_kind_is_refused_rather_than_coerced():
    """`kind` selects the whole rendering. A misread value silently drawn as
    an ordered scale would assert an ordering the text never stated."""
    proposals = [
        {
            "name": "Difficulty",
            "kind": "spectrum",
            "evidence": {"start": 0, "end": 50},
            "members": [{"name": "EASY"}],
        }
    ]

    assert verify_classes(proposals, document_text=SONGS, source_id="songs") == []
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/application/test_ontology_discovery.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the module**

```python
# research_team/application/ontology_discovery.py
"""Discovering the classes a document states, and refusing the ones it does not.

Extraction turns "There are six difficulties available in the game: EASY,
NORMAL, HARD, EXPERT, MASTER, and APPEND" into six unrelated `category`
entities. The class name, the membership, the ordering and the count are all
in that sentence and none of the four survives. This recovers them.

**Reads the whole document, never chunks.** The rank table's class name lives
entirely in its header row, `| Rank | Reward |`, one line long. A chunk
boundary between that header and `| S rank |` leaves the members in a chunk
with no name for what they belong to -- the pass would be blind to precisely
the case it exists for. `corpus_spans` prefers paragraph then sentence
boundaries and has no notion of a table, so nothing prevents it. The cost is
`MAX_DISCOVERY_CHARS`: a longer document is refused rather than windowed. A
windowed pass reintroduces the split-table problem with extra bookkeeping, and
no measurement yet says how many real documents exceed the ceiling.

**Verification is against the document, not against plausibility.** A model
that pattern-matches a taxonomy onto a document that does not state one
produces something indistinguishable, by eye, from a real discovery. So every
member name must occur verbatim in the text and every evidence span must lie
inside it. What is dropped is recorded rather than discarded: a class that
found five of a declared six with no explanation cannot be judged, because the
reader cannot tell an invented member from a document genuinely short one.
"""

import json
from typing import Any

from research_team.domain.ontology import (
    DiscoveredClass,
    DiscoveredMember,
    EvidenceSpan,
    RejectedMember,
)

#: The longest document this pass will read. Above it the document is refused
#: and listed as ungrouped rather than truncated: a truncated read would drop
#: the trailing half of a document silently and report success, which is the
#: failure mode this whole feature is arranged against. Sized so the SEKAI
#: document (4,890 chars, measured 2026-08-15) is comfortable and a long wiki
#: article still fits; not tuned against a corpus-wide measurement, because
#: none has been taken -- take one before raising it.
MAX_DISCOVERY_CHARS = 40_000

_KINDS = frozenset({"ordered_scale", "unordered_set", "taxonomy"})

PROMPT_HEADER = """\
Find the classes this document states outright, and nothing else.

A class is a named group whose members the document actually lists -- a
sentence that enumerates them, a table whose header names them, or a section
that introduces them as a set. Report only classes the document names. Do not
group things yourself, do not use anything you know about this subject from
outside the document, and do not report a class the document merely implies.

Report a class only where the document gives the members it has, not where it
offers examples of a larger set. "There are six difficulties: EASY, NORMAL,
HARD, EXPERT, MASTER, and APPEND" states its members. "attested for a wide
range of occupations, including fishermen, salt merchants, olive oil dealers"
gives three examples of many and is not a class. "including", "such as", "for
example" and "among others" all mark a list you should not report.

Two things contrasted are not a class either. "Official cults were state
funded. Non-official cults were funded by private individuals" names no group
and lists no members; it is a sentence about two things, not a set.

For each class give:
  - name: what the document calls the group, in its own words.
  - kind: "ordered_scale" if the document states an order or a progression,
    "taxonomy" if the class has named subclasses, "unordered_set" otherwise.
    Do not report an order the document does not state.
  - declared_count: the number the document states, if it states one
    ("There are six difficulties" -> 6). Omit it if the document gives no
    number. Do not count the members yourself.
  - evidence: the character offsets of the sentence or table header that
    states this class, as {"start": <int>, "end": <int>}.
  - members: each member as {"name": "<exactly as the document spells it>",
    "ordinal": <int from 0, only for ordered_scale>}.
  - parent_name: the name of the class this one nests under, if any.

Every member name must appear in the document exactly as you write it. A name
that does not will be discarded and reported as a rejection, so copy rather
than paraphrase.

Answer with JSON and nothing else:

  {"classes": [{"name": ..., "kind": ..., "declared_count": ...,
                "evidence": {"start": ..., "end": ...},
                "members": [{"name": ..., "ordinal": ...}],
                "parent_name": ...}]}

If the document states no classes, answer {"classes": []}. That is a normal
answer and is preferred over inventing one.

Document:
"""


def build_prompt(document_text: str) -> str:
    """The whole document, under the rules that constrain what may be said about it.

    The rules are in the same string as the material for the reason
    `ChatModelDefinitionText` gives for using one `HumanMessage`: splitting
    them across two messages would put half the contract somewhere the
    application-layer test of the prompt could not see it.
    """
    return f"{PROMPT_HEADER}\n{document_text}\n"


def parse_ontology(raw: str) -> list[dict[str, Any]]:
    """The model's proposals, or empty if the reply is not the asked-for shape.

    Returns raw dicts rather than `DiscoveredClass`: nothing here is believed
    yet, and constructing the domain type before verification would make an
    invented class and a discovered one the same type at the point where they
    still have to be told apart.
    """
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        text = text.rsplit("```", 1)[0]
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return []
    if not isinstance(payload, dict):
        return []
    return [item for item in (payload.get("classes") or []) if isinstance(item, dict)]


def verify_classes(
    proposals: list[dict[str, Any]], *, document_text: str, source_id: str
) -> list[DiscoveredClass]:
    """Only what the document actually supports.

    Three refusals, and they are not the same severity. A member not in the
    text is dropped and *recorded* -- the class survives, minus one, and the
    reader is told why. A class whose evidence span is outside the document is
    dropped whole, because there is nothing left for a reader to open and
    judge; recording it would be recording an artefact nobody can check. A
    class with an unrecognised `kind` is dropped whole because `kind` selects
    the entire rendering, and coercing it to `unordered_set` would quietly
    turn a misread into a claim about the text.
    """
    verified: list[DiscoveredClass] = []
    for proposal in proposals:
        name = proposal.get("name")
        kind = proposal.get("kind")
        if not isinstance(name, str) or not name.strip() or kind not in _KINDS:
            continue

        evidence = proposal.get("evidence")
        if not isinstance(evidence, dict):
            continue
        start, end = evidence.get("start"), evidence.get("end")
        if not (isinstance(start, int) and isinstance(end, int)):
            continue
        if not (0 <= start < end <= len(document_text)):
            continue

        members: list[DiscoveredMember] = []
        rejected: list[RejectedMember] = []
        for item in proposal.get("members") or []:
            if not isinstance(item, dict):
                continue
            member_name = item.get("name")
            if not isinstance(member_name, str) or not member_name.strip():
                continue
            if member_name not in document_text:
                rejected.append(
                    RejectedMember(
                        name=member_name,
                        reason="not found in the document, verbatim",
                    )
                )
                continue
            ordinal = item.get("ordinal")
            members.append(
                DiscoveredMember(
                    name=member_name,
                    ordinal=ordinal if isinstance(ordinal, int) else None,
                )
            )

        if not members:
            continue

        declared = proposal.get("declared_count")
        parent = proposal.get("parent_name")
        verified.append(
            DiscoveredClass(
                name=name.strip(),
                kind=kind,
                evidence=EvidenceSpan(source_id=source_id, start=start, end=end),
                members=members,
                declared_count=declared if isinstance(declared, int) else None,
                parent_name=parent if isinstance(parent, str) and parent.strip() else None,
                rejected_members=rejected,
            )
        )
    return verified
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/application/test_ontology_discovery.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format research_team/application/ontology_discovery.py tests/application/test_ontology_discovery.py
uv run ruff check .
uv run ruff format --check .
git add research_team/application/ontology_discovery.py tests/application/test_ontology_discovery.py
git commit -m "Ask the document what its classes are, and believe only what it says

Reads whole documents, never chunks. The rank table's class name lives
entirely in its one-line header; a chunk boundary between that header and its
rows leaves the members with no name for what they belong to, which is exactly
the case this pass exists for. corpus_spans has no notion of a table and would
not prevent it. Cost: documents over 40,000 chars are refused rather than
windowed, because windowing reintroduces the same split with extra bookkeeping
and no measurement yet says how many real documents exceed the ceiling.

Verification is against the text, not against plausibility -- a model that
pattern-matches a taxonomy onto a document that states none produces something
indistinguishable by eye from a real discovery.

Three refusals at two severities, which is the part worth reading twice. A
member not in the text is dropped AND recorded, so the class survives minus
one and the reader is told why. A class whose evidence span is outside the
document is dropped whole: there is nothing left to open and judge, and
recording an uncheckable artefact is worse than losing it. An unrecognised
kind is dropped whole rather than coerced, because kind selects the entire
rendering and defaulting it would turn a misread into a claim about the text."
```

---

### Task 5: The service and the two adapters

**Files:**
- Modify: `research_team/application/ontology_discovery.py`
- Create: `research_team/infrastructure/agent/ontology_model.py`
- Create: `research_team/infrastructure/knowledge/ontology_recorder.py`
- Test: `tests/application/test_ontology_discovery.py`

**Interfaces:**
- Consumes: `build_prompt`, `parse_ontology`, `verify_classes`, `MAX_DISCOVERY_CHARS` (Task 4); `CorpusReadPort` (existing).
- Produces:
  - `OntologyTextPort` — `model_name: str` property, `async generate(prompt: str) -> str`
  - `OntologyRecordPort` — `async record(source_id: str, model_version: str, classes: list[DiscoveredClass]) -> None`
  - `OntologyDiscoveryService(corpus, model, recorder)` with `async discover(source_id: str) -> int | None`
  - `ChatModelOntologyText(model, *, model_name)`
  - `EventStoreOntologyRecorder(event_store, project_id)`

`discover` returns the number of classes recorded, or `None` when the document is unknown or over `MAX_DISCOVERY_CHARS`. An `int` and not a list: the caller is a route reporting what happened, and handing back the classes would make the route a second place that has to know their shape.

- [ ] **Step 1: Write the failing test**

```python
class _FakeModel:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    @property
    def model_name(self) -> str:
        return "fake-model"

    async def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class _FakeRecorder:
    def __init__(self) -> None:
        self.recorded: list[tuple[str, str, list]] = []

    async def record(self, source_id, model_version, classes) -> None:
        self.recorded.append((source_id, model_version, classes))


async def test_discovery_records_the_classes_the_document_supports(corpus):
    model = _FakeModel(
        '{"classes": [{"name": "Difficulty", "kind": "ordered_scale", '
        '"declared_count": 6, "evidence": {"start": 0, "end": 60}, '
        '"members": [{"name": "EASY", "ordinal": 0}]}]}'
    )
    recorder = _FakeRecorder()
    service = OntologyDiscoveryService(corpus=corpus, model=model, recorder=recorder)

    assert await service.discover("songs") == 1

    source_id, model_version, classes = recorder.recorded[0]
    assert (source_id, model_version) == ("songs", "fake-model")
    assert classes[0].members[0].name == "EASY"


async def test_a_document_that_states_no_classes_is_still_recorded(corpus):
    """An empty result is a real outcome and must reach the recorder, or the
    ungrouped sweep re-runs this document on every pass forever, at model
    cost. Would pass with an early `return` on an empty list only if this
    asserted the call count, which is why it does."""
    recorder = _FakeRecorder()
    service = OntologyDiscoveryService(
        corpus=corpus, model=_FakeModel('{"classes": []}'), recorder=recorder
    )

    assert await service.discover("songs") == 0
    assert len(recorder.recorded) == 1


async def test_an_unreadable_reply_records_nothing_at_all(corpus):
    """Distinct from the empty case above. An empty answer is the model
    saying 'no classes here'; an unparseable one is the model saying nothing
    we can read, and recording that as 'examined, none found' would mark the
    document done and stop anyone retrying it."""
    recorder = _FakeRecorder()
    service = OntologyDiscoveryService(
        corpus=corpus, model=_FakeModel("sorry"), recorder=recorder
    )

    assert await service.discover("songs") is None
    assert recorder.recorded == []


async def test_a_document_over_the_ceiling_is_refused_before_the_model_is_called(
    long_corpus,
):
    """Refused, not truncated: a truncated read drops a document's second half
    silently and reports success. The model must not be called, or the refusal
    costs the same as the work."""
    model = _FakeModel('{"classes": []}')
    service = OntologyDiscoveryService(
        corpus=long_corpus, model=model, recorder=_FakeRecorder()
    )

    assert await service.discover("huge") is None
    assert model.prompts == []


async def test_an_unknown_source_is_none_rather_than_an_exception(corpus):
    service = OntologyDiscoveryService(
        corpus=corpus, model=_FakeModel('{"classes": []}'), recorder=_FakeRecorder()
    )

    assert await service.discover("nope") is None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/application/test_ontology_discovery.py -k service -v`
Expected: FAIL with `NameError: name 'OntologyDiscoveryService' is not defined`

- [ ] **Step 3: Write the ports and the service**

Append to `research_team/application/ontology_discovery.py`:

```python
class OntologyTextPort(Protocol):
    """Turning a prompt into text, with the name of whatever did it.

    One method and one property, mirroring `DefinitionTextPort` and for the
    identical reason: anything wider would put LangChain's vocabulary in this
    layer's contract, which is what `tests/test_architecture.py` exists to
    prevent, and would make the fake above a mock of a chat model rather than
    six lines.
    """

    @property
    def model_name(self) -> str: ...

    async def generate(self, prompt: str) -> str: ...


class OntologyRecordPort(Protocol):
    """Appending the discovery event, without naming an event store here.

    The application layer states what it needs recorded; where that lands is
    infrastructure's business, the same division `KnowledgePort.ingest` keeps
    between "extract this document" and redstring's own append.
    """

    async def record(
        self, source_id: str, model_version: str, classes: list[DiscoveredClass]
    ) -> None: ...


class OntologyDiscoveryService:
    """One document's classes: read it, ask, verify, record.

    Bound to one project through the `CorpusReadPort` and the recorder it is
    handed, never through a parameter -- the same implicit binding
    `GraphReadPort` documents at length, and for the same reason: a project id
    a caller can pass is a knob that can be turned to the wrong project.
    """

    def __init__(
        self, *, corpus: CorpusReadPort, model: OntologyTextPort, recorder: OntologyRecordPort
    ) -> None:
        self._corpus = corpus
        self._model = model
        self._recorder = recorder

    async def discover(self, source_id: str) -> int | None:
        """How many classes were recorded, or `None` when nothing was.

        The three `None`s are deliberately not distinguished in the return
        type -- unknown source, document too long, unreadable reply. They
        differ in cause and agree in consequence: nothing was recorded, the
        document stays ungrouped, and retrying is the answer to all three. A
        richer result type would be three cases every caller has to handle to
        do one thing.

        **An empty result is recorded, and that is not the same as `None`.**
        Zero classes says "examined, states none" and takes the document off
        the sweep. `None` says "not examined", and leaves it on.
        """
        document = await self._corpus.read_document(source_id)
        if document is None:
            return None
        if len(document.text) > MAX_DISCOVERY_CHARS:
            return None

        raw = await self._model.generate(build_prompt(document.text))
        proposals = parse_ontology(raw)
        if not proposals and raw.strip() and not _looks_like_empty_answer(raw):
            # An unreadable reply is not an empty one. Recording it as
            # "examined, none found" would mark the document done and stop
            # anyone retrying a call that simply failed to parse.
            return None

        classes = verify_classes(
            proposals, document_text=document.text, source_id=source_id
        )
        await self._recorder.record(source_id, self._model.model_name, classes)
        return len(classes)
```

`_looks_like_empty_answer` is a small module-level helper returning `True` when `parse_ontology` succeeded on a payload whose `classes` key was present and empty. Implement it by having `parse_ontology` be the single parser and adding a sibling `parsed_successfully(raw) -> bool`, or restructure `parse_ontology` to return `list | None` — **choose one and use it consistently**; the tests above pin the behaviour, not the internal shape.

- [ ] **Step 4: Write the model adapter**

```python
# research_team/infrastructure/agent/ontology_model.py
"""`OntologyTextPort` over a LangChain chat model.

Beside `definition_model.py` and structurally identical to it, for the reason
that file gives: this is the only place LangChain's vocabulary is allowed to
meet the discovery use case.

The extraction model, shared, not a second client -- discovery is the same job
extraction already does (read this material, answer with JSON about it, invent
nothing) against the same endpoint, and `build_extraction_model` has already
taken the decision that matters (thinking off). The cost of sharing is stated
rather than hidden: `AGENT_EXTRACTION_THINKING` and `AGENT_MODEL` apply to
both, so a build tuned for extraction tunes discovery too.
"""

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage


class ChatModelOntologyText:
    def __init__(self, model: BaseChatModel, *, model_name: str) -> None:
        self._model = model
        self._model_name = model_name

    @property
    def model_name(self) -> str:
        return self._model_name

    async def generate(self, prompt: str) -> str:
        response = await self._model.ainvoke([HumanMessage(prompt)])
        return str(response.content)
```

- [ ] **Step 5: Write the recorder**

```python
# research_team/infrastructure/knowledge/ontology_recorder.py
"""`OntologyRecordPort` over the event store.

The only place this feature appends. `OntologyDiscovered` enforces no
invariant -- a pass replaces a source's classes wholesale -- so it goes
straight to the store rather than through a `DeciderAggregate`, exactly as
redstring appends `DocumentExtracted` without consulting one of this
application's aggregates. See `domain/ontology.py` for the full reasoning.
"""
```

Implement `EventStoreOntologyRecorder(event_store, project_id)` with a `record` that constructs `OntologyDiscovered(aggregate_id=project_id, project_id=project_id, ...)` and appends it. Follow `redstring_adapter.py:417`'s append call shape exactly, including how it obtains the expected version.

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/application/test_ontology_discovery.py -v`
Expected: PASS (all 12)

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format research_team/application/ontology_discovery.py research_team/infrastructure/agent/ontology_model.py research_team/infrastructure/knowledge/ontology_recorder.py tests/application/test_ontology_discovery.py
uv run ruff check .
uv run ruff format --check .
git add research_team/application/ontology_discovery.py research_team/infrastructure/agent/ontology_model.py research_team/infrastructure/knowledge/ontology_recorder.py tests/application/test_ontology_discovery.py
git commit -m "Run one document through discovery, and record even when it finds nothing

Zero classes is recorded; an unreadable reply is not. They look alike and are
opposite: 'examined, states none' takes the document off the sweep, while
'the call failed to parse' has to leave it on, or a transient failure marks a
document permanently done and nobody retries it. The tests pin both.

Documents over the ceiling are refused before the model is called -- refusing
after would cost the same as the work, and truncating instead would drop a
document's second half silently while reporting success.

The three None cases (unknown source, too long, unreadable) are deliberately
not distinguished in the return type. They differ in cause and agree in
consequence: nothing recorded, still ungrouped, retry is the answer to all
three. A richer result would be three cases every caller handles to do one
thing.

The model adapter shares the extraction client rather than adding a second.
Discovery is the same job against the same endpoint; the cost is that
AGENT_MODEL and AGENT_EXTRACTION_THINKING now tune both."
```

---

### Task 6: Composition wiring and the `ungrouped` listing

**Files:**
- Modify: `research_team/composition.py`
- Modify: `research_team/application/document_extraction.py`
- Test: `tests/application/test_document_extraction.py`

**Interfaces:**
- Consumes: `OntologyRunner` (Task 3), `OntologyDiscoveryService`, `ChatModelOntologyText`, `EventStoreOntologyRecorder` (Task 5).
- Produces:
  - `Application.ontology: OntologyRunner`
  - `Application.ontology_discoverers: Callable[[UUID], Awaitable[OntologyDiscoveryService | None]]`
  - `DocumentExtractor.ungrouped(project_id, examined: set[str]) -> tuple[str, ...]`

`ungrouped` takes the examined set as a parameter rather than reaching for the ontology store itself. `DocumentExtractor` knows about the corpus and the graph and has no business knowing about ontology tables; the route joins the two. This also keeps the function pure enough to test without a store.

- [ ] **Step 1: Write the failing test**

```python
async def test_ungrouped_lists_extracted_documents_no_pass_has_examined(extractor, project_id):
    """Extracted, because a document with no entities has no members for a
    class to resolve against; and not examined, because a document the pass
    looked at and found nothing in is done, not pending. Conflating the second
    with 'has no classes' would re-run every barren document on every sweep,
    at model cost -- which is the whole reason the examined set is recorded
    separately from the class rows."""
    result = await extractor.ungrouped(project_id, examined={"songs"})

    assert "songs" not in result
    assert "ranks" in result
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/application/test_document_extraction.py -k ungrouped -v`
Expected: FAIL with `AttributeError: 'DocumentExtractor' object has no attribute 'ungrouped'`

- [ ] **Step 3: Implement `ungrouped`**

Model it on `DocumentExtractor.unextracted` (`document_extraction.py:107`) — read that method first and match its shape. It returns extracted source ids minus `examined`.

- [ ] **Step 4: Wire the runner**

In `composition.py`, at the three registration points the comment at `:702-707` names ("a projection wired somewhere else is a projection somebody forgets to start"):

1. Construct beside `definition_invalidation` (~`:716`):
```python
    ontology = OntologyRunner(repository.store, resolved_path, repository.publisher, resolved_tracer)
```
2. Add `ontology: OntologyRunner` to the `Application` dataclass beside `definitions` (~`:206`), and pass it in the constructor call (~`:1671`).
3. Add `await self.ontology.start()` to `start()` beside `:415`, and the matching lines in `caught_up` (~`:477`) and `stop` (~`:498`).

- [ ] **Step 5: Wire the service factory**

Beside `definition_reader` (~`:1493`):

```python
    async def ontology_discoverer(target_project_id: UUID) -> OntologyDiscoveryService | None:
        return OntologyDiscoveryService(
            corpus=ProjectCorpusReader(corpus, target_project_id),
            model=ChatModelOntologyText(extraction_model, model_name=config.model_name()),
            recorder=EventStoreOntologyRecorder(repository.store, target_project_id),
        )
```

**Read `definition_reader`'s body before writing this.** It carries an ordering fix at `:1520-1529` — `await graphs.open(pid)` before `graphs.chunks(pid)` — because the first definition request for any newly-touched project answered 503 otherwise, once per project, indistinguishable from flakiness. This factory does not touch `graphs` at all, so that specific hazard does not apply; confirm that is still true when you write it rather than assuming it.

- [ ] **Step 6: Run the affected suites**

Run: `uv run pytest tests/application/test_document_extraction.py tests/test_composition.py -v`
Expected: PASS

- [ ] **Step 7: Format, lint, commit**

```bash
uv run ruff format research_team/composition.py research_team/application/document_extraction.py tests/application/test_document_extraction.py
uv run ruff check .
uv run ruff format --check .
git add research_team/composition.py research_team/application/document_extraction.py tests/application/test_document_extraction.py
git commit -m "Wire the ontology runner, and say which documents still need a pass

ungrouped takes the examined set as a parameter rather than reaching for the
ontology store. DocumentExtractor knows the corpus and the graph and has no
business knowing about ontology tables; the route joins them, and the function
stays testable without a store.

Examined is not the same as has-classes, and the listing depends on the
difference. A document the pass looked at and found nothing in is done; if
'no classes' meant 'pending', every barren document would be re-run on every
sweep at model cost."
```

---

### Task 7: The routes

**Files:**
- Modify: `research_team/interfaces/web/app.py`
- Test: `tests/interfaces/test_ontology_routes.py`

**Interfaces:**
- Consumes: `Application.ontology`, `Application.ontology_discoverers`, `DocumentExtractor.ungrouped`.
- Produces: three routes.

| Route | Shape | Why |
|---|---|---|
| `POST /api/projects/{project_id}/sources/{source_id}/ontology` | 202 via `extract_queue`, 404 on unknown source | A queued model call a human waits on — the same thing `…/extract` (`app.py:937`) is |
| `POST /api/projects/{project_id}/sources/ontology` | 202, sweeps `ungrouped` | Mirrors `extract_all_sources` (`app.py:865`) |
| `GET /api/projects/{project_id}/ontology` | 200 with classes + members, 503 when the runner is unwired | Mirrors `/api/corpus/rebuild`'s 503-when-unwired shape |

**Do not add a per-project rebuild route.** All three existing rebuild endpoints are process-wide and `EntityDefinitionRunner.rebuild()` is exposed by none. This feature should not invent a per-project rebuild convention as a side effect; that is a separate decision.

- [ ] **Step 1: Write the failing test**

```python
async def test_the_ontology_route_returns_classes_with_their_evidence_and_rejections(
    client, project_id, seeded_ontology
):
    """Asserts the payload's contents, not its status. An event no projection
    handles counts as applied, so a build with OntologyRunner unregistered
    answers this route 200 with an empty list -- a status assertion passes
    against exactly the bug this feature is most likely to ship with."""
    response = await client.get(f"/api/projects/{project_id}/ontology")

    body = response.json()
    (klass,) = body["classes"]
    assert klass["name"] == "Difficulty"
    assert klass["kind"] == "ordered_scale"
    assert (klass["declaredCount"], klass["memberCount"]) == (6, 2)
    assert klass["evidence"] == {"sourceId": "songs", "start": 10, "end": 90}
    assert klass["rejectedMembers"] == [{"name": "LEGEND", "reason": "not in the document"}]
    assert [m["name"] for m in klass["members"]] == ["EASY", "NORMAL"]


async def test_queueing_an_ontology_pass_for_an_unknown_source_is_404(client, project_id):
    response = await client.post(f"/api/projects/{project_id}/sources/nope/ontology")

    assert response.status_code == 404


async def test_the_ontology_route_is_503_when_the_runner_is_unwired(client_without_ontology, project_id):
    """The same shape /api/corpus/rebuild uses. 503 rather than an empty 200,
    because an empty 200 is what a project with no classes correctly returns,
    and a misconfigured build must not be indistinguishable from a project
    nobody has run the pass on."""
    response = await client_without_ontology.get(f"/api/projects/{project_id}/ontology")

    assert response.status_code == 503
```

Match the JSON casing convention the neighbouring routes already use — read one of them and follow it rather than assuming camelCase.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/interfaces/test_ontology_routes.py -v`
Expected: FAIL with 404 on every route

- [ ] **Step 3: Implement the routes**

Follow `extract_source` (`app.py:937`) for the queued pair — including its `if await _reader(project_id).read_document(source_id) is None: 404` guard at `:959` — and `read_graph_definition` (`app.py:1535`) for the read.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/interfaces/test_ontology_routes.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Format, lint, commit**

```bash
uv run ruff format research_team/interfaces/web/app.py tests/interfaces/test_ontology_routes.py
uv run ruff check .
uv run ruff format --check .
git add research_team/interfaces/web/app.py tests/interfaces/test_ontology_routes.py
git commit -m "Serve the discovered ontology, and queue the pass that finds it

202 through the existing extraction queue for the two write routes, matching
the extract routes: a queued model call a human waits on. 503 rather than an
empty 200 on the read when the runner is unwired -- an empty 200 is what a
project with no classes correctly returns, and a misconfigured build must not
be indistinguishable from one nobody has run the pass on.

Deliberately no per-project rebuild route. All three existing rebuild
endpoints are process-wide and the definition runner's rebuild is exposed by
none; inventing a per-project convention as a side effect of this feature is
a separate decision."
```

---

### Task 8: Joining classes into the graph read

**Files:**
- Modify: `research_team/application/graph_read.py`
- Modify: `research_team/infrastructure/knowledge/graph_reader.py`
- Test: `tests/infrastructure/test_graph_reader.py`

**Interfaces:**
- Consumes: `OntologyRunner.classes_for` / `.members_for` (Task 3).
- Produces: `GraphEntity.inferred: bool = False`; `MAX_ONTOLOGY_CLASSES: int = 200`; class nodes with `entity_type="class"` and edges with `relationship_type="instance_of"`.

**This task touches files the `temporal` lane owned, and that lane is doing a cutover, not a patch. Re-read `graph_reader.py`, `graph_read.py` and `temporal_rendering.py` before writing anything** — this plan was written against the versions at `334ff85`.

What is known to be changing, as of 2026-08-15: `temporal` found that redstring's parser was destroying extraction's output in two ways — BC dates are structurally unparseable (`parse_temporal` has no BC branch, and `datetime.MINYEAR == 1` means no pre-1 AD year is storable at all), and AD dates were being *fabricated*, with `AD 476` acquiring a month and day from the source article's publication date and stored at DAY precision. Both are in the real database now. The fix is a signed-year interval type replacing `datetime` in the temporal representation, so:

- **`GraphEntity.temporal` may change shape** — assume it does. This task adds `GraphEntity.inferred` beside it; add the field, do not reformat what is around it.
- **`temporal_rendering.render_extent` almost certainly changed.** `_to_graph_entity` calls it. Do not touch that call.
- **`TimelineBand` may emit numbers rather than ISO strings.** Outside this task entirely; do not follow it.

None of this touches the class layer, which carries no dates — the risk is collision in the same functions, not conflicting semantics. If a code block below no longer matches the file, **port the reasoning, not the diff**; the reasoning is what this plan is for.

Confirm rather than assume that `read_models.py:1261` is untouched, since the case for a separate pass (spec §3) rests on `EntityDefinitionProjection` staling every entity in a `DocumentExtracted`.

- [ ] **Step 1: Write the failing test**

```python
async def test_a_discovered_class_arrives_as_an_inferred_node_with_inferred_edges(
    reader, seeded_ontology
):
    graph = await reader.whole()

    (klass,) = [e for e in graph.entities if e.entity_type == "class"]
    assert klass.name == "Difficulty"
    assert klass.inferred is True

    edges = [r for r in graph.relationships if r.relationship_type == "instance_of"]
    assert {e.target_id for e in edges} == {klass.entity_id}
    assert all(e.inferred for e in edges)


async def test_an_instance_of_edge_carries_the_sentence_it_came_from(reader, seeded_ontology):
    """An inferred edge with no visible derivation is indistinguishable from
    an asserted one -- the confusion `derivation` exists to prevent. Here the
    derivation is the quoted evidence, not arithmetic."""
    graph = await reader.whole()

    (edge,) = [r for r in graph.relationships if r.relationship_type == "instance_of"][:1]
    assert "six difficulties" in edge.derivation


async def test_a_member_that_resolves_to_no_entity_draws_no_edge(reader, ontology_with_orphan):
    """The staleness contract. The membership row survives with a null
    entity_id -- Task 2 pins that -- and here it must produce no edge, because
    an edge to a node the caller was not given is an edge it cannot draw. That
    is the same dangling-reference rule `returned_ids` already enforces for
    stored edges."""
    graph = await reader.whole()

    node_ids = {e.entity_id for e in graph.entities}
    for edge in graph.relationships:
        assert edge.source_id in node_ids and edge.target_id in node_ids


async def test_ordinary_entities_are_not_marked_inferred(reader, seeded_ontology):
    """`inferred` defaults False and must stay False for everything redstring
    stored. A test asserting only that class nodes are inferred would pass
    against an implementation that marked every node."""
    graph = await reader.whole()

    assert all(not e.inferred for e in graph.entities if e.entity_type != "class")


async def test_classes_past_the_cap_set_inferred_truncated(reader, many_classes):
    """A drawing missing lines looks exactly like a drawing with none to miss.
    Class nodes are not entities, so MAX_GRAPH_NODES does not bound them and
    nothing else would."""
    graph = await reader.whole()

    assert graph.inferred_truncated is True
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/infrastructure/test_graph_reader.py -k class or ontology or inferred -v`
Expected: FAIL — no class nodes in the result

- [ ] **Step 3: Add the DTO field**

```python
    inferred: bool = False
    """Derived by a pass rather than extracted from a document.

    True only for the class nodes an ontology pass produced. It exists
    because a class node's id is synthetic -- no redstring entity has it -- so
    a client that fetches `/neighborhood` or `/definition` on click must not
    fetch for this node: both would answer for an entity the store does not
    have. Defaulted, so every existing construction site and test is
    unaffected, exactly as `GraphRelationship.inferred` was.
    """
```

And the cap:

```python
#: How many discovered classes reach one drawing. Separate from
#: `MAX_GRAPH_NODES`, which counts redstring entities and would not see these
#: at all -- a class node is synthesised on read. Low relative to the node cap
#: because a class is a hub: 200 classes averaging ten members each is 2,000
#: edges on their own, which is `MAX_INFERRED_EDGES` spent before a single
#: temporal edge is drawn.
MAX_ONTOLOGY_CLASSES = 200
```

- [ ] **Step 4: Join them in the reader**

In `whole`, after `inferred, inferred_truncated = _inferred_edges(kept)`:

```python
        # After `_inferred_edges`, so the two derived sources share one
        # truncation verdict rather than each reporting its own -- a reader
        # told "some computed lines were dropped" does not care which pass
        # dropped them, and two flags would be two things to check.
        classes, class_edges, classes_truncated = await self._ontology_layer(kept)
```

Implement `_ontology_layer(entities)` to fetch the project's classes, resolve each membership's `entity_id` against the ids in `entities`, drop unresolved members, and return the nodes, the edges and whether the cap cut any. **Resolve against the entities passed in, not against the store** — the same reasoning `_inferred_edges`'s docstring gives for why it needs no both-ends filter.

Repeat in `neighborhood`, restricted to classes at least one of whose members is in the returned set — a class node with no drawable members is a bare hub.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_graph_reader.py -v`
Expected: PASS

- [ ] **Step 6: Prove them red**

Delete the `_ontology_layer` call from `whole` and re-run. Expected: FAIL. Restore it.

- [ ] **Step 7: Run the whole Python suite and both ruff gates**

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

- [ ] **Step 8: Verify against a database that predates the change**

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/claude-1000/probe.db
```

Then start the app against the printed `AGENT_DB=` line and fetch `GET /api/projects/3881dec0-6d7c-4418-aaa0-f45d2a97032a/graph`. Expected: 200, unchanged from before this task, with no class nodes — the pass has not been run against that database yet. **Use `local_copy`, not `cp`**: a hand-copied database will not open, because every checkpoint's position token carries a store id derived from the database path, and `PositionForeignError` is raised before a single event replays. Do not "fix" that by deleting the checkpoints — an empty `projection_checkpoints` replays the whole log, which is `/rebuild` by another name and hides exactly the resume-near-the-end behaviour this step exists to exercise.

- [ ] **Step 9: Commit**

```bash
git add research_team/application/graph_read.py research_team/infrastructure/knowledge/graph_reader.py tests/infrastructure/test_graph_reader.py
git commit -m "Draw discovered classes as inferred nodes, capped with the other derived edges

GraphEntity gains `inferred` because a class node's id is synthetic -- no
redstring entity has it -- so a client fetching /neighborhood or /definition
on click must not fetch for this node. Both would answer for an entity the
store does not have.

The class layer is counted against MAX_ONTOLOGY_CLASSES and folded into the
existing inferred_truncated flag rather than getting its own. A reader told
some computed lines were dropped does not care which pass dropped them, and
two flags are two things to check. The cap is low relative to the node cap
because a class is a hub: 200 classes at ten members each is MAX_INFERRED_EDGES
spent before a single temporal edge is drawn.

A membership that resolves to no entity draws no edge while keeping its row --
an edge to a node the caller was not given is one it cannot draw, the same
dangling-reference rule returned_ids already enforces for stored edges.

Proved red by deleting the join from whole(). Verified against a copy of the
real database made with local_copy, not cp -- a hand copy raises
PositionForeignError before replaying anything, and clearing the checkpoints
to get past that replays the whole log and hides the resume behaviour the
check exists for."
```

---

### Task 9: Frontend types and click suppression

**Files:**
- Modify: `frontend/src/domain/knowledge/graph.ts`
- Modify: the panel component that fetches on node click (locate it — `GraphCanvas.tsx`'s click handler names it)
- Test: alongside each, following the existing `*.test.tsx` convention

**Interfaces:**
- Consumes: the API shape from Task 8.
- Produces: `GraphNode.inferred?: boolean`.

**This task touches files the `graphview` lane owned. Re-read `graph.ts` and `GraphCanvas.tsx` before writing** — this plan was written against `334ff85`.

- [ ] **Step 1: Write the failing test**

```typescript
it('does not fetch a definition or a neighbourhood for an inferred class node', async () => {
  // A class node's id is synthetic: no redstring entity has it, so
  // /definition answers for nothing and /neighborhood answers 404. Asserting
  // the fetch does not happen, rather than that the error is handled, because
  // a handled 404 still costs a round trip on every click and still puts a
  // spurious failure in the network log.
  render(<Panel node={{ id: 'synthetic', name: 'Difficulty', entityType: 'class', inferred: true }} />)

  await waitFor(() => expect(screen.getByText('Difficulty')).toBeInTheDocument())
  expect(fetchSpy).not.toHaveBeenCalled()
})

it('still fetches for an ordinary node', () => {
  // Would pass with fetching disabled entirely, which is why it is here.
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/research --reporter=verbose`
Expected: FAIL — the fetch happens.

Do not run this concurrently with any other vitest process.

- [ ] **Step 3: Add the field**

```typescript
  /** Whether this node was synthesised by a derivation pass rather than
   *  extracted from a document -- today, a discovered ontology class.
   *
   *  Load-bearing beyond display: a synthetic node's id belongs to no stored
   *  entity, so `/definition` and `/neighborhood` must not be fetched for it.
   *  Optional for the same reason `temporal` is -- every existing test and
   *  construction site predates it. */
  readonly inferred?: boolean
```

- [ ] **Step 4: Guard the fetches, run tests to verify they pass**

Run: `cd frontend && npx vitest run src/presentation/research src/domain/knowledge --reporter=verbose`
Expected: PASS

- [ ] **Step 5: Run the full frontend gate**

```bash
cd frontend && npm run verify
```

This is the only command that covers the prettier check and the bundle-size budget, and they are the two that fail in CI. If the budget trips, raise it rather than shaving the feature — that is this project's stated preference — and say so in the commit.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/domain/knowledge/graph.ts frontend/src/presentation/research
git commit -m "Stop clicking a synthesised class node from fetching a real entity

A discovered class's node id is synthetic: no redstring entity has it, so
/definition answers for nothing and /neighborhood answers 404. Guarded at the
fetch rather than by handling the error, because a handled 404 still costs a
round trip on every click and still writes a spurious failure into the network
log a reader may be reading for real ones.

The field is optional, like temporal before it, so every existing construction
site and test is untouched."
```

---

### Task 10: The ontology view

**Files:**
- Create: `frontend/src/domain/knowledge/ontology.ts`
- Create: `frontend/src/presentation/research/OntologyPane.tsx`
- Test: `frontend/src/domain/knowledge/ontology.test.ts`, `frontend/src/presentation/research/OntologyPane.test.tsx`

**Interfaces:**
- Consumes: `GET /api/projects/{id}/ontology` (Task 7).
- Produces: `OntologyClass`, `OntologyMember`, `foldOntology(payload) -> readonly OntologyClass[]`, `<OntologyPane projectId />`.

**What this view owes the reader**, from the spec's §6 — each is a test, not a hope:

1. **The evidence opens the source document at the span.** Not an inline quote. Quoted text proves the model wrote a sentence; opening the document proves the sentence is in it. `GET /api/projects/{id}/sources/{source_id}` already serves the text (`app.py:1038`) and a document reader already exists.
2. **The checksum is visible**, "6 of 6 stated" or "5 of 6 stated", and the rejected members are shown beside it with their reasons.
3. **`kind` selects the layout** — ordered scale in ordinal order, unordered set deliberately unordered, taxonomy nested.
4. **Everything is marked derived**, in the visual language the dashed inferred edges already establish.

- [ ] **Step 1: Write the failing fold test**

```typescript
it('orders an ordered scale by ordinal, not by arrival', () => {
  // The API returns rows in whatever order SQLite gave them. An ordered scale
  // rendered in arrival order asserts a sequence the text did not state --
  // and D/C/B/A/S is precisely a case where alphabetical, arrival and stated
  // order all differ, so a fixture in stated order would not catch it.
  const folded = foldOntology({
    classes: [{
      name: 'Rank', kind: 'ordered_scale', declaredCount: 5, memberCount: 5,
      evidence: { sourceId: 's', start: 0, end: 10 }, rejectedMembers: [],
      members: [
        { name: 'B rank', ordinal: 2 },
        { name: 'S rank', ordinal: 4 },
        { name: 'D rank', ordinal: 0 },
      ],
    }],
  })

  expect(folded[0].members.map((m) => m.name)).toEqual(['D rank', 'B rank', 'S rank'])
})

it('leaves an unordered set in arrival order and marks it unordered', () => {
  // Sorting a bag would read a sequence into it. The inverse of the case
  // above, and the reason `kind` is carried rather than inferred from
  // whether ordinals are present.
})

it('reports a class whose members fall short of its declared count', () => {
  const folded = foldOntology({ classes: [{ /* declaredCount: 6, 5 members */ }] })

  expect(folded[0].complete).toBe(false)
})

it('keeps a class that samples a much larger set, and shows both numbers', () => {
  // Measured 2026-08-15: wiki-roman-economy declares 268 occupations and names
  // nine. The prompt asks the model not to report open lists; when it does
  // anyway, "9 of 268" is what makes the class self-evidently a sample. Kept
  // rather than dropped at some ratio threshold -- a threshold would be a
  // number nobody could justify, and the reader can see 9 of 268 for what it
  // is faster than any rule could classify it.
  const folded = foldOntology({
    classes: [{ name: 'Occupation', kind: 'unordered_set', declaredCount: 268,
                memberCount: 9, /* nine members */ }],
  })

  expect(folded[0].complete).toBe(false)
  expect(folded[0].declaredCount).toBe(268)
  expect(folded[0].members).toHaveLength(9)
})
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/domain/knowledge/ontology.test.ts --reporter=verbose`
Expected: FAIL — module not found

- [ ] **Step 3: Write the fold**

A pure module: no fetching, no React, no store — the shape `graph.ts` establishes and for the same reason, that the merge semantics have correctness properties easy to break under refactoring pressure from the caller.

- [ ] **Step 4: Write the pane and its test**

```typescript
it('links a class to its evidence in the source document', () => {
  render(<OntologyPane {...props} />)

  expect(screen.getByRole('link', { name: /evidence/i })).toHaveAttribute(
    'href', expect.stringContaining('start=10'),
  )
})

it('shows the checksum and the rejected members together', () => {
  // Separately, a "5 of 6" is an unexplained gap and a rejection list is
  // noise. Together they are the reader's whole basis for judging whether the
  // pass invented a member or the document is genuinely short one, which are
  // opposite conclusions about whether to trust it.
  render(<OntologyPane {...props} />)

  expect(screen.getByText(/5 of 6/)).toBeInTheDocument()
  expect(screen.getByText(/LEGEND/)).toBeInTheDocument()
  expect(screen.getByText(/not found in the document/)).toBeInTheDocument()
})
```

- [ ] **Step 5: Run the frontend gate**

```bash
cd frontend && npm run verify
```

- [ ] **Step 6: If you touched a stylesheet or a layout primitive, run the browser suite**

```bash
cd frontend && npm run test:browser
```

Outside `verify` and outside CI, so nothing forces it. Run it anyway if this pane's correctness is a computed style or a measurement: jsdom lays nothing out, `getComputedStyle` returns only what an inline style said, and a selector matching nothing is indistinguishable from one that matches.

Two traps if you write one: the viewport is set in `vite.config.ts` and a media query reads *that*, not the width of the wrapper the test renders into; and `vitest.setup.browser.ts` is deliberately separate from `vitest.setup.ts`, because the jsdom setup pins `offsetWidth`/`offsetHeight` to constants and would blind the one suite whose job is measuring.

And if you write a border: `border-solid` beside one directional width draws three unwanted sides, because this build imports no Tailwind preflight. Pair `border-0` with the directional width, or use the directional width alone.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/domain/knowledge/ontology.ts frontend/src/domain/knowledge/ontology.test.ts frontend/src/presentation/research/OntologyPane.tsx frontend/src/presentation/research/OntologyPane.test.tsx
git commit -m "Render the class layer so a reader can judge it

kind selects the layout because a force-directed canvas cannot draw order:
five spokes into a Rank hub look identical whether or not the ranks form a
scale, and the ordinal exists in the data and is invisible there. An ordered
scale sorts by ordinal, an unordered set deliberately does not -- sorting a
bag would read a sequence into it.

Evidence links into the source document rather than quoting inline. Quoted
text proves the model wrote a sentence; opening the document proves the
sentence is in it, which is the different and stronger claim, and the route
that serves the text already exists.

The checksum and the rejections are shown together. Separately a '5 of 6' is
an unexplained gap and a rejection list is noise; together they are the
reader's whole basis for telling an invented member from a document genuinely
short one, which are opposite conclusions about whether to trust the pass."
```

---

### Task 11: The measurement that gates layer 3

**Files:**
- Create: `docs/extraction/ontology-class-counts.md` (findings only — no code)

**Interfaces:**
- Consumes: everything above.
- Produces: a number per project, and a recommendation.

The spec gates layer 3 — schema refinement, which needs per-project schema selection that does not exist today — on this count. Do not build layer 3 before running it.

- [ ] **Step 1: Run the sweep against a copy of the real database**

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/claude-1000/ontology-probe.db
```

Start the app against the printed `AGENT_DB=` line, then `POST /api/projects/{id}/sources/ontology` for each of the three projects:

- Project SEKAI `3881dec0-6d7c-4418-aaa0-f45d2a97032a` (55 entities, 11 `category`)
- Ancient Rome `cf4d9a61-2a81-4ca9-9432-d34cfe5c7a61` (2,525 entities, 116 `category`)
- budgeting `bbb418fd-db5d-4d17-84a3-9636d5a456db` (174 entities, 45 `category`)

**A copy, not the real database.** This makes paid model calls and writes events; running it against `~/.research-team/sessions.db` puts derived events in the user's real log before anyone has judged whether the pass is any good.

- [ ] **Step 2: Record the counts**

For each project: classes found, members resolved vs unresolved, classes whose `declared_count` disagreed with `member_count`, and classes dropped by verification. Note the date and that these are measured, not reasoned.

- [ ] **Step 3: Judge the output by hand**

Open each class's evidence in the source document. The question is not "did it find things" but "is what it found stated by the text". A pass that finds twenty plausible classes in Ancient Rome that the text does not state is a worse result than finding two in SEKAI that it does.

- [ ] **Step 4: Recommend**

The spec's prediction, measured 2026-08-15 rather than reasoned: SEKAI yields several classes, the other two yield near zero. The evidence is **zero enumerating sentences across all five Ancient Rome documents**, against one in the SEKAI document that is the whole basis of this feature. Expect at most one Rome candidate — `wiki-roman-economy`'s "268 different occupations… including" — and expect it to render as `9 of 268`, which is the checksum correctly identifying a sample rather than a set.

**If the prediction holds, recommend deferring layer 3** — per-project schema machinery built for one document is machinery bought on a promise it cannot keep. If it does not hold, say so plainly; the prediction was a prediction, and it is written down here so it can be scored rather than quietly forgotten.

- [ ] **Step 5: Commit the findings**

```bash
git add docs/extraction/ontology-class-counts.md
git commit -m "Count what discovery actually finds, before buying schema machinery for it

The spec gates layer 3 on this. Per-project schema selection does not exist --
selection is one process-wide env var with nothing on the Project aggregate --
so layer 3 is the largest cost in the design, and it is only worth paying if
more than one project produces classes.

Judged by opening each class's evidence in the source, not by counting rows.
Twenty plausible classes the text does not state is a worse result than two it
does, and only the first is visible in a count."
```

---

## Self-Review

**Spec coverage.** Walked each spec section against a task: §1 crux → the whole architecture, Tasks 1–3. §2 rejected-alternative → no task, correctly (it is a rejection). §3 separate pass → Tasks 5–7. §4 event/read models/projection/service/whole-document/routes → Tasks 1, 2, 3, 4, 5, 7. §5 graph join, `instance_of`, `GraphEntity.inferred`, caps → Task 8. §6 inspectability → Tasks 2 (`rejected_members`), 4 (recording rejections), 10 (all four obligations). §7 layer 3 → Task 11's gate, then a separate plan. §8 tests → distributed, with the assert-rows-not-status rule in Tasks 3 and 7, the fixture-that-has-not-run-the-pass in Task 8's orphan test, and every named failure shape present. §9 not-built → carried as comments in Tasks 2 and 4.

**One gap found and closed while reviewing.** The spec's §8 lists "a fixture that has not run the pass" as a test obligation, and the first draft of Task 8 had no such case. Task 8's `test_a_member_that_resolves_to_no_entity_draws_no_edge` now covers the resolution half; the composition half — a reader whose ontology store was never opened — is covered by Task 7's 503 test. Neither alone is enough, which is why both are there.

**Placeholder scan.** No TBDs. Three places delegate a shape to an existing file rather than inlining it (Task 2's `_delete_source` SQL, Task 5's recorder append, Task 7's JSON casing). Each names the exact file and line to copy from, because inventing a second convention beside an existing one is a worse failure than the extra lookup.

**Type consistency.** `DiscoveredClass.kind` is `str` on the row and `Literal` on the event — intentional, and stated in Task 2: a `ReadModel` column that refused an unknown value would put a replay in the DLQ for a payload the log already accepted. `member_count` is the row's, `declaredCount`/`memberCount` are the API's camelCase — Task 7's test pins the boundary and instructs matching the neighbours rather than assuming. `entity_id` is `UUID | None` throughout. `discover` returns `int | None` in Tasks 5, 6 and 7 alike.

**One risk this plan cannot close.** Tasks 8 and 9 modify files two other agents held concurrently, and this plan was written against `334ff85`. Both tasks open with an instruction to re-read before writing. If the DTOs moved, the code blocks are wrong and the reasoning in them still holds — port the reasoning, not the diff.

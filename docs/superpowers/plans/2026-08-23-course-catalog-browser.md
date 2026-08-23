# Course Catalog Browser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Curriculum tab into a browsable course catalog — candidates
grouped into categories, ranked by prominence, drawn as three sections of
differently-sized cards.

**Architecture:** A catalog is *derived* from the existing curriculum
projection on every request, exactly as areas are. Generated blurbs are cached
against a membership hash (following `entity_definitions`). The one thing on
the event log is the featured override, because that is a person's decision
rather than a derivation.

**Tech Stack:** Python 3.13, FastAPI, `eventsource-py`, aiosqlite, pytest.
React 19, TanStack Query, Tailwind v4, vitest.

**Spec:** `docs/superpowers/specs/2026-08-23-course-catalog-browser-design.md`

## Global Constraints

- **Four gates, all of them:** `uv run ruff check .`, `uv run ruff format --check .`,
  `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run
  over the whole repository, not the files you touched.
- **`npm run test:browser` is required for this work.** Card size is a computed
  style; jsdom reports every card identical.
- **Never run two vitest processes at once.** Re-run a failing frontend test alone
  before investigating it.
- **Assert on data, never on status.** An event no projection handles counts as
  applied, so a missing projection yields an empty read model and a 200. A test
  that asserts "the request succeeded" passes against exactly the bug this
  codebase ships most often.
- **Every port here has exactly one production adapter.** Each needs one test that
  drives *both ends over real data*. A stub on one side and a unit test on the
  other proves the halves work and cannot prove they meet.
- **`border-0` before a directional width.** This build imports no preflight, so
  `border-dashed` with only `border-l-2` draws the browser's ~3px default on the
  other three sides. Never pair `border-0` with a non-directional `border`.
- Comments explain **why**. State costs. Say when something was measured rather
  than reasoned. A test that would pass with the change reverted says so in its
  docstring.

---

### Task 1: Catalog value objects

**Files:**
- Create: `research_team/domain/course_catalog.py`
- Test: `tests/domain/test_course_catalog.py`

**Interfaces:**
- Consumes: `LearningArea`, `AreaMember` from `research_team.domain.learning_area`
- Produces: `CategoryKey`, `ArtRef`, `Blurb`, `CourseCandidate`, `Category`,
  `CatalogSections`, `prominence_of(area) -> float`, `membership_hash(area) -> str`

- [ ] **Step 1: Write the failing test**

```python
"""The catalog's value objects, and the two derivations over them."""

from research_team.domain.course_catalog import (
    membership_hash,
    prominence_of,
)
from research_team.domain.learning_area import AreaMember, LearningArea


def _area(slug: str, *members: tuple[str, float]) -> LearningArea:
    return LearningArea(
        slug=slug,
        members=tuple(
            AreaMember(entity_id=n, name=n, entity_type="person", centrality=c)
            for n, c in members
        ),
    )


def test_prominence_prefers_a_well_connected_area_over_a_merely_large_one():
    """Size and centrality *disagree* here, deliberately.

    An area whose size and centrality agree cannot distinguish this formula
    from `size` alone, and a test built from one representative example would
    pass under both. See CLAUDE.md on formulas correct on every case a test
    naturally reaches.
    """
    big_and_loose = _area("big", *[(f"e{i}", 0.1) for i in range(20)])
    small_and_tight = _area("tight", *[(f"t{i}", 3.0) for i in range(4)])

    assert prominence_of(small_and_tight) > prominence_of(big_and_loose)


def test_prominence_is_zero_for_an_area_with_no_members():
    """Not a crash and not a division by zero: an empty area is a real thing
    a degenerate projection can produce, and it must sort last rather than
    fail the whole catalog."""
    assert prominence_of(LearningArea(slug="empty", members=())) == 0.0


def test_membership_hash_ignores_member_order():
    """The hash answers "is this the same set of entities", so two reads of
    one cluster that happened to order members differently must agree --
    otherwise every request invalidates every blurb."""
    one = _area("a", ("x", 1.0), ("y", 2.0))
    other = _area("a", ("y", 2.0), ("x", 1.0))

    assert membership_hash(one) == membership_hash(other)


def test_membership_hash_changes_when_an_entity_joins():
    grown = _area("a", ("x", 1.0), ("y", 2.0), ("z", 1.0))

    assert membership_hash(_area("a", ("x", 1.0), ("y", 2.0))) != membership_hash(grown)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_course_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'research_team.domain.course_catalog'`

- [ ] **Step 3: Write minimal implementation**

```python
"""What a cluster looks like when it is offered as something to study.

**Nothing here is an aggregate and nothing here is on the event log**, for
`learning_area.py`'s reason, which this module inherits rather than restates: a
candidate is a pure function of a projection that is itself a pure function of
a graph folded from the log. Storing one would store a derivation beside its
own inputs.

The one thing in this feature that *does* earn the log is the featured
override, and it lives in `domain/catalog_curation.py` rather than here --
because it is a person's decision rather than a derivation, and keeping the two
in separate modules is what stops the distinction eroding.
"""

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256

from research_team.domain.learning_area import AreaMember, LearningArea

CategoryKey = str
"""A grouper's answer for one area. A `str` rather than an enum: the grouper is
a port with more than one intended implementation, and an enum here would make
the domain the place every future grouper's vocabulary has to be registered."""


@dataclass(frozen=True)
class ArtRef:
    """Where a card's illustration is, and what it shows.

    A URL and an alt text and nothing else, so increment 3 changes the value
    this carries and not its shape. `alt` is required rather than optional
    because a decorative-only image on a browsing surface is a card a screen
    reader cannot tell from any other card.
    """

    url: str
    alt: str


@dataclass(frozen=True)
class Blurb:
    """Generated copy, and what it was generated from.

    `membership_hash` is the whole reason this is a record rather than a
    string. A blurb written from forty entities that now describes ninety is
    not wrong in any way a reader can see, and this repository has shipped
    silent staleness more than once. Carrying the hash makes "this description
    is N entities behind" a number a card can render.
    """

    text: str
    membership_hash: str
    generated_at: datetime


@dataclass(frozen=True)
class CourseCandidate:
    """One cluster, dressed for browsing.

    `blurb` is `None` for a candidate nothing has written copy for yet, which
    is every candidate on a cold project. That is an ordinary state and not a
    degraded one: the card renders its title, its anchors and its art, and asks
    for copy when someone looks at it.
    """

    slug: str
    title: str
    category: CategoryKey
    prominence: float
    size: int
    anchors: tuple[AreaMember, ...]
    art: ArtRef
    blurb: Blurb | None = None
    featured_rank: int | None = None


@dataclass(frozen=True)
class Category:
    """A group of candidates, with the label a reader sees.

    `key` and `label` are separate because only one of them is checkable. The
    key is what the grouper decided and what a page can justify -- "these are
    grouped because their anchors are `person`" -- where the label is cosmetic
    and may be model-written. Collapsing them would make the justification
    unavailable the moment a label is generated.
    """

    key: CategoryKey
    label: str
    candidates: tuple[CourseCandidate, ...]


@dataclass(frozen=True)
class CatalogSections:
    """The catalog, cut into the three bands a reader's attention has."""

    hero: tuple[CourseCandidate, ...]
    highlights: tuple[CourseCandidate, ...]
    filed: tuple[Category, ...]


def prominence_of(area: LearningArea) -> float:
    """How prominently this area should be offered.

    Size times mean anchor centrality. Centrality is already weighted degree
    *within* the area, which is the correct reading: an entity wired to half
    the project but to nothing in its own area is a bridge, not an anchor, and
    ranking on global degree would promote an area on the strength of a member
    that barely belongs to it.

    **What this measures, stated because it does not go away:** how
    well-connected a cluster is. That is a proxy for "well covered by the
    corpus", not for "worth a learner's time". A hero row driven by this alone
    leads with whatever was ingested most, which is why the featured override
    exists in the same increment rather than a later one.

    Zero for an empty area rather than a `ZeroDivisionError`: a degenerate
    projection can produce one, and it must sort last rather than fail the
    whole catalog.
    """
    if not area.members:
        return 0.0
    mean_centrality = sum(m.centrality for m in area.members) / len(area.members)
    return len(area.members) * mean_centrality


def membership_hash(area: LearningArea) -> str:
    """A stable digest of *which entities* are in this area.

    Sorted before hashing, so two reads of one cluster that ordered members
    differently agree. They otherwise would not, and every request would
    invalidate every blurb -- turning a cache into a per-request model call.

    Deliberately over entity ids only, not over names or centralities. A
    consolidation that renames an entity or shifts a weight has not changed
    what the area is *about*, and regenerating copy for it would churn the
    text under a reader for no gain.
    """
    joined = "\n".join(sorted(m.entity_id for m in area.members))
    return sha256(joined.encode("utf-8")).hexdigest()[:16]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_course_catalog.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add research_team/domain/course_catalog.py tests/domain/test_course_catalog.py
git commit -m "The catalog's value objects, and what prominence actually measures"
```

---

### Task 2: The featured override, on the log

**Files:**
- Create: `research_team/domain/catalog_curation.py`
- Test: `tests/domain/test_catalog_curation.py`

**Interfaces:**
- Produces: `CATALOG_AGGREGATE_TYPE`, `CourseFeatured`, `CourseUnfeatured`

- [ ] **Step 1: Write the failing test**

```python
"""The two curation events, and the one property they have to keep."""

from uuid import uuid4

from research_team.domain.catalog_curation import (
    CATALOG_AGGREGATE_TYPE,
    CourseFeatured,
    CourseUnfeatured,
)


def test_featuring_carries_the_slug_rather_than_a_course_id():
    """A person features a candidate, and most candidates are not realized.

    Keying on a minted course id would make the hero row unusable on a fresh
    project, which is every project before anyone has built a course.
    """
    project = uuid4()
    event = CourseFeatured(aggregate_id=project, project_id=project, slug="warp-drive", rank=0)

    assert event.slug == "warp-drive"
    assert event.rank == 0


def test_both_events_land_on_the_catalog_stream():
    project = uuid4()

    assert CourseFeatured(
        aggregate_id=project, project_id=project, slug="s", rank=1
    ).aggregate_type == CATALOG_AGGREGATE_TYPE
    assert CourseUnfeatured(
        aggregate_id=project, project_id=project, slug="s"
    ).aggregate_type == CATALOG_AGGREGATE_TYPE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/domain/test_catalog_curation.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
"""The one part of the catalog a person decides rather than the graph derives.

Its own module beside `course_catalog.py`, and the split is the point. Every
value object next door is a derivation and must stay recomputable. Featuring is
a *choice*, so it goes on the log -- and keeping the two in separate files is
what stops that distinction eroding the first time somebody wants to cache a
candidate "just like the featured ones".

Appended directly rather than through a `DeciderAggregate`, following
`domain/ontology.py`: these enforce no invariant. Featuring an already-featured
slug is idempotent in effect, and there is no state for a decider to protect.

**Keyed on `slug`, not on a course id.** A person features a *candidate*, and
on a fresh project no candidate has been realized -- a minted id would make the
hero row unusable exactly when it matters most. The cost is real and is handled
on read: a slug is derived from an area's top anchor, so re-clustering can move
it, and a featured slug that names no current area cannot be placed. It is
reported rather than dropped (see `CatalogService.build`), because curation
work that silently disappears is worse than curation work that is visibly
stranded.
"""

from uuid import UUID

from eventsource import DomainEvent, register_event

CATALOG_AGGREGATE_TYPE = "CourseCatalog"
"""The stream these are appended to, named rather than spelled twice.

There is no `CourseCatalog` aggregate to ask for `aggregate_type`, deliberately
-- see the module docstring -- so this constant stands in for the class
attribute the way `ONTOLOGY_AGGREGATE_TYPE` does, and the feed-coverage guard
has something to name that cannot drift from the events' own default.
"""


@register_event
class CourseFeatured(DomainEvent):
    """Somebody put this candidate on the front page.

    `rank` orders the hero row among featured candidates. Ties are broken on
    slug when they occur, which they will: nothing stops two candidates being
    featured at the same rank, and refusing that would mean this event
    enforcing an invariant it has no aggregate to enforce it with.
    """

    aggregate_type: str = CATALOG_AGGREGATE_TYPE
    project_id: UUID
    slug: str
    rank: int = 0


@register_event
class CourseUnfeatured(DomainEvent):
    """Somebody took this candidate off the front page.

    Unfeaturing a slug that was never featured is appended rather than refused,
    for this module's no-invariant reason: the projection treats it as a
    delete, and a delete of nothing is nothing.
    """

    aggregate_type: str = CATALOG_AGGREGATE_TYPE
    project_id: UUID
    slug: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/domain/test_catalog_curation.py -v`
Expected: 2 passed

- [ ] **Step 5: Add the schema-evolution case**

`domain/events.py` opens with the supported evolution cases and
`tests/infrastructure/test_schema_evolution.py` enforces them. Add one case
that writes a `CourseFeatured` payload **without** `rank` and reads it back,
asserting it defaults to 0 — that is what a payload written before `rank`
existed would look like, and the default is what makes it loadable.

- [ ] **Step 6: Run the evolution suite**

Run: `uv run pytest tests/infrastructure/test_schema_evolution.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add research_team/domain/catalog_curation.py tests/domain/test_catalog_curation.py tests/infrastructure/test_schema_evolution.py
git commit -m "Featuring is a decision, so it goes on the log"
```

---

### Task 3: The featured read model and its projection

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` (add `CatalogFeatureRow`,
  `CatalogFeatureStore`, `CatalogFeatureProjection` beside `OntologyProjection`)
- Test: `tests/infrastructure/test_catalog_features.py`

**Interfaces:**
- Consumes: `CourseFeatured`, `CourseUnfeatured` (Task 2)
- Produces: `CatalogFeatureStore.open(db_path)`, `.featured_for(project_id) -> dict[str, int]`

- [ ] **Step 1: Write the failing test**

```python
"""The featured projection, over a real store rather than a fake.

Every assertion is on *rows*, never on "no exception was raised": an event no
projection handles counts as applied, so a build with this projection
unregistered serves an empty hero row and a 200. See CLAUDE.md under *Events*.
"""

from uuid import uuid4

import pytest

from research_team.domain.catalog_curation import CourseFeatured, CourseUnfeatured
from research_team.infrastructure.persistence.read_models import (
    CatalogFeatureProjection,
    CatalogFeatureStore,
)


@pytest.fixture
async def store(db_path):
    opened = await CatalogFeatureStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def test_a_featured_slug_is_readable_with_its_rank(store):
    project = uuid4()
    projection = CatalogFeatureProjection(store)

    await projection.handle(
        CourseFeatured(aggregate_id=project, project_id=project, slug="warp", rank=2)
    )

    assert await store.featured_for(project) == {"warp": 2}


async def test_unfeaturing_removes_it(store):
    project = uuid4()
    projection = CatalogFeatureProjection(store)
    await projection.handle(
        CourseFeatured(aggregate_id=project, project_id=project, slug="warp", rank=2)
    )

    await projection.handle(
        CourseUnfeatured(aggregate_id=project, project_id=project, slug="warp")
    )

    assert await store.featured_for(project) == {}


async def test_featuring_the_same_slug_again_moves_its_rank_rather_than_duplicating(store):
    """Idempotent by row id, which is what lets the route be a plain POST with
    no read-modify-write and no version check."""
    project = uuid4()
    projection = CatalogFeatureProjection(store)
    await projection.handle(
        CourseFeatured(aggregate_id=project, project_id=project, slug="warp", rank=2)
    )

    await projection.handle(
        CourseFeatured(aggregate_id=project, project_id=project, slug="warp", rank=0)
    )

    assert await store.featured_for(project) == {"warp": 0}


async def test_one_projects_features_are_invisible_to_another(store):
    mine, theirs = uuid4(), uuid4()
    projection = CatalogFeatureProjection(store)
    await projection.handle(
        CourseFeatured(aggregate_id=mine, project_id=mine, slug="warp", rank=0)
    )

    assert await store.featured_for(theirs) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_catalog_features.py -v`
Expected: FAIL — `ImportError: cannot import name 'CatalogFeatureStore'`

- [ ] **Step 3: Write minimal implementation**

Add beside `OntologyClassRow` and its store, following `EntityDefinitionStore.open`
exactly — including the project index, because every read here is project-scoped
and an unindexed table puts one project's reads behind a scan of every other's.

```python
class CatalogFeatureRow(ReadModel):
    """One candidate somebody put on the front page.

    Keyed by `(project_id, slug)` through `row_id`, so featuring the same slug
    twice moves its rank rather than adding a second row. That idempotence is
    what lets the route be a plain POST with no read-modify-write.
    """

    __table_name__ = "catalog_features"

    project_id: UUID
    slug: str
    rank: int = 0

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        return uuid5(CATALOG_NAMESPACE, f"{project_id}:{slug}")


class CatalogFeatureStore:
    """The featured table and the connection it uses."""

    def __init__(self, connection: aiosqlite.Connection, rows: ReadModelRepository) -> None:
        self._connection = connection
        self._rows = rows

    @classmethod
    async def open(cls, db_path: str, tracer=None) -> "CatalogFeatureStore":
        connection = await aiosqlite.connect(db_path)
        await apply_schema(connection, CatalogFeatureRow)
        # `apply_schema` reconciles columns, not indexes -- the same note
        # `EntityDefinitionStore.open` carries, for the same reason: every read
        # here is project-scoped.
        await connection.execute(
            f"CREATE INDEX IF NOT EXISTS idx_catalog_features_project "
            f"ON {CatalogFeatureRow.table_name()}(project_id)"
        )
        await connection.commit()
        rows = SQLiteReadModelRepository(connection, CatalogFeatureRow, tracer)
        return cls(connection, rows)

    async def feature(self, project_id: UUID, slug: str, rank: int) -> None:
        await self._rows.save(
            CatalogFeatureRow(
                id=CatalogFeatureRow.row_id(project_id, slug),
                project_id=project_id,
                slug=slug,
                rank=rank,
            )
        )

    async def unfeature(self, project_id: UUID, slug: str) -> None:
        """Deleting something absent is a no-op, not an error.

        This is driven by a projection over a log that may hold an unfeature
        for a slug whose feature was never projected -- a rebuild from an
        arbitrary checkpoint does exactly that -- and raising here would put a
        routine replay in the dead-letter queue.
        """
        await self._rows.delete(CatalogFeatureRow.row_id(project_id, slug))

    async def featured_for(self, project_id: UUID) -> dict[str, int]:
        cursor = await self._connection.execute(
            f"SELECT slug, rank FROM {CatalogFeatureRow.table_name()} "
            "WHERE project_id = ? AND deleted_at IS NULL",
            (str(project_id),),
        )
        try:
            return {row[0]: row[1] for row in await cursor.fetchall()}
        finally:
            await cursor.close()

    async def close(self) -> None:
        await self._connection.close()


class CatalogFeatureProjection(DeclarativeProjection):
    """Keeps `catalog_features` level with the curation events."""

    def __init__(self, store: CatalogFeatureStore) -> None:
        self._store = store

    @handles(CourseFeatured)
    async def _featured(self, event: CourseFeatured) -> None:
        await self._store.feature(event.project_id, event.slug, event.rank)

    @handles(CourseUnfeatured)
    async def _unfeatured(self, event: CourseUnfeatured) -> None:
        await self._store.unfeature(event.project_id, event.slug)
```

Add `CATALOG_NAMESPACE = uuid5(NAMESPACE_URL, "research-team/catalog")` beside the
other namespace constants in that module.

Match the `@handles` decorator and `DeclarativeProjection` base to whatever
`OntologyProjection` in the same file uses — copy its form rather than the form
written here if they differ.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_catalog_features.py -v`
Expected: 4 passed

- [ ] **Step 5: Prove the projection test is not vacuous**

Comment out the `@handles(CourseFeatured)` decorator and re-run. Expected: the
first three tests FAIL. This is the check that matters — with the decorator
gone the projection silently does nothing and every "did it throw" assertion
would still pass. Restore the decorator by re-editing the file, **not** by
`git checkout`, which would discard the rest of your uncommitted work in it.

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/persistence/read_models.py tests/infrastructure/test_catalog_features.py
git commit -m "The featured table, and a projection test that fails when the projection stops"
```

---

### Task 4: The blurb cache

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` (add `CourseBlurbRow`,
  `CourseBlurbStore`)
- Test: `tests/infrastructure/test_course_blurbs.py`

**Interfaces:**
- Produces: `CourseBlurbStore.open(db_path)`, `.get(project_id, slug) -> CourseBlurbRow | None`,
  `.put(project_id, slug, text, membership_hash, model, generated_at)`

- [ ] **Step 1: Write the failing test**

```python
"""The blurb cache. A cache, not a projection -- nothing writes it from the log."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from research_team.infrastructure.persistence.read_models import CourseBlurbStore


@pytest.fixture
async def store(db_path):
    opened = await CourseBlurbStore.open(db_path)
    try:
        yield opened
    finally:
        await opened.close()


async def test_a_stored_blurb_reads_back_with_the_hash_it_was_written_from(store):
    """The hash is the point of the row. Without it a blurb describing a
    cluster that has since doubled is indistinguishable from a current one."""
    project = uuid4()
    await store.put(
        project, "warp", "Learn about warp drive.", "abc123", "m", datetime.now(UTC)
    )

    row = await store.get(project, "warp")

    assert row is not None
    assert row.text == "Learn about warp drive."
    assert row.membership_hash == "abc123"


async def test_rewriting_a_slug_replaces_rather_than_duplicates(store):
    project = uuid4()
    await store.put(project, "warp", "First.", "abc123", "m", datetime.now(UTC))

    await store.put(project, "warp", "Second.", "def456", "m", datetime.now(UTC))

    row = await store.get(project, "warp")
    assert row is not None
    assert row.text == "Second."
    assert row.membership_hash == "def456"


async def test_an_unwritten_slug_is_none_rather_than_an_error(store):
    """`None` is an ordinary answer: every candidate on a cold project has no
    blurb, and the card renders without one."""
    assert await store.get(uuid4(), "never-written") is None


async def test_one_projects_blurbs_are_invisible_to_another(store):
    mine, theirs = uuid4(), uuid4()
    await store.put(mine, "warp", "Mine.", "abc", "m", datetime.now(UTC))

    assert await store.get(theirs, "warp") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_course_blurbs.py -v`
Expected: FAIL — `ImportError: cannot import name 'CourseBlurbStore'`

- [ ] **Step 3: Write minimal implementation**

Mirror `EntityDefinitionRow`/`EntityDefinitionStore` in the same file, including
the project index. Row fields:

```python
class CourseBlurbRow(ReadModel):
    """One generated blurb, cached against the cluster it describes.

    A cache and not a projection's own state, exactly like
    `EntityDefinitionRow`: the catalog service's `put` is the only writer.

    Unlike that row there is no `stale` flag, and the difference is
    deliberate. A definition is invalidated by graph events this table never
    reads, so it needs a flag something else can set. A blurb carries
    `membership_hash`, which answers the same question *by comparison* -- the
    caller already holds the current hash and can see the disagreement itself.
    A flag would be a second answer to one question, and the two would drift.
    """

    __table_name__ = "course_blurbs"

    project_id: UUID
    slug: str
    text: str
    membership_hash: str
    model: str
    generated_at: str

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        return uuid5(CATALOG_NAMESPACE, f"blurb:{project_id}:{slug}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_course_blurbs.py -v`
Expected: 4 passed

- [ ] **Step 5: Verify against a database that predates the change**

A read-model change verified only against a fresh database is unverified.

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/probe.db
```

Then open `CourseBlurbStore` against `/tmp/probe.db` in a REPL and call `get`.
Expected: `None`, not an `OperationalError` about a missing table.

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/persistence/read_models.py tests/infrastructure/test_course_blurbs.py
git commit -m "The blurb cache, keyed on the membership it was written from"
```

---

### Task 5: The category grouper port and its one implementation

**Files:**
- Create: `research_team/application/course_catalog.py` (ports only in this task)
- Create: `research_team/infrastructure/knowledge/type_plurality_grouper.py`
- Test: `tests/infrastructure/test_type_plurality_grouper.py`

**Interfaces:**
- Consumes: `LearningArea`, `CategoryKey`
- Produces: `CategoryGrouper` protocol with `group(areas) -> Mapping[str, CategoryKey]`;
  `TypePluralityGrouper`; `CATEGORY_LABELS: Mapping[CategoryKey, str]`

- [ ] **Step 1: Write the failing test**

```python
"""Grouping areas by what their anchors are, over areas shaped like real ones."""

from research_team.domain.learning_area import AreaMember, LearningArea
from research_team.infrastructure.knowledge.type_plurality_grouper import (
    TypePluralityGrouper,
)


def _area(slug: str, *types: str) -> LearningArea:
    return LearningArea(
        slug=slug,
        members=tuple(
            AreaMember(
                entity_id=f"{slug}-{i}",
                name=f"{slug}-{i}",
                entity_type=t,
                centrality=float(len(types) - i),
            )
            for i, t in enumerate(types)
        ),
    )


def test_an_area_is_grouped_by_the_commonest_type_among_its_anchors():
    grouper = TypePluralityGrouper()

    grouped = grouper.group([_area("crew", "person", "person", "work")])

    assert grouped["crew"] == "person"


def test_a_tie_breaks_on_the_type_of_the_most_central_anchor():
    """Ties are routine -- an area of two people and two works is ordinary --
    and an arbitrary tiebreak would move a card between categories on reruns
    over an unchanged graph. Anchors are already ranked by centrality, so the
    top one decides."""
    grouper = TypePluralityGrouper()

    grouped = grouper.group([_area("mixed", "work", "person")])

    # `work` is first, so it has the higher centrality in `_area`.
    assert grouped["mixed"] == "work"


def test_an_area_with_no_members_gets_the_unclassified_key_rather_than_crashing():
    grouper = TypePluralityGrouper()

    grouped = grouper.group([LearningArea(slug="empty", members=())])

    assert grouped["empty"] == "unclassified"


def test_every_area_handed_in_comes_back_out():
    """A grouper that silently dropped an area would delete courses from the
    catalog, and the catalog would still render."""
    grouper = TypePluralityGrouper()

    grouped = grouper.group([_area("a", "person"), _area("b", "work"), _area("c", "location")])

    assert set(grouped) == {"a", "b", "c"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_type_plurality_grouper.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the port**

In `research_team/application/course_catalog.py`:

```python
class CategoryGrouper(Protocol):
    """Decides which category each area belongs to.

    A port with one implementation today and a known better one waiting. The
    ontology is the better source and is not ready: measured 2026-08-23, the
    ontology tables were empty and `ontology_examined` was 0, so the pass had
    never read a document. Even populated, this corpus's own grouping edges are
    weak -- 470 `is_a`/`member_of` edges over 234 targets whose commonest values
    are `Star Trek`, `The Original Series`, `Rotten Tomatoes` and `Variety`.
    Grouping on those today produces a "Rotten Tomatoes" category.

    So this exists so the ontology can replace the implementation without the
    browser changing. Per CLAUDE.md, a port with exactly one production adapter
    needs a test driving *both ends over real data* -- see
    `test_a_catalog_over_a_real_ingest_has_cards_in_more_than_one_category`.
    """

    def group(self, areas: Sequence[LearningArea]) -> Mapping[str, CategoryKey]:
        """Every area's slug mapped to its category. Total: an area that comes
        in must come out, or the catalog silently loses courses."""
        ...
```

- [ ] **Step 4: Write the implementation**

```python
"""Grouping areas by the commonest entity type among their anchors.

**Why this and not the ontology**, which is the obvious source: see
`CategoryGrouper`. The short version is that the ontology tables were empty
when this was written and the graph's own `is_a` edges point mostly at
franchises and review aggregators.

**What this cannot do**, written down so nobody rediscovers it: it cannot
separate races from enemies. Both are `organization` or `concept`. That
distinction needs the ontology or a model, and it is the reason `CategoryGrouper`
is a port rather than this function.
"""

from collections import Counter
from collections.abc import Mapping, Sequence

from research_team.domain.course_catalog import CategoryKey
from research_team.domain.learning_area import LearningArea

UNCLASSIFIED: CategoryKey = "unclassified"

CATEGORY_LABELS: Mapping[CategoryKey, str] = {
    "person": "People",
    "work": "Works & Media",
    "location": "Places",
    "organization": "Organisations",
    "event": "Events",
    "concept": "Ideas",
    "category": "Classifications",
    UNCLASSIFIED: "Unclassified",
}
"""Display labels for the keys this grouper emits.

A fixed table rather than generated copy, in this increment. A generated label
is increment 2's problem; a table is honest, checkable, and cannot describe a
category as something it is not. An unlisted key falls back to the key itself,
which is ugly and correct -- a made-up label would be neither.
"""


class TypePluralityGrouper:
    """The `CategoryGrouper` over anchor entity types."""

    def group(self, areas: Sequence[LearningArea]) -> Mapping[str, CategoryKey]:
        return {area.slug: self._key_for(area) for area in areas}

    @staticmethod
    def _key_for(area: LearningArea) -> CategoryKey:
        anchors = area.anchors
        if not anchors:
            return UNCLASSIFIED
        counts = Counter(m.entity_type for m in anchors)
        best = max(counts.values())
        tied = {t for t, n in counts.items() if n == best}
        if len(tied) == 1:
            return next(iter(tied))
        # Ties are routine -- two people and two works is an ordinary area --
        # and an arbitrary tiebreak would move a card between categories on
        # reruns over an unchanged graph. `anchors` is already ranked by
        # centrality with a deterministic id tiebreak, so the top one decides.
        return next(m.entity_type for m in anchors if m.entity_type in tied)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_type_plurality_grouper.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add research_team/application/course_catalog.py research_team/infrastructure/knowledge/type_plurality_grouper.py tests/infrastructure/test_type_plurality_grouper.py
git commit -m "Categories come from anchor types, behind a port the ontology can take over"
```

---

### Task 6: Placeholder art

**Files:**
- Create: `research_team/infrastructure/knowledge/seeded_art.py`
- Modify: `research_team/application/course_catalog.py` (add `ArtPort`)
- Test: `tests/infrastructure/test_seeded_art.py`

**Interfaces:**
- Produces: `ArtPort` protocol with `for_candidate(slug, category) -> ArtRef`;
  `SeededArtProvider`

- [ ] **Step 1: Write the failing test**

```python
"""Deterministic placeholder art. Increment 3 replaces the implementation."""

from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider


def test_the_same_slug_gets_the_same_art_every_time():
    """Stable across runs, because a catalog whose illustrations reshuffle on
    every request is a catalog nobody can recognise a card in."""
    provider = SeededArtProvider()

    assert provider.for_candidate("warp", "work") == provider.for_candidate("warp", "work")


def test_different_slugs_get_different_art():
    provider = SeededArtProvider()

    assert provider.for_candidate("warp", "work") != provider.for_candidate("vulcan", "work")


def test_the_alt_text_names_the_candidate_rather_than_describing_decoration():
    """A browsing surface where every image is "decorative" is a surface a
    screen reader cannot tell one card from another in."""
    art = SeededArtProvider().for_candidate("warp-drive", "work")

    assert "warp-drive" in art.alt.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_seeded_art.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

Emit a `data:` URI holding a small SVG whose hue and shape are derived from
`sha256(slug)`. It must be **stable** and **distinct per slug**, and it must not
look broken — a catalog of grey rectangles is not browsable, and browsability is
this increment's entire point. Category selects the palette so a category page
reads as one family.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_seeded_art.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/knowledge/seeded_art.py research_team/application/course_catalog.py tests/infrastructure/test_seeded_art.py
git commit -m "Placeholder art that is stable, distinct, and not embarrassing"
```

---

### Task 7: The blurb writer, and its one refusal

**Files:**
- Create: `research_team/infrastructure/knowledge/blurb_writer.py`
- Modify: `research_team/application/course_catalog.py` (add `BlurbTextPort`, `BlurbCachePort`)
- Test: `tests/infrastructure/test_blurb_writer.py`

**Interfaces:**
- Produces: `BlurbTextPort.write(title, anchors) -> str | None`; `ModelBlurbWriter(model)`

- [ ] **Step 1: Write the failing test**

```python
"""Blurb generation, and the check that keeps it inside the corpus."""

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from research_team.domain.learning_area import AreaMember
from research_team.infrastructure.knowledge.blurb_writer import ModelBlurbWriter

ANCHORS = (
    AreaMember(entity_id="1", name="Warp drive", entity_type="concept", centrality=3.0),
    AreaMember(entity_id="2", name="Zefram Cochrane", entity_type="person", centrality=2.0),
)


def _writer(text: str) -> ModelBlurbWriter:
    return ModelBlurbWriter(FakeMessagesListChatModel(responses=[AIMessage(content=text)]))


async def test_a_blurb_built_from_the_anchors_is_returned():
    writer = _writer("Follow Zefram Cochrane and the Warp drive that changed everything.")

    assert await writer.write("Warp drive", ANCHORS) is not None


async def test_a_blurb_naming_an_entity_the_cluster_does_not_hold_is_refused():
    """The one check available without spans.

    A model asked to write about warp drive will happily bring in Kirk from
    what it read years ago, and that copy is indistinguishable at a glance from
    copy derived from this cluster -- which is exactly why a reader would trust
    it. A blurb that names an entity the corpus did not put in this area
    promises a course the corpus cannot teach.

    Weaker than the citation check `entity_definitions` runs, and recorded as
    weaker rather than presented as equivalent.
    """
    writer = _writer("Join Captain Kirk as he explores the Warp drive.")

    assert await writer.write("Warp drive", ANCHORS) is None


async def test_an_empty_reply_is_refused_rather_than_stored_as_an_empty_blurb():
    assert await _writer("   ").write("Warp drive", ANCHORS) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/infrastructure/test_blurb_writer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

The prompt names the title and up to 12 anchors (matching
`course_authoring.PROMPT_ANCHORS`, and for its reason: an area with sixty
members does not become a better course by listing all sixty). Ask for two
sentences of catalog copy.

The check: extract capitalised runs from the reply; every one must appear in
some anchor name, case-insensitively. Sentence-initial words are exempt —
otherwise every sentence's first word is a false positive. Refuse on any
unmatched run, and refuse on empty or whitespace-only replies.

Record in the docstring that the check is **deliberately conservative in the
refusing direction**: a refused blurb costs a card its copy, where an accepted
ungrounded one costs a reader their trust, and only one of those is recoverable
by clicking again.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_blurb_writer.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/knowledge/blurb_writer.py research_team/application/course_catalog.py tests/infrastructure/test_blurb_writer.py
git commit -m "Blurbs may only name what the cluster holds"
```

---

### Task 8: `CatalogService`

**Files:**
- Modify: `research_team/application/course_catalog.py` (add `CatalogService`, `Catalog`)
- Test: `tests/application/test_course_catalog.py`

**Interfaces:**
- Consumes: `Curriculum` (`application/curriculum.py`), `CategoryGrouper`, `ArtPort`,
  `BlurbCachePort`, `prominence_of`, `membership_hash`
- Produces: `Catalog(sections, categories, unplaceable_featured, derived_from)`;
  `CatalogService.build(project_id, curriculum, featured) -> Catalog`

- [ ] **Step 1: Write the failing test**

```python
"""Assembling a catalog from a curriculum, a grouper and the featured set."""

from uuid import uuid4

from research_team.application.course_catalog import CatalogService
from research_team.domain.learning_area import AreaMember, AreaProjection, LearningArea, LearningPath
from research_team.application.curriculum import Curriculum
from research_team.infrastructure.knowledge.seeded_art import SeededArtProvider
from research_team.infrastructure.knowledge.type_plurality_grouper import TypePluralityGrouper


class _NoBlurbs:
    async def get(self, project_id, slug):
        return None


def _area(slug: str, size: int, centrality: float, kind: str = "person") -> LearningArea:
    return LearningArea(
        slug=slug,
        members=tuple(
            AreaMember(
                entity_id=f"{slug}-{i}", name=f"{slug} {i}",
                entity_type=kind, centrality=centrality,
            )
            for i in range(size)
        ),
    )


def _curriculum(*areas: LearningArea) -> Curriculum:
    return Curriculum(
        projection=AreaProjection(
            areas=areas, entity_count=sum(a.size for a in areas),
            relationship_count=0, co_mention_count=0,
        ),
        path=LearningPath(slug="all", title="All", area_slugs=tuple(a.slug for a in areas), edges=()),
    )


def _service() -> CatalogService:
    return CatalogService(
        grouper=TypePluralityGrouper(), art=SeededArtProvider(), blurbs=_NoBlurbs()
    )


async def test_the_hero_leads_with_the_most_prominent_candidate():
    catalog = await _service().build(
        uuid4(), _curriculum(_area("small", 2, 1.0), _area("big", 20, 5.0)), featured={}
    )

    assert catalog.sections.hero[0].slug == "big"


async def test_a_featured_candidate_outranks_a_more_prominent_one():
    """The whole reason the override is in this increment: the derived score
    measures corpus coverage, not worth."""
    catalog = await _service().build(
        uuid4(),
        _curriculum(_area("small", 2, 1.0), _area("big", 20, 5.0)),
        featured={"small": 0},
    )

    assert catalog.sections.hero[0].slug == "small"


async def test_a_featured_slug_that_names_no_area_is_reported_not_dropped():
    """Re-clustering moves slugs. Curation work that silently disappears is
    worse than curation work that is visibly stranded."""
    catalog = await _service().build(
        uuid4(), _curriculum(_area("big", 20, 5.0)), featured={"gone": 0}
    )

    assert catalog.unplaceable_featured == ("gone",)


async def test_every_area_reaches_exactly_one_section():
    """A candidate that fell out of all three sections would vanish from the
    catalog and the catalog would still render."""
    areas = [_area(f"a{i}", i + 1, 1.0) for i in range(12)]
    catalog = await _service().build(uuid4(), _curriculum(*areas), featured={})

    placed = (
        [c.slug for c in catalog.sections.hero]
        + [c.slug for c in catalog.sections.highlights]
        + [c.slug for cat in catalog.sections.filed for c in cat.candidates]
    )
    assert sorted(placed) == sorted(a.slug for a in areas)
    assert len(placed) == len(set(placed))


async def test_areas_of_different_anchor_types_land_in_different_categories():
    catalog = await _service().build(
        uuid4(),
        _curriculum(_area("people", 5, 2.0, "person"), _area("shows", 5, 2.0, "work")),
        featured={},
    )

    assert {c.key for c in catalog.sections.filed} >= {"person", "work"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/application/test_course_catalog.py -v`
Expected: FAIL — `ImportError: cannot import name 'CatalogService'`

- [ ] **Step 3: Write minimal implementation**

`build` takes the already-built `Curriculum` rather than the ports that make one:
`CurriculumService` already caches per graph counts, and rebuilding here would
run a clustering pass per catalog view. Section cut points are module constants
with stated defaults (`HERO = 5`, `HIGHLIGHTS = 8`) and a comment saying they are
layout choices rather than findings.

Ordering: featured first by `rank` then slug; the remainder by `prominence`
descending then slug. **Slug is the tiebreak everywhere** — two candidates of
equal prominence must order the same way on every run, or cards move between
sections on reruns over an unchanged graph.

`unplaceable_featured` is the sorted tuple of featured slugs matching no area.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/application/test_course_catalog.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add research_team/application/course_catalog.py tests/application/test_course_catalog.py
git commit -m "Assembling a catalog, with the featured override on top of the derived order"
```

---

### Task 9: Routes and presenter

**Files:**
- Modify: `research_team/interfaces/web/app.py` (four routes; `create_app` gains
  `catalog`, `catalog_features`, `blurbs`)
- Modify: `research_team/interfaces/web/presenters.py` (add `catalog_view`)
- Modify: `web.py` (pass the three new dependencies)
- Test: `tests/interfaces/test_catalog_routes.py`

**Interfaces:**
- Consumes: `CatalogService.build`, `CatalogFeatureStore.featured_for`
- Produces: `GET /api/projects/{id}/catalog`, `GET .../catalog/categories/{key}`,
  `POST .../catalog/{slug}/feature`, `POST .../catalog/{slug}/unfeature`

- [ ] **Step 1: Write the failing test**

```python
"""The catalog routes, composed rather than faked.

Composed for `test_ontology_routes.py`'s reason: a build that never constructs
a `CatalogService` answers `GET .../catalog` with empty sections and no error,
and a fixture handing the route a hand-built service cannot tell that build
from a working one. Every assertion here is on the payload's contents.
"""
```

Assertions to write:
- `GET /catalog` on a project with a real graph returns **non-empty** `hero`
  and at least one category. Not a 200 — the count is the assertion.
- `GET /catalog` returns **503** when `catalog` is not passed to `create_app`.
- `POST /catalog/{slug}/feature` then `GET /catalog` puts that slug first in
  `hero`. Await the projection's `caught_up()` between them.
- `POST /catalog/{slug}/unfeature` restores the derived order.
- `GET /catalog/categories/{unknown}` is **404**, not an empty category.
- `GET /catalog` on an unknown project is **404**.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/interfaces/test_catalog_routes.py -v`
Expected: FAIL — 404 on every route

- [ ] **Step 3: Write the routes**

`GET /catalog` resolves the curriculum through the existing `_curriculum(project_id)`
helper — reusing its 503-when-unwired and 422-on-`GraphTooLarge` behaviour rather
than repeating either.

**503 when `catalog` or `catalog_features` is None**, never empty sections. An
empty catalog is correct for a project with no graph, so an unwired build
answering the same thing is indistinguishable from an empty one.

**Register the literal-segment routes above any `{slug}` route in the same
prefix.** `app.py` records this exact bug happening twice: a literal like
`categories` gets read as a `{slug}` by the parameterised route registered
above it.

Add `catalog_view` to `presenters.py`, carrying `derived_from` (the projection's
counts) exactly as `curriculum_view` does — for that function's stated reason: a
catalog over 40 entities and one over 4,000 render identically otherwise.
Include `unplaceableFeatured` in the payload.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/interfaces/test_catalog_routes.py -v`
Expected: all pass

- [ ] **Step 5: Add the entrypoint guard**

`tests/interfaces/test_web_entrypoint.py` exists because routes added to
`create_app` and not to `web.py`'s call have shipped 503ing three times. Add a
case covering the three new dependencies.

- [ ] **Step 6: Run the entrypoint suite**

Run: `uv run pytest tests/interfaces/test_web_entrypoint.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add research_team/interfaces/web/app.py research_team/interfaces/web/presenters.py web.py tests/interfaces/
git commit -m "The catalog routes, and the entrypoint guard that stops them 503ing"
```

---

### Task 10: Composition wiring, and the both-ends test

**Files:**
- Modify: `research_team/composition.py`
- Test: `tests/test_catalog_wiring.py`

**Interfaces:**
- Produces: `Application.catalog`, `Application.catalog_features`, `Application.blurbs`

- [ ] **Step 1: Write the failing test**

```python
"""The test CLAUDE.md asks for: both ends of every port, over real data.

A stub on one side and a unit test on the other proves the halves work and
cannot prove they meet. The co-mention channel shipped exactly that way and
produced nothing for a whole feature, with every piece tested.
"""


async def test_a_catalog_over_a_real_ingest_has_cards_in_more_than_one_category():
    """Drives a real ingest through a composed application and asserts on the
    catalog's *contents*.

    The category count is the assertion that matters. With the grouper
    unwired every candidate lands in one bucket and the catalog still renders
    -- so `>= 2` is what separates a working grouper from a silent default.
    """
```

Build an application over two small documents whose entities are of clearly
different types, extract them, build the catalog, and assert: non-zero
candidates, non-empty anchors on the first, and **at least two distinct
category keys**.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_catalog_wiring.py -v`
Expected: FAIL — `Application` has no `catalog`

- [ ] **Step 3: Wire it**

Follow `definition_invalidation` in `composition.py` — including registering
`CatalogFeatureProjection` with the projection set, and `start()`/`caught_up()`/
`stop()` in the three lifecycle methods. `EntityDefinitionRunner`'s absence once
shipped a fully green suite; the comment at `composition.py:1215` says so.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_catalog_wiring.py -v`
Expected: PASS

- [ ] **Step 5: Prove it catches the unwiring**

Remove `CatalogFeatureProjection` from the projection set and re-run. Expected:
the featuring route test in Task 9 FAILS. Restore by re-editing, not by
`git checkout`.

- [ ] **Step 6: Commit**

```bash
git add research_team/composition.py tests/test_catalog_wiring.py
git commit -m "Catalog wiring, proved by a test that fails when the projection is dropped"
```

---

### Task 11: Frontend domain, port and repository

**Files:**
- Create: `frontend/src/domain/knowledge/catalog.ts`
- Modify: `frontend/src/infrastructure/http/dto.ts`
- Create: `frontend/src/infrastructure/http/catalog-repository.ts`
- Modify: `frontend/src/application/ports/repositories.ts`
- Modify: `frontend/src/application/queries/keys.ts`
- Modify: `frontend/src/app/container.ts`
- Test: `frontend/src/domain/knowledge/catalog.test.ts`

**Interfaces:**
- Produces: `CourseCandidate`, `Category`, `Catalog` types; `CatalogRepository` with
  `catalog(projectId)`, `feature(projectId, slug, rank)`, `unfeature(projectId, slug)`;
  `queryKeys.catalog(project)`

- [ ] **Step 1: Write the failing test**

```typescript
import { describe, expect, it } from 'vitest'

import { blurbAge, type CourseCandidate } from './catalog.ts'

const candidate = (over: Partial<CourseCandidate> = {}): CourseCandidate => ({
  slug: 'warp',
  title: 'Warp drive',
  category: 'concept',
  prominence: 12,
  size: 8,
  anchors: [],
  art: { url: 'data:image/svg+xml,x', alt: 'Warp drive' },
  blurb: null,
  featuredRank: null,
  ...over,
})

describe('blurbAge', () => {
  it('reports no age when the blurb was written from the current membership', () => {
    expect(
      blurbAge(candidate({ blurb: { text: 'x', membershipHash: 'abc', generatedAt: 'now' } }), 'abc'),
    ).toBe(null)
  })

  it('reports staleness when the membership has moved since', () => {
    // The number this repo has shipped without twice. A blurb describing a
    // cluster that has since doubled is not wrong in any way a reader sees.
    expect(
      blurbAge(candidate({ blurb: { text: 'x', membershipHash: 'old', generatedAt: 'then' } }), 'new'),
    ).toBe('stale')
  })

  it('reports nothing for a candidate with no blurb at all', () => {
    // An ordinary state, not a degraded one: every candidate on a cold project
    // has no copy yet.
    expect(blurbAge(candidate(), 'abc')).toBe(null)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/domain/knowledge/catalog.test.ts`
Expected: FAIL — module not found

- [ ] **Step 3: Implement types, dto, repository, port, keys, container**

Mirror `ontology-repository.ts` and `curriculum-repository.ts` exactly. The DTO
defaults arrays, matching `ungroupedSourcesDto`'s note: an empty catalog is a
real answer and the server distinguishes an unwired build with a 503.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd frontend && npx vitest run src/domain/knowledge/catalog.test.ts`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/domain/knowledge/catalog.ts frontend/src/infrastructure/http/ frontend/src/application/ frontend/src/app/container.ts
git commit -m "The catalog's client types, and the staleness a card can render"
```

---

### Task 12: `CourseCard`

**Files:**
- Create: `frontend/src/presentation/curriculum/CourseCard.tsx`
- Test: `frontend/src/presentation/curriculum/CourseCard.test.tsx`
- Test: `frontend/src/presentation/curriculum/course-card-sizing.browser.test.tsx`

**Interfaces:**
- Consumes: `CourseCandidate` (Task 11)
- Produces: `CourseCard({ candidate, size, onOpen })` where `size` is
  `'hero' | 'highlight' | 'filed'`

- [ ] **Step 1: Write the failing jsdom test**

Cover, in `*.test.tsx` (roles, text, keyboard — things jsdom can judge):
- the title renders
- the art's `alt` is the candidate's, not empty
- a candidate with no blurb renders without one and does **not** render an
  empty paragraph
- a stale blurb renders its staleness note
- a featured candidate is marked as such to a screen reader, not only by colour
- clicking calls `onOpen` with the slug

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/curriculum/CourseCard.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement `CourseCard`**

Three sizes. **`border-0` before any directional width**; never `border-0`
beside a plain `border`. If an inward focus ring is wanted, use the
`.lay-ring-inward` class from `layout.css` — a `focus-visible:outline-offset-*`
utility loses to the unlayered `:focus-visible` rule in `tokens.css`, silently,
and no gate catches it.

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/presentation/curriculum/CourseCard.test.tsx`
Expected: all pass

- [ ] **Step 5: Write the browser test for sizing**

```typescript
/** Card size is a computed style, so this cannot live in jsdom -- which lays
 *  nothing out and would report all three sizes identical. */
```

Render all three sizes and assert the hero's measured width is greater than the
highlight's, which is greater than the filed one's. Measured, not asserted from
class names: a class in the attribute proves nothing about what the cascade did
with it.

- [ ] **Step 6: Run the browser suite**

Run: `cd frontend && npm run test:browser`
Expected: PASS. Run it alone — never two vitest processes at once.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/presentation/curriculum/CourseCard.tsx frontend/src/presentation/curriculum/CourseCard.test.tsx frontend/src/presentation/curriculum/course-card-sizing.browser.test.tsx
git commit -m "The card, in three sizes, with the sizing measured rather than asserted"
```

---

### Task 13: `CatalogPane`, the facet, and the category page

**Files:**
- Create: `frontend/src/presentation/curriculum/CatalogPane.tsx`
- Create: `frontend/src/presentation/curriculum/CategoryPage.tsx`
- Modify: `frontend/src/presentation/routing/routes.ts` (add `catalog` to `FACETS`)
- Modify: `frontend/src/presentation/project/ProjectView.tsx` (render it; make it the
  Curriculum tab's default reading)
- Test: `frontend/src/presentation/curriculum/CatalogPane.test.tsx`
- Test: `frontend/src/presentation/routing/routes.test.ts` (extend)

**Interfaces:**
- Consumes: `CatalogRepository` (Task 11), `CourseCard` (Task 12)

- [ ] **Step 1: Write the failing test**

Cover:
- three sections render, each with its cards, from a stubbed repository
- **the repository was actually called** with the project id — not that
  something rendered. A silent default makes "never wired" and "working"
  identical to a test that only inspects the DOM.
- featuring a card calls `feature(projectId, slug, rank)`
- `unplaceableFeatured` renders a visible note naming the stranded slugs
- a pending catalog renders `Loading`, an errored one renders `ErrorBox`
- `routes.test.ts`: `#/p/<id>/catalog/<key>` parses to the catalog facet with
  that key, and an unknown facet still falls back to `home`

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/curriculum/CatalogPane.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 3: Implement the pane, the category page and the facet**

`area` and `path` stay. They are the analytic readings and the catalog does not
replace them; `catalog` becomes the tab's default.

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/presentation/curriculum/ src/presentation/routing/`
Expected: all pass

- [ ] **Step 5: Prove the wiring test is not vacuous**

Replace the `catalog(projectId)` call with a hard-coded empty catalog and
re-run. Expected: the "repository was called" test FAILS. Restore by re-editing.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/presentation/
git commit -m "The Curriculum tab opens on a catalog"
```

---

### Task 14: All four gates, and a look at it running

- [ ] **Step 1: Backend gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

- [ ] **Step 2: Frontend gates**

```bash
cd frontend && npm run verify
```

Run `verify`, not the individual commands: the prettier check and the bundle-size
budget are only in the chain, and they are the two that fail in CI.

- [ ] **Step 3: Browser suite**

```bash
cd frontend && npm run test:browser
```

- [ ] **Step 4: Look at it**

```bash
cd frontend && npm run build && cd ..
AGENT_BASE_URL=<the configured endpoint> uv run web.py
```

Open the Curriculum tab on the Star Trek project. Check by eye: cards vary in
size, categories are plural and not all `unclassified`, and art differs between
cards. **A green suite is not this check** — a chosen control drawing in the
unchosen colour shipped past a fully green suite here once and was caught by eye.

- [ ] **Step 5: Commit and open a PR**

Commit message carries what was rejected and what is deliberately undone —
`git log` is a design record here.

---

## Self-review notes

**Spec coverage.** Candidates → Task 1. Featured override → Tasks 2, 3, 8, 9.
Categories and the port → Task 5. Blurbs and their weaker check → Tasks 4, 7.
Art placeholder → Task 6. Prominence → Task 1. Three sections → Task 8.
Category page → Task 13. Routes and 503 → Task 9. Both-ends test → Task 10.
Browser test for card geometry → Task 12. Staleness rendered → Tasks 11, 12.

**Known gap, deliberate.** The spec says a blurb is generated *on demand*. No
task builds the on-demand trigger — Tasks 4/7 build the writer and the cache,
and Task 8 reads the cache. The first person through will find every card
blurb-less. That is correct for this increment: the trigger belongs with the
course detail page in increment 2, where there is a place to put "generate copy
for this one". Cards render titles, anchors and art without it.

**Not covered by any task, and named in the spec as out of scope:** pagination,
search, free-text filter, generated titles, generated category labels.

# Course detail and realization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A reader clicks a catalog card, lands on a course page with a generated outline, and can decide the course is real — after which the disagreement between that decision and the drifting cluster is visible.

**Architecture:** `Course` is a `DeciderAggregate` on the log with one invariant (realize once), projected to a `courses` read model. Everything else is derived on read: fit is a pure function over the frozen ids and the current cluster; the outline is a cached model call, invalidated by membership hash comparison exactly as blurbs are. Authoring is started as a consequence of realizing, never as a condition of it.

**Tech Stack:** Python 3.12, `eventsource-py`, FastAPI, aiosqlite, LangChain chat models; React + TypeScript + Tailwind v4 + vitest.

**Spec:** `docs/superpowers/specs/2026-08-23-course-realization-design.md`

**Predecessor spec (vocabulary, assumed):** `docs/superpowers/specs/2026-08-23-course-catalog-browser-design.md`

## Global Constraints

- **Four gates, and passing three is not passing:** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, `cd frontend && npm run verify`. The two ruff commands run repo-wide, not over touched files.
- **Never run `git checkout <path>`.** It discards uncommitted work in that file, including other people's. To undo a deliberate break, re-edit the file.
- **Never run two vitest processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the cause.
- **No backwards compatibility is required.** This project is pre-release; break data, events and contracts rather than migrating — but say so in a docstring when you do.
- `CATALOG_NAMESPACE` is `UUID("c5e8a017-3d62-5f94-8b21-6a0d4e97c318")` in `research_team/infrastructure/persistence/read_models.py`. Every new row id under it carries a **prefix** in its derivation string. Existing prefixes: none (`CatalogFeatureRow`), `blurb:` (`CourseBlurbRow`). This plan adds `course:` and `outline:`.
- `PROMPT_ANCHORS = 12` in `research_team/application/course_authoring.py` is the anchor ceiling for any prompt about an area. Reuse it; do not invent a second number.
- **`application/` must never import `infrastructure/`.** `tests/test_architecture.py::test_imports_point_inward` enforces it. Ports go in `application/`, adapters in `infrastructure/`.
- **An event no projection handles counts as APPLIED.** A missing projection registration yields an empty read model and a 200, not an error. Every projection test must assert that a **row exists with the right data**, never that a request succeeded.
- Comments explain **why**, state costs as well as benefits, name what a test would fail on, and say when something was **measured** rather than reasoned. A comment that restates the code is worse than none.
- If a test would pass with the change reverted, say so in its docstring rather than leaving it as reassurance.

---

### Task 1: The `Course` aggregate and the fit function

**Files:**
- Create: `research_team/domain/course.py`
- Test: `tests/domain/test_course.py`

**Interfaces:**
- Consumes: `research_team.domain.learning_area.LearningArea` (has `.slug`, `.members` — each an `AreaMember` with `.entity_id`, `.name`, `.centrality` — `.anchors`, `.size`, `.display_name()`).
- Produces: `COURSE_AGGREGATE_TYPE`, `CourseRealized`, `CourseAbandoned`, `RealizeCourse`, `AbandonCourse`, `Course`, `CourseState`, `CourseFit`, `fit_of`, `course_stream_id`.

Follow the shape of `research_team/domain/course_authoring_run.py` exactly — it is the closest existing aggregate: `@register_event` classes deriving `DomainEvent`, frozen dataclass commands, a `BaseModel` state, a `decide` function raising `CommandRejectedError`, an `evolve` function, and a `DeciderAggregate` subclass. Read it before writing.

- [ ] **Step 1: Write the failing tests**

```python
# tests/domain/test_course.py
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from eventsource import CommandRejectedError

from research_team.domain.course import (
    AbandonCourse,
    CourseAbandoned,
    CourseFit,
    CourseRealized,
    CourseState,
    RealizeCourse,
    decide,
    evolve,
    fit_of,
)
from research_team.domain.learning_area import AreaMember, LearningArea


def _area(slug: str, ids: list[str]) -> LearningArea:
    members = tuple(
        AreaMember(entity_id=i, name=i.title(), entity_type="concept", centrality=1.0)
        for i in ids
    )
    return LearningArea(slug=slug, members=members)


def _realize(project_id, slug="warp-drive", ids=("a", "b")) -> RealizeCourse:
    return RealizeCourse(
        project_id=project_id,
        slug=slug,
        title="Warp Drive",
        member_entity_ids=tuple(ids),
        membership_hash="deadbeef",
        realized_at=datetime.now(UTC),
    )


def test_realizing_an_unrealized_course_emits_the_frozen_membership():
    project_id = uuid4()
    events = decide(_realize(project_id), CourseState())
    assert len(events) == 1
    assert isinstance(events[0], CourseRealized)
    assert events[0].member_entity_ids == ["a", "b"]


def test_realizing_twice_is_refused():
    """The invariant. A second CourseRealized would overwrite the frozen
    membership that fit is computed against, erasing the drift by observing
    it. Rejection is what keeps the comparison meaningful."""
    project_id = uuid4()
    state = evolve(CourseState(), decide(_realize(project_id), CourseState())[0])
    with pytest.raises(CommandRejectedError):
        decide(_realize(project_id, ids=("a", "b", "c")), state)


def test_abandoning_then_realizing_freezes_the_new_membership():
    """Abandon is a deliberate second decision, so re-realizing after it is
    allowed and *does* re-freeze. Distinguishes the guarded accident from the
    intended act."""
    project_id = uuid4()
    state = evolve(CourseState(), decide(_realize(project_id), CourseState())[0])
    state = evolve(state, decide(AbandonCourse(project_id, "warp-drive"), state)[0])
    events = decide(_realize(project_id, ids=("a", "b", "c")), state)
    assert events[0].member_entity_ids == ["a", "b", "c"]


def test_abandoning_an_unrealized_course_is_refused():
    with pytest.raises(CommandRejectedError):
        decide(AbandonCourse(uuid4(), "warp-drive"), CourseState())


@pytest.mark.parametrize(
    "area, expected",
    [
        pytest.param(
            _area("warp-drive", ["a", "b"]),
            CourseFit(kept=("a", "b"), added=(), dropped=(), orphaned=False),
            id="unchanged",
        ),
        pytest.param(
            _area("warp-drive", ["b", "c"]),
            CourseFit(kept=("b",), added=("c",), dropped=("a",), orphaned=False),
            id="drifted",
        ),
        pytest.param(
            None,
            CourseFit(kept=(), added=(), dropped=("a", "b"), orphaned=True),
            id="orphaned",
        ),
    ],
)
def test_fit_distinguishes_drift_from_orphaning(area, expected):
    """Parametrised over the property that separates the two answers -- whether
    the slug resolves at all -- rather than over a representative example. An
    orphaned course and a course that lost every member produce identical
    `dropped` tuples and must still be told apart, which is what `orphaned`
    carries and what a single non-parametrised case would never check."""
    assert fit_of(("a", "b"), area) == expected
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/domain/test_course.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'research_team.domain.course'`

- [ ] **Step 3: Write `research_team/domain/course.py`**

Module docstring must state, in this repository's register:
- Why this is an aggregate when `domain/catalog_curation.py` next door is not: featuring enforces nothing, realizing enforces realize-once, and the cost of getting it wrong is that a second `CourseRealized` overwrites the frozen membership fit is computed against — the drift erased by observing it, silently.
- Why `member_entity_ids` is on the event rather than recoverable from the hash: the hash says *that* it moved, the ids say *how*, and "how" is the whole feature. A hash-only event makes fit a boolean.
- Why `title` is carried despite being derivable while the slug resolves: the orphaned case has no `display_name()` to fall back on, and a stranded-course list that renders a bare slug hides the case it exists to surface.

Contents:

```python
COURSE_AGGREGATE_TYPE = "Course"


def course_stream_id(project_id: UUID, slug: str) -> StreamId:
    """One stream per (project, slug), so a project's courses do not serialise
    against each other -- realizing two courses at once is an ordinary thing to
    do and a shared stream would make one of them retry."""
    return StreamId(f"{project_id}:{slug}")
```

`CourseRealized` / `CourseAbandoned` exactly as the spec's Section 1 declares them. `member_entity_ids: list[str]` on the event (a `DomainEvent` is a pydantic model; use `list`, not `tuple`).

Commands, frozen dataclasses: `RealizeCourse(project_id, slug, title, member_entity_ids: tuple[str, ...], membership_hash, realized_at)` and `AbandonCourse(project_id, slug)`.

```python
class CourseState(BaseModel):
    realized: bool = False
    project_id: UUID | None = None
    slug: str = ""
    title: str = ""
    member_entity_ids: list[str] = Field(default_factory=list)
    membership_hash: str = ""
```

`decide` rejects `RealizeCourse` when `state.realized`, with a message naming the slug and saying abandon-first. It rejects `AbandonCourse` when not `state.realized`. `evolve` sets and clears `realized`; on `CourseAbandoned` it keeps the ids on the state rather than clearing them (nothing reads them while unrealized, and clearing loses the record for a projection replaying to build history).

Then:

```python
@dataclass(frozen=True)
class CourseFit:
    kept: tuple[str, ...]
    added: tuple[str, ...]
    dropped: tuple[str, ...]
    orphaned: bool


def fit_of(frozen_ids: Sequence[str], area: LearningArea | None) -> CourseFit:
    """How a realized course stands against its cluster now.

    Entity *ids*, not names. A dropped id has no name in the current cluster --
    resolving it would mean inventing a label for something that is gone -- so
    the presenter resolves what it can and reports the rest as ids.

    `area is None` is the orphaned case: the slug names no cluster, because
    slugs derive from an area's top anchor and re-clustering moves them. It is
    reported separately from "every member dropped" even though the two produce
    identical `dropped` tuples, because they call for different actions.
    """
    frozen = set(frozen_ids)
    if area is None:
        return CourseFit(
            kept=(), added=(), dropped=tuple(sorted(frozen)), orphaned=True
        )
    current = {m.entity_id for m in area.members}
    return CourseFit(
        kept=tuple(sorted(frozen & current)),
        added=tuple(sorted(current - frozen)),
        dropped=tuple(sorted(frozen - current)),
        orphaned=False,
    )
```

Finally the `Course(DeciderAggregate[CourseState, CourseCommand])` subclass, mirroring `CourseAuthoringRun`'s.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/domain/test_course.py -v`
Expected: PASS, 7 tests.

The helper above matches the real signatures, checked in pre-flight: `LearningArea(slug, members, title=None, summary=None)` with `anchors`/`size`/`display_name()` as properties, and `AreaMember(entity_id, name, entity_type, centrality, temporal=None)`. If anything disagrees, fix the helper — never the production code.

- [ ] **Step 5: Commit**

```bash
git add research_team/domain/course.py tests/domain/test_course.py
git commit -m "A course is a decision, so it earns the log"
```

---

### Task 2: `CourseRow`, `CourseProjection`, `CourseStore`

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` (add beside `CourseBlurbStore`)
- Test: `tests/infrastructure/test_course_read_model.py`

**Interfaces:**
- Consumes: Task 1's `CourseRealized`, `CourseAbandoned`; `CATALOG_NAMESPACE`.
- Produces: `CourseRow`, `CourseStore` (`open`, `get`, `for_project`, `realize`, `abandon`), `CourseProjection`.

Read `CourseBlurbRow` / `CourseBlurbStore` and `CatalogFeatureRow` / `CatalogFeatureStore` / `CatalogFeatureProjection` in the same file first. `CourseStore` is shaped like `CatalogFeatureStore` (it has a projection); the row is shaped like `CourseBlurbRow` (project-scoped index).

- [ ] **Step 1: Write the failing test**

```python
# tests/infrastructure/test_course_read_model.py
async def test_realizing_stores_the_frozen_membership(tmp_path):
    """Asserts the row and its ids, not that anything returned 200.

    This is the test CLAUDE.md's projection entry asks for: an event no
    projection handles counts as applied, so a build with CourseProjection
    unregistered answers every request happily with an empty table. An
    assertion on a status code passes with the projection deleted; this one
    does not.
    """
    store = await CourseStore.open(str(tmp_path / "r.db"))
    project_id = uuid4()
    await CourseProjection(store).handle(
        CourseRealized(
            project_id=project_id,
            slug="warp-drive",
            title="Warp Drive",
            member_entity_ids=["a", "b"],
            membership_hash="deadbeef",
            realized_at=datetime.now(UTC),
        )
    )
    row = await store.get(project_id, "warp-drive")
    assert row is not None
    assert row.member_entity_ids == ["a", "b"]
    assert row.abandoned is False


async def test_abandoning_marks_the_row_rather_than_deleting_it(tmp_path):
    """A delete would let a rebuild resurrect the course: the projection
    replays CourseRealized, finds nothing to undo it, and the course comes
    back realized. The column survives the replay in the right order."""
    ...
    assert row.abandoned is True
    assert row.member_entity_ids == ["a", "b"]


async def test_for_project_omits_another_projects_courses(tmp_path):
    ...


async def test_a_course_row_id_does_not_collide_with_a_blurb_or_a_feature(tmp_path):
    """All three share CATALOG_NAMESPACE and hash the same {project}:{slug}
    pair. The prefixes are what keep them apart, and this fails if one is
    dropped."""
    project_id, slug = uuid4(), "warp-drive"
    ids = {
        CourseRow.row_id(project_id, slug),
        CourseBlurbRow.row_id(project_id, slug),
        CatalogFeatureRow.row_id(project_id, slug),
    }
    assert len(ids) == 3
```

Fill the elided bodies following the first test's shape.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/infrastructure/test_course_read_model.py -v`
Expected: FAIL on the import of `CourseRow`.

- [ ] **Step 3: Implement**

```python
class CourseRow(ReadModel):
    __table_name__ = "courses"

    project_id: UUID
    slug: str
    title: str
    member_entity_ids: list[str] = Field(default_factory=list)
    membership_hash: str
    realized_at: datetime
    abandoned: bool = False
    """Marked rather than deleted, so a rebuild replaying CourseRealized then
    CourseAbandoned lands where a rebuild replaying only the first does not.
    A delete would make abandonment invisible to the replay that follows it."""

    @field_validator("member_entity_ids", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        # `course:` for the reason `CourseBlurbRow` gives for `blurb:` -- three
        # row types now share CATALOG_NAMESPACE over the same {project}:{slug}.
        return uuid5(CATALOG_NAMESPACE, f"course:{project_id}:{slug}")
```

`CourseStore.open` creates the project index (`idx_courses_project`) exactly as `CourseBlurbStore.open` does, and carries the same note that `apply_schema` reconciles columns and not indexes. `get` checks `row.project_id != project_id` for `CourseBlurbStore.get`'s stated reason. `for_project` returns non-abandoned rows.

`CourseProjection` follows `CatalogFeatureProjection`: `handles` both event types, `handle` dispatches to `store.realize(...)` / `store.abandon(...)`.

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/infrastructure/test_course_read_model.py -v`

- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/persistence/read_models.py tests/infrastructure/test_course_read_model.py
git commit -m "The courses table, and why abandon is a column and not a delete"
```

---

### Task 3: `CourseOutlineRow` and `CourseOutlineStore`

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` (beside `CourseBlurbStore`)
- Test: `tests/infrastructure/test_course_outline_store.py`

**Interfaces:**
- Produces: `CourseOutlineRow`, `CourseOutlineStore` (`open`, `get`, `put`).

This is a **cache, not a projection** — nothing on the log describes an outline, so there is nothing to replay. Copy `CourseBlurbStore`'s structure and its docstring reasoning for having no projection and no `stale` flag.

- [ ] **Step 1: Write the failing test**

```python
async def test_an_outline_round_trips_its_sections(tmp_path):
    store = await CourseOutlineStore.open(str(tmp_path / "r.db"))
    project_id = uuid4()
    await store.put(
        project_id,
        "warp-drive",
        promise="What made faster-than-light travel possible.",
        sections=[{"heading": "Origins", "summary": "Cochrane's first flight."}],
        membership_hash="deadbeef",
        model="qwen",
        generated_at=datetime.now(UTC),
    )
    row = await store.get(project_id, "warp-drive")
    assert row.sections == [{"heading": "Origins", "summary": "Cochrane's first flight."}]
    assert row.membership_hash == "deadbeef"


async def test_putting_the_same_slug_twice_replaces_rather_than_duplicates(tmp_path):
    """Keyed by (project, slug) through row_id, so regenerating after drift
    overwrites. A second row would make `get` return whichever the repository
    happened to reach first, which is a cache that reports a stale hash at
    random."""
    ...


async def test_an_outline_row_id_does_not_collide_with_a_blurb(tmp_path):
    ...
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/infrastructure/test_course_outline_store.py -v`

- [ ] **Step 3: Implement**

```python
class CourseOutlineRow(ReadModel):
    """One generated outline, cached against the cluster it describes.

    Its own table rather than a `kind` column beside `CourseBlurbRow`. A blurb's
    payload is one `text` column and this one's is a structured list, so a
    shared table needs a JSON column that only half its rows ever fill -- and
    then the two row types share nothing but a primary key and a namespace. Two
    stores of the same shape are duplication a reader can see; one store with a
    column meaningful for half its rows is a schema that has to be explained.

    No `stale` flag, for `CourseBlurbRow`'s reason: `membership_hash` answers
    the same question by comparison, and a flag would be a second answer that
    can disagree with the first.
    """

    __table_name__ = "course_outlines"

    project_id: UUID
    slug: str
    promise: str
    sections: list[dict] = Field(default_factory=list)
    """`[{"heading": ..., "summary": ...}]`, in reading order."""
    membership_hash: str
    model: str
    generated_at: str

    @field_validator("sections", mode="before")
    @classmethod
    def _decode_json_list(cls, value: object) -> object:
        if isinstance(value, str):
            return json.loads(value)
        return value

    @staticmethod
    def row_id(project_id: UUID, slug: str) -> UUID:
        return uuid5(CATALOG_NAMESPACE, f"outline:{project_id}:{slug}")
```

`CourseOutlineStore` mirrors `CourseBlurbStore` including the index note.

- [ ] **Step 4: Run to verify pass**
- [ ] **Step 5: Commit**

```bash
git add research_team/infrastructure/persistence/read_models.py tests/infrastructure/test_course_outline_store.py
git commit -m "The outline cache, and why it is not a kind column on blurbs"
```

---

### Task 4: Share the grounding check, then write `ModelOutlineWriter`

**Files:**
- Create: `research_team/infrastructure/knowledge/grounding.py`
- Modify: `research_team/infrastructure/knowledge/blurb_writer.py` (import the shared predicate; delete the local copy)
- Create: `research_team/infrastructure/knowledge/outline_writer.py`
- Modify: `research_team/application/course_catalog.py` (add `OutlineTextPort` **and** `OutlineCachePort` + `CachedOutline` — see Global Constraints)
- Test: `tests/infrastructure/test_outline_writer.py`
- Test: `tests/infrastructure/test_blurb_writer.py` (existing — must stay green unchanged)

**Interfaces:**
- Consumes: `research_team.domain.learning_area.AreaMember`.
- Produces: `grounding.ungrounded_runs(reply, anchors) -> list[str]`, `grounding.SENTENCE_OPENERS`; `OutlineTextPort.write(title, anchors) -> DraftOutline | None`; `OutlineTextPort.model_name: str`; `DraftOutline(promise: str, sections: tuple[tuple[str, str], ...])`.
- Also produces: **`BlurbTextPort.model_name: str`**, and the matching property on `ModelBlurbWriter`. See R7 below.

**Read `blurb_writer.py` in full before starting.** Its grounding check has three rounds of review behind it — a capitalised run in the reply must substring-match an anchor name, with a shrunk list of exempt sentence openers. **Move it; do not re-derive it.** Two copies of that predicate will drift, and the blurb's copy is the one that survived review.

- [ ] **Step 1: Move the predicate, keeping the blurb tests green**

Cut `_ungrounded_runs`, `_SENTENCE_OPENERS` and any regex constants they use into `grounding.py` as public names. `blurb_writer.py` imports them. **Run `uv run pytest tests/infrastructure/test_blurb_writer.py -v` and confirm every test still passes with no edits to the test file.** If a test needed editing, the move changed behaviour and is wrong — undo the edit and fix the move.

Commit this alone:

```bash
git add research_team/infrastructure/knowledge/grounding.py research_team/infrastructure/knowledge/blurb_writer.py
git commit -m "The grounding check moves out of the blurb writer so the outline can share it"
```

- [ ] **Step 2: Write the failing outline tests**

```python
async def test_an_outline_naming_an_entity_the_cluster_does_not_hold_is_refused():
    """Same conservative side as the blurb: refusing a plausible outline costs
    a card its copy, and returning an ungrounded one puts a claim about
    coverage in front of a reader that the graph cannot support."""
    writer = ModelOutlineWriter(_stub_model(SECTIONS_NAMING_PICARD))
    assert await writer.write("Warp Drive", _anchors(["Zefram Cochrane"])) is None


async def test_an_outline_grounded_in_its_anchors_is_returned():
    ...


async def test_an_outline_with_fewer_than_three_sections_is_refused():
    """Two sections is a blurb with bullets. The floor is what makes this a
    different artifact from the one already on the card."""
    ...


async def test_an_outline_with_more_than_six_sections_is_truncated_not_refused():
    """The ceiling is padding, not ungroundedness -- the extra sections are
    usually real and simply thin. Truncating keeps the good ones; refusing
    would throw away a whole model call over a formatting excess."""
    ...


async def test_a_reply_that_is_not_the_expected_shape_is_refused_rather_than_raising():
    """A local model returns prose instead of the asked-for structure often
    enough that this is the ordinary path, not the edge case."""
    ...
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/infrastructure/test_outline_writer.py -v`

- [ ] **Step 4: Implement**

**R7 — both text ports gain a `model_name` property.** `CourseBlurbRow` and `CourseOutlineRow` both carry a `model` column, and nothing in the system can currently fill it: `ModelBlurbWriter` holds a `BaseChatModel` privately and exposes only `write`. Increment 1 never noticed because it never called `put`. The caller is in `application/`, which `tests/test_architecture.py` keeps free of LangChain's vocabulary, so it cannot reach into the chat model itself.

Add `model_name: str` to `BlurbTextPort` and `OutlineTextPort`, implemented on each adapter as a property reading the chat model's own name (`getattr(self._model, "model_name", None) or getattr(self._model, "model", None) or type(self._model).__name__` — a local model's LangChain wrapper does not reliably carry either attribute, and a stored `"unknown"` is better than a crash on a value that exists only for provenance). Add a test that the property is non-empty for a stub model carrying neither attribute.

The alternative — returning the name beside the text from `write` — was rejected: it makes every refusal (`None`) also lose the model name, and the name is a property of the writer, not of one reply.

`OutlineTextPort` in `research_team/application/course_catalog.py`, beside `BlurbTextPort` and documented in the same register — including that `None` is a legitimate answer and not an error, and **that per CLAUDE.md this port has exactly one production adapter and therefore needs a test driving both ends over real data** (Task 13).

`ModelOutlineWriter(model: BaseChatModel)` in `infrastructure/knowledge/outline_writer.py`:
- Prompt names at most `PROMPT_ANCHORS` anchors (import the constant from `application/course_authoring.py`; do not restate 12).
- Asks for a one-sentence promise and three to six `## Heading` / paragraph pairs.
- Parses; on a parse failure returns `None`.
- Runs `grounding.ungrounded_runs` **separately over each field** — the promise, each heading, each summary — and concatenates the results. Any ungrounded run refuses the whole outline.

  **Do not join the fields into one string first.** `_SENTENCE_SPLIT` splits on terminal punctuation, and a heading has none, so a joined `"Origins"` + `"Cochrane's first flight."` reads as one sentence and yields the single capitalised run `Origins Cochrane's` — grounded in no anchor, refusing every outline that has a capitalised heading. Which is every outline. Add a test that would fail on the joined version:

```python
async def test_a_capitalised_heading_does_not_run_into_the_summary_beneath_it():
    """Fails on a writer that joins the fields before checking: the heading
    and the summary's first word fuse into one capitalised run that no anchor
    contains, refusing every outline that has a heading. Every outline has a
    heading."""
```
- Fewer than three sections refuses; more than six truncates to six.

- [ ] **Step 5: Run to verify pass, then re-run the blurb suite**

Run: `uv run pytest tests/infrastructure/test_outline_writer.py tests/infrastructure/test_blurb_writer.py -v`

- [ ] **Step 6: Commit**

```bash
git add research_team/infrastructure/knowledge/outline_writer.py research_team/application/course_catalog.py tests/infrastructure/test_outline_writer.py
git commit -m "An outline the graph can support, or none at all"
```

---

### Task 5: `AuthoringRunStore.authored_session_for`

**Files:**
- Modify: `research_team/infrastructure/persistence/read_models.py` (`AuthoringRunStore`)
- Test: `tests/infrastructure/test_authoring_run_store.py` (extend if it exists; create if not)

**Interfaces:**
- Produces: `async def authored_session_for(self, project_id: UUID, target: str) -> UUID | None`

`AuthoringRunRow.authored` is `[{"target": ..., "session_id": ...}]`. Scan this project's rows newest `started_at` first and return the first matching target's session.

- [ ] **Step 1: Write the failing test**

```python
async def test_the_newest_run_wins_when_a_target_was_authored_twice(tmp_path):
    """Re-authoring an area writes a second session, and the course page must
    link the one that exists now rather than the first ever written. Ordering
    is the whole method; a version returning any match passes a single-run
    test and fails this one."""
    ...


async def test_a_target_no_run_authored_has_no_session(tmp_path):
    ...


async def test_another_projects_run_is_not_matched(tmp_path):
    ...
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement.** Filter in Python over `for_project`-style rows rather than in SQL — `authored` is a JSON column and a `json_each` query would tie this read to SQLite in a file whose other reads do not.
- [ ] **Step 4: Run to verify pass**
- [ ] **Step 5: Commit**

```bash
git commit -am "Which session holds a target's course, newest run first"
```

---

### Task 6: `CourseService`

**Files:**
- Create: `research_team/application/course_realization.py`
- Test: `tests/application/test_course_realization.py`

**Interfaces:**
- Consumes: Task 1's `Course`, `RealizeCourse`, `AbandonCourse`, `fit_of`, `CourseFit`; `application/curriculum.Curriculum`; `application/course_catalog.CourseCandidate` via `CatalogService`.
- Produces:
  - `RealizedCoursePort` (Protocol): `for_project(project_id) -> Sequence[RealizedCourse]`, `get(project_id, slug) -> RealizedCourse | None`.
  - `RealizedCourse` — this layer's own frozen dataclass (`CachedOutline` lives in `course_catalog.py`; see R2), **not** the `read_models` row types, for `CachedBlurb`'s stated reason (`tests/test_architecture.py` keeps `infrastructure.persistence` out of `application/`).
  - `CourseService.detail(project_id, curriculum, catalog, slug) -> CourseDetail | None`
  - `CourseService.orphans(project_id, curriculum) -> tuple[RealizedCourse, ...]`
  - `CourseDetail(candidate, outline, members, course)` where `course` is `None | RealizedCourseView(realized_at, membership_hash, fit, authored_session_id)`.

`CourseService.detail` generates the outline when the cache misses or its hash disagrees, awaits it, and `put`s the result. A refusal (`None`) is cached **not at all** — a refused outline is retried next visit, because the refusal is usually a bad sample rather than a property of the cluster, and a cached refusal would make the card permanently blank with nothing to retry it.

- [ ] **Step 1: Write the failing tests**

```python
async def test_a_missing_outline_is_generated_and_cached():
    ...
    assert writer.calls == 1
    assert cache.put_calls == 1


async def test_a_cached_outline_whose_hash_matches_is_not_regenerated():
    ...
    assert writer.calls == 0


async def test_a_cached_outline_whose_hash_disagrees_is_regenerated():
    """The staleness mechanism. A version that only checks presence passes the
    first two tests and never regenerates after a single drift."""
    ...
    assert writer.calls == 1


async def test_a_refused_outline_is_not_cached():
    """So the next visit retries. Caching a refusal makes the blank permanent
    and gives nothing a way to clear it."""
    ...
    assert cache.put_calls == 0
    assert detail.outline is None


async def test_a_realized_course_reports_its_fit_against_the_current_cluster():
    ...


async def test_orphans_lists_a_realized_course_whose_slug_names_no_cluster():
    """The route cannot reach these -- the candidate does not exist -- so this
    is the only surface they have. A version returning () passes every other
    test in this file."""
    ...
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run to verify pass**
- [ ] **Step 5: Commit**

```bash
git add research_team/application/course_realization.py tests/application/test_course_realization.py
git commit -m "The course detail read, and why a refused outline is not cached"
```

---

### Task 7: The blurb sweep

**Files:**
- Create: `research_team/interfaces/web/blurb_sweep.py`
- Test: `tests/interfaces/test_blurb_sweep.py`

**Interfaces:**
- Consumes: `application/course_catalog.BlurbTextPort`, `BlurbCachePort`, `CatalogService`.
- Produces: `BlurbSweep` with `async start(project_id, candidates, write) -> dict`, `progress(project_id) -> dict`, and `SweepAlreadyActive`.

Model this on `research_team/interfaces/web/authoring.py`'s `AuthoringActivity`: one run at a time per project, an in-memory progress record, `RunAlreadyActive` raised on a second start. **Read it first.** Unlike `AuthoringActivity` this needs no aggregate — a blurb is a cache entry, nothing on the log describes one, and the progress is genuinely process state that a restart should lose.

Progress shape: `{"running": bool, "done": int, "total": int, "failed": int}`.

- [ ] **Step 1: Write the failing tests**

```python
async def test_the_sweep_writes_a_blurb_for_every_candidate_that_lacks_one():
    ...
    assert cache.put_calls == 3


async def test_a_candidate_whose_blurb_matches_the_current_hash_is_skipped():
    ...


async def test_a_refusal_is_counted_and_does_not_stop_the_sweep():
    """A blurb the model will not ground is a card that keeps its title and its
    art -- exactly what increment 1 renders today. Stopping would let one
    stubborn cluster block every card behind it."""
    ...
    assert progress["failed"] == 1
    assert progress["done"] == 2


async def test_a_second_sweep_while_one_runs_is_refused():
    ...


async def test_progress_for_a_project_that_never_swept_reports_not_running():
    ...
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run to verify pass**
- [ ] **Step 5: Commit**

```bash
git add research_team/interfaces/web/blurb_sweep.py tests/interfaces/test_blurb_sweep.py
git commit -m "The blurbs increment 1 built and never wrote"
```

---

### Task 8: Compose everything

**Files:**
- Modify: `research_team/composition.py`
- Test: `tests/test_composition.py` (extend)

**Interfaces:**
- Consumes: Tasks 2, 3, 4, 6, 7.
- Produces on `Application`: `courses: CourseStore` (via the same lazy pattern as `_blurb_cache` if it must open late), `course_service: CourseService`, `outlines: ModelOutlineWriter`, `blurb_sweep: BlurbSweep`, `course_repository: AggregateRepository[Course]`, and **`CourseProjection` registered on the subscription**.

**Read `composition.py`'s `_LazyBlurbCache` and the `CatalogFeatureRunner`/`catalog_features` property first — including the docstring at line ~458 in `app.py` explaining why `catalog_features` is a getter.** Anything this task adds that does not exist until `start()` must be handed to `create_app` the same way, or it will be captured as `None` and every request will 503. That bug shipped once (PR #272) and its comment is in the file.

`ModelOutlineWriter` takes the same `extraction_model` `ModelBlurbWriter` does. Do not introduce a second model configuration.

- [ ] **Step 1: Write the failing test**

```python
async def test_the_course_projection_is_registered(tmp_path):
    """Not 'the app starts'. An event no projection handles counts as applied,
    so a build with CourseProjection missing starts cleanly, answers every
    request 200, and reports every course unrealized forever. This asserts the
    projection is on the subscription's handler set by name."""
    ...


async def test_a_realized_course_survives_a_restart(tmp_path):
    """The end-to-end version of the above, and the one that would have caught
    it: realize, close, reopen from the same database, and read the row back."""
    ...
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_composition.py tests/test_architecture.py -v`

- [ ] **Step 5: Commit**

```bash
git commit -am "Wire the course projection, the outline writer and the blurb sweep"
```

---

### Task 9: The routes

**Files:**
- Modify: `research_team/interfaces/web/app.py`
- Modify: `web.py` (pass the new collaborators through, following the `catalog_features` getter pattern)
- Test: `tests/interfaces/test_course_routes.py`

**Interfaces:**
- Produces:
  - `GET  /api/projects/{project_id}/catalog/{slug}` → detail
  - `POST /api/projects/{project_id}/catalog/{slug}/realize` → 202
  - `POST /api/projects/{project_id}/catalog/{slug}/abandon` → 200
  - `POST /api/projects/{project_id}/catalog/blurbs` → 202
  - `GET  /api/projects/{project_id}/catalog/blurbs` → progress

**Route ordering.** `/catalog/blurbs` is a literal one-segment path that collides with `/catalog/{slug}` on method and segment count for the GET. **Register `/catalog/blurbs` above `/catalog/{slug}`** or FastAPI's declaration-order matching reads `blurbs` as a slug. The `/catalog/categories/{key}` block already carries this comment; extend it rather than writing a second one.

**Where the frozen membership comes from.** `CourseCandidate` carries `anchors` only — at most 12 members. The realize route must resolve the `LearningArea` from `curriculum.projection.areas` by slug and freeze `tuple(m.entity_id for m in area.members)`, the **full** membership. `membership_hash` comes from the candidate. Freezing anchors instead would make every course a 12-member course and make fit report drift that is an artifact of the anchor cap.

**Extract `_one`** out of `author_courses` into a closure both it and the realize route call, so there is one call into `CourseAuthor` and not two copies.

- [ ] **Step 1: Write the failing tests**

```python
async def test_realizing_records_the_decision_even_when_a_run_is_in_flight(client):
    """The design's load-bearing case. The authoring endpoint answers 409 when a
    run is active; letting that propagate would make whether you can *choose* a
    course depend on whether someone else is mid-run. 202, frame null, reason
    set, and the row is there."""
    response = await client.post(f"/api/projects/{project_id}/catalog/{slug}/realize")
    assert response.status_code == 202
    assert response.json()["realized"] is True
    assert response.json()["authoring"] is None
    assert response.json()["reason"]
    row = await store.get(project_id, slug)
    assert row is not None


async def test_realizing_an_unknown_slug_is_404(client):
    ...


async def test_realizing_twice_is_409(client):
    ...


async def test_reading_blurb_progress_is_not_read_as_a_slug(client):
    """Route ordering. With the declarations swapped this answers 404 for a
    course named 'blurbs' instead of the sweep's progress."""
    response = await client.get(f"/api/projects/{project_id}/catalog/blurbs")
    assert response.status_code == 200
    assert "running" in response.json()


async def test_the_detail_route_generates_a_missing_outline(client):
    ...


async def test_abandoning_does_not_cancel_a_running_authoring_run(client):
    """The decision is withdrawn; the work it caused is not. Deleting a
    person's course because they clicked the wrong thing is the failure this
    guards."""
    ...
```

- [ ] **Step 2: Run to verify failure**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/interfaces/test_course_routes.py tests/interfaces/test_catalog_routes.py -v`

- [ ] **Step 5: Commit**

```bash
git commit -am "Realize records the decision; authoring is a consequence, not a condition"
```

---

### Task 10: Presenters

**Files:**
- Modify: `research_team/interfaces/web/presenters.py`
- Test: `tests/interfaces/test_presenters.py` (extend)

**Interfaces:**
- Produces: `course_detail_view(detail) -> dict`; `catalog_view` gains `orphanedCourses`.

`fit` resolves ids to names against the current area's members. **A dropped id has no name there and is reported as its id** — do not look it up anywhere else and do not substitute a placeholder.

`catalog_view` gains `"orphanedCourses": [{"slug", "title", "realizedAt"}]` beside the existing `unplaceableFeatured`.

Carry `membershipHash` on the outline exactly as increment 1's `candidate_view` carries it on the blurb — that field was dropped once in review and every blurb would have reported stale forever.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_dropped_entity_is_reported_as_its_id_when_the_cluster_no_longer_names_it():
    """Not a placeholder and not a lookup elsewhere. The name is genuinely gone
    and inventing one would claim knowledge the current cluster does not have."""
    ...


def test_the_outline_carries_a_membership_hash_that_can_differ_from_the_candidates():
    """Increment 1's regression, one field over. A view that omits it makes
    every outline report stale forever; a view that copies the candidate's
    makes every outline report fresh forever. The stub returns a different
    hash so a copy fails."""
    ...


def test_a_catalog_with_no_orphans_carries_an_empty_list_not_a_missing_key():
    ...
```

- [ ] **Step 2-5:** failing run, implement, passing run, commit.

```bash
git commit -am "Present the fit, the outline's own hash, and the stranded courses"
```

---

### Task 11: Frontend domain and repository

**Files:**
- Create: `frontend/src/domain/knowledge/course.ts`
- Create: `frontend/src/infrastructure/http/course-repository.ts`
- Test: `frontend/src/domain/knowledge/course.test.ts`
- Test: `frontend/src/infrastructure/http/course-repository.test.ts`

**Interfaces:**
- Consumes: `frontend/src/infrastructure/http/catalog-repository.ts` (read it — match its fetch, error and type conventions exactly).
- Produces: types `CourseDetail`, `CourseFit`, `Outline`, `RealizedCourse`; `outlineAge(detail): 'stale' | null` mirroring `catalog.ts`'s `blurbAge`; repository functions `fetchCourse`, `realizeCourse`, `abandonCourse`, `startBlurbSweep`, `fetchBlurbSweep`.

`fitSummary(fit)` returns a short phrase for the banner — the counts and the orphaned case distinguished.

- [ ] **Step 1: Write the failing tests** — including one asserting `outlineAge` reports `'stale'` when the outline's hash differs from the candidate's, and `null` when they match.
- [ ] **Step 2: Run to verify failure.** `cd frontend && npm test -- src/domain/knowledge/course.test.ts` — **one vitest process at a time.**
- [ ] **Step 3-5:** implement, pass, commit.

---

### Task 12: `CoursePage.tsx`

**Files:**
- Create: `frontend/src/presentation/curriculum/CoursePage.tsx`
- Test: `frontend/src/presentation/curriculum/CoursePage.test.tsx`
- Modify: the route table (find it with `grep -rn "catalog/:key\|categories/:key" frontend/src`)
- Create: `frontend/src/domain/knowledge/title-case.ts` + its test

**Title casing happens here, at display time, and nowhere else.** The generated
title is stored in **sentence case**, because `grounding.ungrounded_runs` finds
invented entity names by capitalisation and a Title Case string collapses into
one capitalised run that no anchor contains — so a fully grounded Title Case
title is refused along with an invented one (measured 2026-08-23). Sentence
case is the only shape the grounding check can read.

The string reaching the frontend has therefore **already passed grounding**, so
casting it cosmetically carries no trust risk at all. Write
`titleCase(s: string): string` — capitalise each word except a small stop-word
list (`of`, `the`, `and`, `a`, `an`, `in`, `to`, `for`), and never the first
word's exception. Apply it in `CourseCard` and `CoursePage`.

**Do not lowercase a title before grounding it, ever.** That was considered and
is a trap: down-casing the input leaves no capitalised runs, so
`ungrounded_runs` returns `[]` for every title, grounded or invented. It does
not weaken the check, it deletes it — a no-op wearing the shape of a working
one, which is the failure CLAUDE.md's `RING_INWARD` and co-mention entries are
both about.

**Interfaces:**
- Consumes: Task 11's repository and types; `CourseCard.tsx` for the art treatment.

Layout: art and title, blurb, "Make this course" or the realized state, the outline, then the member list.

**Tailwind v4 with no default theme.** Numbered spacing utilities like `w-80` generate no CSS in this build and silently collapse the element — increment 1 shipped every card at 39.23px that way. Use arbitrary values (`w-[320px]`). `frontend/scripts/check-tailwind.mjs` covers `w`/`h`; run it.

**`border-solid` beside one directional width draws three unwanted sides.** Pair `border-0` with the directional width, and never write `border-0 border`.

Tests in jsdom: roles, focus order, keyboard routing, rendered text. **Do not assert computed styles there** — jsdom lays nothing out and returns only what an inline style said. If this page's correctness turns on a measurement, add a `*.browser.test.tsx` and run `npm run test:browser`.

- [ ] **Step 1: Write the failing tests**

```tsx
it('offers to make an unrealized course real', ...)
it('shows when a realized course was realized, and does not offer to make it again', ...)
it('names what the cluster added and dropped when a realized course has drifted', ...)
it('says the cluster is gone rather than showing a diff when the course is orphaned', ...)
it('links the authored session when one exists, and offers to author when none does', ...)
it('marks the outline stale when its hash disagrees with the candidate', ...)
```

- [ ] **Step 2-5:** failing run, implement, passing run, commit.

---

### Task 13: The catalog page, and the both-ends real-data tests

**Files:**
- Modify: `frontend/src/presentation/curriculum/CatalogPane.tsx` (card links, sweep button and progress, orphaned strip)
- Modify: `frontend/src/presentation/curriculum/CourseCard.tsx` (become a link)
- Test: `frontend/src/presentation/curriculum/CatalogPane.test.tsx` (extend)
- Test: `tests/infrastructure/test_outline_over_a_real_ingest.py`

**The both-ends test is the one this repository's history demands.** `OutlineTextPort` has exactly one production adapter. Per CLAUDE.md, a port with one adapter and no test between them is two things that were never checked against each other — the co-mention channel shipped that way and produced nothing for a release. Follow `test_a_catalog_over_a_real_ingest_has_cards_in_more_than_one_category` for how increment 1 reaches a real ingest.

```python
async def test_an_outline_over_a_real_ingest_names_only_entities_the_cluster_holds():
    """Drives the real writer against real anchors, not a stub against a stub.

    Skips when no real ingest is available, and the skip is loud: a silently
    skipped both-ends test is the same nothing the port already had."""
```

- [ ] **Step 1-5:** as above, plus `cd frontend && npm run verify` before committing the frontend half.

---

### Task 14: Verify against a copy of the real database

**Files:**
- Modify: `docs/superpowers/specs/2026-08-23-course-realization-design.md` (record what was measured, and when)

**A read-model change verified only against a fresh database is unverified.** This adds two tables to a database that predates them.

- [ ] **Step 1: Make a real copy**

```bash
uv run python -m research_team.infrastructure.persistence.local_copy /tmp/claude-1000/-home-ty-workspace-research-team/86b56ea4-66c0-41bd-ab83-ee4a21b74420/scratchpad/probe.db
```

Do **not** `cp` the database — the store id derives from its path and every checkpoint carries it, so a plain copy raises `PositionForeignError` on start. Do **not** delete the checkpoints to get past that: a projection with no checkpoint replays the whole log, which is `/rebuild` by another name and hides the half of the bug that survives `apply_schema`.

- [ ] **Step 2: Start against it** using the `AGENT_DB=` line `local_copy` prints, and confirm the server comes up, `courses` and `course_outlines` exist, and the catalog and detail routes answer.

- [ ] **Step 3: Realize one course against the real data**, restart, and confirm the row is still there with its frozen ids.

- [ ] **Step 4: Record the measurement** in the spec — what was run, against what, on what date, and what it showed. Reasoned is not measured.

- [ ] **Step 5: Run all four gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

- [ ] **Step 6: Commit**

```bash
git commit -am "Verified against a copy of the real database, not a fresh one"
```

---

### Task 15: A course title, not an entity name

**Dispatched between Tasks 6 and 7.** Appended here rather than renumbered so
every brief path already generated still points at the task it was cut from.

**Files:**
- Modify: `research_team/application/course_catalog.py` (`BlurbTextPort`, `CachedBlurb`, `CatalogService`)
- Modify: `research_team/infrastructure/knowledge/blurb_writer.py`
- Modify: `research_team/infrastructure/persistence/read_models.py` (`CourseBlurbRow`, `CourseBlurbStore.put`)
- Modify: `research_team/composition.py` (`_LazyBlurbCache`)
- Test: `tests/infrastructure/test_blurb_writer.py`, `tests/infrastructure/test_course_blurbs.py`, `tests/application/test_catalog_service.py`

**Why.** `CourseCandidate.title` is `area.display_name()`, which is
`area_projection.py:565`'s `anchor.name` — the single highest-centrality entity
in the cluster. That is an entity name, not a course name, and it reads like
one: this project's real catalog offers courses called "Xindi" and
"Rotten Tomatoes". Increment 1's spec pinned the field to `display_name()` and
said "not generated in this increment"; this is that increment.

**Why it rides on the blurb call rather than getting its own.** The writer
already makes one grounded model call per candidate and already has the
anchors in the prompt. A second call would double the cost of a sweep that is
already the most expensive thing on the page, and — worse — would let the title
and the blurb disagree about what the course is *about*, with nothing to
notice. One call returns both or refuses both.

**The fallback is not optional.** A candidate with no cached copy, or whose
copy the model refused, must still render. `display_name()` stays as the
fallback, so a cold catalog looks exactly as it does today rather than as a
page of blank cards.

**Interfaces:**
- Consumes: Task 4's `grounding.ungrounded_runs`, `BlurbTextPort.model_name`.
- Produces: `DraftBlurb(title: str, text: str)`; `BlurbTextPort.write(...) -> DraftBlurb | None`; `CachedBlurb.title: str`; `CourseBlurbRow.title: str = ""`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/infrastructure/test_blurb_writer.py
async def test_the_writer_returns_a_title_and_a_blurb_from_one_call():
    """One call, not two. A second model call for the title would double a
    sweep's cost and let the two disagree about what the course is about, with
    nothing able to notice."""
    ...


async def test_a_title_naming_an_entity_the_cluster_does_not_hold_refuses_both():
    """The title is grounded on the same terms as the blurb. Refusing only the
    title would leave a card with grounded copy under an invented name, which
    is the more prominent of the two."""
    ...


async def test_a_reply_with_a_blurb_and_no_title_is_refused():
    ...
```

```python
# tests/application/test_catalog_service.py
async def test_a_candidate_with_no_cached_copy_falls_back_to_the_area_name():
    """So a cold catalog renders as it does today rather than as blank cards.
    Fails on an implementation that reads the cached title unconditionally."""
    ...


async def test_a_cached_title_is_preferred_over_the_area_name():
    ...
```

```python
# tests/infrastructure/test_course_blurbs.py
async def test_a_blurb_row_written_before_titles_existed_reads_back_with_an_empty_title():
    """`apply_schema` reconciles added columns, but it leaves them empty in
    rows that predate the change. A `title` with no default would make the
    column required on a populated table, which the read-models section of
    CLAUDE.md records as the case SQLite refuses and this project already
    shipped once. Empty is the honest value and the fallback covers it."""
    ...
```

- [ ] **Step 2: Run to verify failure**

- [ ] **Step 3: Implement**

The prompt asks for a title on its own first line and the two sentences
beneath it. Constrain it in the prompt and enforce it in the parse:
**three to eight words, no trailing punctuation, and not identical to the top
anchor's name** — the last because a model handed one dominant entity will
return it verbatim, which is the defect this task exists to fix and which
would otherwise pass every grounding check by construction.

`CourseBlurbRow.title: str = ""` — a default, not required, for the reason in
the test docstring above.

`CatalogService.build` sets `title=cached.title or area.display_name()`.

- [ ] **Step 4: Run to verify pass**
- [ ] **Step 5: Commit**

```bash
git commit -am "A course title, not the name of its most central entity"
```

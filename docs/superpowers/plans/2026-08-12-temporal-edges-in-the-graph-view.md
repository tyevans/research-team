# Temporal Edges in the Graph View — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Draw the temporal extents extraction already writes onto entities, as computed edges on the graph canvas, visibly distinct from the edges the event log recorded.

**Architecture:** `redstring.infer_relations` is pure over entities the reader has already fetched, so the whole feature lives in `ProjectGraphReader` and adds no store round trip. The port learns a boolean and two strings; nothing above `GraphReadPort` ever names a redstring type. The wire and the browser carry the same distinction through to a dashed line the reader can hover for the arithmetic.

**Tech Stack:** Python 3.12 / FastAPI / pydantic / pytest / redstring; React 19 / TypeScript / zod / zustand / react-force-graph-2d / vitest.

**Spec:** `docs/superpowers/specs/2026-08-12-temporal-edges-in-the-graph-view-design.md`

## Global Constraints

- **Four gates, and passing three is not passing.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository, not the files you touched.
- **Never run two vitest processes at once.** Concurrent runs fail spuriously with a coverage temp-file error naming nothing about the real cause.
- **No `redstring.<dotted.path>` imports anywhere under `research_team/`.** Only names in `redstring.__all__`. Task 2 adds the test that enforces this; do not defeat it.
- **`redstring.__all__` provides:** `TemporalExtent`, `TemporalRelation`, `DatePrecision`, `UncertaintyMarker`, `infer_relations`, `InferredRelation`, `Entity`, `InMemoryGraphStore`. It does **not** provide `render_temporal` or `INFERRED_RELATIONS`.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on. A comment restating the code is worse than none.
- **Commit messages carry the reasoning that does not fit in a comment** — what was considered and rejected, what the change costs. `git log` is the design record here.
- **All `datetime` values on a `TemporalExtent` must be timezone-aware.** A naive one raises at construction.
- **Constants, exact values:** `MAX_GRAPH_NODES = 500`, `MAX_NEIGHBORHOOD_DEPTH = 2`, `MAX_INFERRED_EDGES = 2_000`.
- **Commit after every task.** Do not batch.

---

## File Structure

**Python — create:**
- `research_team/infrastructure/knowledge/temporal_rendering.py` — `_render_extent`'s home. Its own module rather than more lines in `graph_reader.py`: it is a pure text function with no store, no tenant and no async, and it needs the densest test of anything in this change (Task 1). `graph_reader.py` is already 200 lines of I/O reasoning.

**Python — modify:**
- `research_team/application/graph_read.py` — three new DTO fields, one new flag, one new constant.
- `research_team/infrastructure/knowledge/graph_reader.py` — `_DRAWN_RELATIONS`, `_inferred_edges`, the alias fix in `neighborhood`, the cap.
- `research_team/interfaces/web/presenters.py` — pass-through of four new fields.
- `tests/test_architecture.py` — the dotted-path rule.
- `tests/application/test_graph_read.py`, `tests/interfaces/test_web.py` — coverage.
- `tests/infrastructure/test_temporal_rendering.py` — created in Task 1.

**Frontend — modify:**
- `src/infrastructure/http/dto.ts`, `src/infrastructure/http/mappers.ts` — the wire fields.
- `src/domain/knowledge/graph.ts` — `GraphNode.temporal`, `GraphLink.inferred`/`derivation`, and the `linkKey` fix.
- `src/presentation/research/GraphCanvas.tsx` — dashed inferred edges, derivation on hover.
- `src/presentation/research/GraphLegend.tsx` — one line of prose.
- `src/styles/tokens.css`, `src/styles/research.css` — the two edge colours.

**Task order rationale:** Task 1 is pure and depends on nothing. Task 2 is a guard rail that must exist before the code it guards. Tasks 3–5 build the backend bottom-up. Task 6 is the wire. Tasks 7–9 are the browser, and Task 7 (`linkKey`) is a bug fix that stands alone.

---

### Task 1: `_render_extent`, and why it is not redstring's

**Files:**
- Create: `research_team/infrastructure/knowledge/temporal_rendering.py`
- Test: `tests/infrastructure/test_temporal_rendering.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `render_extent(extent: Any) -> str | None`. Public name (no leading underscore) because it crosses a module boundary into `graph_reader.py`. Returns `None` only when `extent` is `None` or `extent.is_empty`.

**Context you need:** `redstring.TemporalExtent` is a pydantic model with `start_date: datetime | None`, `end_date: datetime | None`, `precision: DatePrecision | None`, `uncertainty: UncertaintyMarker | None`, `original_text: str | None`, `sequence_position: int | None`, `publication_date: datetime | None`, and a property `is_empty`. `DatePrecision` has members `YEAR`, `MONTH`, `DAY` (check for others with `list(DatePrecision)` before assuming). Datetimes are timezone-aware.

- [ ] **Step 1: Write the failing test**

Create `tests/infrastructure/test_temporal_rendering.py`:

```python
"""`render_extent`: an extent as text a reader can check an edge against.

Deliberately not `redstring`'s `render_temporal`. That function exists for a
round-trip property and returns `None` for anything it cannot re-parse to an
identical extent -- which includes ordinary extraction output. The tests here
are mostly about the cases where the two disagree, because agreeing on the
easy ones is not what this function is for.
"""

from datetime import UTC, datetime

import pytest
from redstring import DatePrecision, TemporalExtent

from research_team.infrastructure.knowledge.temporal_rendering import render_extent


def test_the_original_text_is_preferred_to_any_reformatting():
    """What the document said, unimproved.

    Fails if the fallback formatter runs whenever it *can* rather than only
    when there is no source text -- which is the shape this most plausibly
    gets written as.
    """
    extent = TemporalExtent(
        start_date=datetime(1904, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
        original_text="the summer of 1904",
    )
    assert render_extent(extent) == "the summer of 1904"


def test_a_month_range_renders_though_redstring_declines_to():
    """The case that makes this a separate function rather than a re-export.

    `render_temporal` returns `None` here -- a month-precision *range* is not
    a form its parser accepts back -- and `None` from this function would mean
    "undated", so the date would vanish from the canvas with no error anywhere.
    """
    extent = TemporalExtent(
        start_date=datetime(1918, 3, 1, tzinfo=UTC),
        end_date=datetime(1918, 11, 1, tzinfo=UTC),
        precision=DatePrecision.MONTH,
    )
    rendered = render_extent(extent)
    assert rendered is not None
    assert "1918" in rendered


def test_a_publication_date_does_not_suppress_the_rendering():
    """Second case `render_temporal` declines. Same failure, same reason."""
    extent = TemporalExtent(
        start_date=datetime(1904, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
        publication_date=datetime(1990, 1, 1, tzinfo=UTC),
    )
    assert render_extent(extent) == "1904"


def test_a_year_renders_as_the_year_alone():
    extent = TemporalExtent(
        start_date=datetime(1904, 1, 1, tzinfo=UTC), precision=DatePrecision.YEAR
    )
    assert render_extent(extent) == "1904"


def test_a_year_range_renders_as_a_span():
    extent = TemporalExtent(
        start_date=datetime(1990, 1, 1, tzinfo=UTC),
        end_date=datetime(1995, 1, 1, tzinfo=UTC),
        precision=DatePrecision.YEAR,
    )
    assert render_extent(extent) == "1990-1995"


def test_dates_with_no_precision_still_render():
    """Precision is optional on the model, so it is optional here.

    Returning `None` for a dated extent because one *descriptive* field is
    absent would hide a date the graph is drawing an edge from.
    """
    extent = TemporalExtent(start_date=datetime(1904, 6, 15, tzinfo=UTC))
    rendered = render_extent(extent)
    assert rendered is not None
    assert "1904" in rendered


@pytest.mark.parametrize(
    ("extent", "case"),
    [
        (None, "absent"),
        (TemporalExtent(), "empty"),
        (TemporalExtent(sequence_position=3), "ordered but undated"),
    ],
)
def test_only_an_undated_extent_renders_as_none(extent, case):
    """`None` means undated and nothing else.

    `sequence_position` alone is what `infer_relations` itself treats as
    undated, so the two agree about which entities take no part.
    """
    assert render_extent(extent) is None, case
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/infrastructure/test_temporal_rendering.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'research_team.infrastructure.knowledge.temporal_rendering'`.

- [ ] **Step 3: Confirm the premise before implementing**

The whole justification for this module is that `render_temporal` returns
`None` for these inputs. Verify it rather than trusting the plan:

```bash
uv run python -c "
from datetime import UTC, datetime
from redstring import DatePrecision, TemporalExtent
from redstring.domain.temporal_parsing import render_temporal
print(repr(render_temporal(TemporalExtent(
    start_date=datetime(1918,3,1,tzinfo=UTC),
    end_date=datetime(1918,11,1,tzinfo=UTC),
    precision=DatePrecision.MONTH))))
print(list(DatePrecision))
"
```

Expected: `None`, then the `DatePrecision` members. If the first line is not
`None`, **stop and report** — the spec's central claim is wrong and the module
should not be written.

- [ ] **Step 4: Write the implementation**

Create `research_team/infrastructure/knowledge/temporal_rendering.py`. Write the module docstring and `render_extent` yourself from the spec's §3 reasoning. Required behaviour:

1. `None` when `extent is None` or `extent.is_empty`.
2. `original_text` when set and non-blank, returned unchanged.
3. `None` when there is no `start_date` (an extent holding only `sequence_position` or `uncertainty` has nothing to render).
4. Otherwise format from `start_date`/`end_date` by `precision`: `YEAR` → `"1904"` / `"1990-1995"`; `MONTH` → `"March 1918"` / `"March 1918-November 1918"`; `DAY` → `"15 June 1904"`; absent precision → ISO date. Join a range with `-`.

Do not import from `redstring.domain.*`. The parameter is typed `Any` for the same reason `graph_reader.py`'s helpers are.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/infrastructure/test_temporal_rendering.py -q`
Expected: 8 passed.

- [ ] **Step 6: Prove the tests red before trusting them green**

Temporarily make `render_extent` return `extent.original_text` and nothing else. Run the suite: `test_a_month_range_renders_though_redstring_declines_to`, `test_a_year_renders_as_the_year_alone` and `test_a_year_range_renders_as_a_span` must fail. Revert.

- [ ] **Step 7: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
git add research_team/infrastructure/knowledge/temporal_rendering.py tests/infrastructure/test_temporal_rendering.py
git commit
```

Commit message must say why this is not `render_temporal` — the round-trip contract, and that a wrong answer here is silent because `None` already means undated.

---

### Task 2: The dotted-path rule

**Files:**
- Modify: `tests/test_architecture.py`

**Interfaces:**
- Consumes: nothing.
- Produces: nothing importable. A guard rail Tasks 3–5 must not trip.

**Context you need:** `tests/test_architecture.py` has `_imported_roots(module)`, which reduces every import to its root package with `.split(".")[0]` — deliberately, since the existing rule is about which *frameworks* a layer may name. So `from redstring.domain.x import y` reads as `redstring` and passes every existing case. You need a **new** helper that keeps the full dotted path. `ALL_MODULES` is a module-level list of `(layer, module_path)` pairs over `research_team/` only, and is what you parametrize over. The rule applies to `research_team/` only — `tests/application/test_graph_read.py` imports `redstring.domain.entity` to build fixtures and must stay legal.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_architecture.py`:

```python
def _imported_paths(module: Path) -> set[str]:
    """Every absolute import, at full dotted length.

    `_imported_roots` truncates to the root package, which is right for the
    framework rule and blind to the one below: `redstring.domain.x` and
    `redstring` are the same string to it, and the whole point here is that
    they are not the same import.
    """
    tree = ast.parse(module.read_text())
    paths: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            paths.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            paths.add(node.module)
    return paths


@pytest.mark.parametrize(
    ("layer", "module"),
    ALL_MODULES,
    ids=[f"{layer}/{module.name}" for layer, module in ALL_MODULES],
)
def test_redstring_is_named_only_through_its_public_surface(layer: str, module: Path) -> None:
    """`redstring`, never `redstring.something`.

    redstring's contract is that anything reached by a dotted path is internal
    and may change in a patch release -- so a dotted import is a dependency on
    a private API that a *patch* bump can break, silently, in a package this
    repository pins below the next minor precisely because it moves.

    The concrete near-miss: `render_temporal` lives at
    `redstring.domain.temporal_parsing` and is not exported. It is the
    obvious-looking way to render a temporal extent and the wrong one
    (`temporal_rendering.py` says why), and without this rule reaching for it
    passes every other test in this file.

    Scoped to `research_team/` deliberately. `tests/` builds redstring
    fixtures through dotted paths and stays free to: a test constructing an
    `Entity` is not shipping against a private API.
    """
    offenders = {path for path in _imported_paths(module) if path.startswith("redstring.")}
    assert not offenders, (
        f"{module.relative_to(PACKAGE)} imports redstring internals: {offenders}; "
        "use the package's public surface"
    )
```

- [ ] **Step 2: Run it to verify it passes, then prove it can fail**

Run: `uv run pytest tests/test_architecture.py -q` → all pass (nothing violates it yet).

A test that has never been red is not yet evidence. Temporarily add `from redstring.domain.entity import Entity` to `research_team/infrastructure/knowledge/graph_reader.py`, re-run, and confirm **exactly one** case fails, naming `graph_reader.py`. Then remove it.

- [ ] **Step 3: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
git add tests/test_architecture.py
git commit
```

Message: the rule exists before the code it guards, and names the near-miss it was written for.

---

### Task 3: The port DTOs

**Files:**
- Modify: `research_team/application/graph_read.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `GraphEntity.temporal: str | None = None`; `GraphRelationship.inferred: bool = False`; `GraphRelationship.derivation: str | None = None`; `Graph.inferred_truncated: bool = False`; `MAX_INFERRED_EDGES = 2_000`.

**Context you need:** These are frozen dataclasses, not pydantic. Every new field is defaulted so existing construction sites keep working. `Neighborhood` deliberately does **not** get `inferred_truncated` — see the spec. Docstring text for each field is given in the spec's §1 and should be used close to verbatim; it is the reasoning, not decoration.

- [ ] **Step 1: Write the failing test**

Add to `tests/application/test_graph_read.py`:

```python
def test_a_relationship_is_asserted_unless_it_says_otherwise():
    """The default is the safe one.

    Every existing construction site omits these fields, so a default of
    `True` -- or a required argument -- would relabel every stored edge in the
    application as inferred. The flag's whole job is telling those apart.
    """
    edge = GraphRelationship(source_id="a", target_id="b", relationship_type="advised")
    assert edge.inferred is False
    assert edge.derivation is None


def test_an_entity_is_undated_unless_it_says_otherwise():
    node = GraphEntity(entity_id="a", name="Prandtl", entity_type="person")
    assert node.temporal is None


def test_a_graph_reports_its_two_truncations_separately():
    """`truncated` is about entities; `inferred_truncated` is about lines.

    One flag for both would tell a reader that nodes are missing when every
    node is present, and send them looking for entities that are all there.
    """
    graph = Graph(entities=(), relationships=(), truncated=True)
    assert graph.inferred_truncated is False
```

Extend the existing import from `research_team.application.graph_read` to cover `Graph`, `GraphEntity`, `GraphRelationship` and `MAX_INFERRED_EDGES`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/application/test_graph_read.py -q`
Expected: `ImportError` for `MAX_INFERRED_EDGES`, then `TypeError: unexpected keyword argument` / `AttributeError` on the new fields.

- [ ] **Step 3: Implement**

Add the fields with the spec's §1 docstrings, and `MAX_INFERRED_EDGES = 2_000` with the spec's §5 comment. Add the spec's §6 note to the existing `MAX_GRAPH_NODES` comment: `infer_relations` refuses above 500,000 pairs, 500 entities is at most 124,750, and raising this cap past ~1,000 makes that refusal reachable.

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/application/test_graph_read.py -q` → all pass.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
git add research_team/application/graph_read.py tests/application/test_graph_read.py
git commit
```

---

### Task 4: Aliases in `neighborhood`

**Files:**
- Modify: `research_team/infrastructure/knowledge/graph_reader.py`
- Test: `tests/application/test_graph_read.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `neighborhood` no longer returns absorbed entities.

**Context you need:** This is a standalone bug fix and is sequenced *before* inference so its test cannot be satisfied by inference behaviour. `ProjectGraphReader._without_aliases(entities)` already exists (`graph_reader.py`, ~line 56) and is what `whole` uses. `neighborhood` currently calls `self._store.neighbors(...)` and passes the result straight through. Apply the filter to `neighbors` **before** `entity_ids` is built, so the edge filter's `returned_ids` narrows with it. Keep it inside the existing `tenant_scope` block. `InMemoryGraphStore` merges via `merge_entities`; see `test_an_entity_merged_away_is_not_drawn_as_its_own_node` (~line 236) for how the existing test seeds a merge, and copy that mechanism.

- [ ] **Step 1: Write the failing test**

```python
async def test_an_entity_merged_away_is_not_drawn_in_a_neighborhood(graph_reader):
    """What `whole` has always done, which `neighborhood` never did.

    `GraphStore.neighbors` returns absorbed entities as well as canonical ones
    -- a merge is not a delete, because the row is what `undo_merge` restores.
    Passed through, a *correctly* consolidated pair draws as two nodes: the
    canonical one carrying every edge, and the alias beside it with none,
    because the merge redirected them. An isolated node bearing a name already
    on the canvas is precisely the duplicate a reader reports.

    Fails against the code as it was: the alias came back in `entities`.
    """
```

Seed a root, a canonical entity related to it, and an alias merged into that canonical entity. Assert the alias's id is absent from `{e.entity_id for e in hood.entities}` and from every relationship endpoint.

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/application/test_graph_read.py -k merged_away_is_not_drawn_in_a_neighborhood -q`
Expected: FAIL — the alias is present.

**If it passes, stop.** Either the seeding did not create a merge or `neighbors` already filters; investigate before writing code, because the fix would then be unnecessary and the test would be evidence about the fixture.

- [ ] **Step 3: Implement**

In `neighborhood`, inside the `tenant_scope` block:

```python
            neighbors = await self._store.neighbors(
                root_id, self._project_id, depth=capped_depth
            )
            # Absorbed entities dropped here, as `whole` already drops them --
            # see `_without_aliases`. Costs one `resolve_entity_ids` round trip
            # per read, which is what `whole` already pays.
            neighbors = await self._without_aliases(list(neighbors))
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/application/test_graph_read.py -q` → all pass, including the existing neighborhood tests.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
git add research_team/infrastructure/knowledge/graph_reader.py tests/application/test_graph_read.py
git commit
```

Message: a pre-existing inconsistency with `whole`, fixed now because the temporal edge about to be added would turn it into a node wired to itself.

---

### Task 5: The adapter computes inferred edges

**Files:**
- Modify: `research_team/infrastructure/knowledge/graph_reader.py`
- Test: `tests/application/test_graph_read.py`

**Interfaces:**
- Consumes: `render_extent` (Task 1); the `GraphRelationship`/`Graph` fields and `MAX_INFERRED_EDGES` (Task 3); the alias fix (Task 4).
- Produces: `Graph.relationships` and `Neighborhood.relationships` now carry inferred edges; `Graph.inferred_truncated` is populated.

**Context you need:**

`infer_relations(entities, *, relations=..., max_pairs=500_000) -> list[InferredRelation]`, where `InferredRelation` is a `NamedTuple` with fields `source_entity_id`, `target_entity_id`, `relation` (a `TemporalRelation`), `source_name`, `target_name`, `source_extent`, `target_extent`. Undated members take no part rather than being an error. The result is sorted and deterministic, with no duplicates and no inverses.

`TemporalRelation` has six members but `infer_relations` only ever emits four: it canonicalises each pair to one edge, so an `AFTER` arrives as its target's `BEFORE` and a `DURING` as its target's `CONTAINS`. Drawing `{CONTAINS, OVERLAPS, EQUALS}` is therefore complete, not a subset needing `AFTER`/`DURING` added.

The existing `Entity` fixture helper `_entity(...)` in the test file takes no extent — extend it with a `temporal=None` keyword argument rather than writing a second helper.

- [ ] **Step 1: Write the failing tests**

Add to `tests/application/test_graph_read.py`. All five are required; each rules out a different wrong implementation.

```python
async def test_a_temporal_edge_appears_between_entities_the_store_never_related(...):
    """Inference ran, as opposed to a stored edge acquiring a flag.

    The pair here has *no* stored relationship, which is what makes that
    distinction checkable: an implementation that only labelled stored edges
    produces nothing at all for this pair.

    The extents are a year and a month inside it, so the relation is
    `CONTAINS`. Two identical extents would give `EQUALS`, which would also
    appear under an implementation that never compared anything and simply
    paired every dated entity up.
    """


async def test_a_stored_edge_between_the_same_pair_is_still_asserted(...):
    """The other half of the pair above. Same two entities, related in the
    store as well -- the stored edge must come back with `inferred=False` and
    no derivation, alongside the computed one rather than instead of it."""


async def test_before_is_not_drawn(...):
    """Two disjoint dated entities produce no edge at all.

    `_DRAWN_RELATIONS` is the only thing keeping the drawing legible -- 100
    dated entities is on the order of 4,950 `BEFORE` edges against at most 500
    nodes, and a force-directed layout given that resolves to a solid disc. An
    exemption nobody checks stops holding silently.
    """


async def test_undated_entities_are_drawn_and_take_no_part(...):
    """One entity with no extent and one with an empty one: both present as
    nodes, both absent from every inferred edge. Most entities in a real graph
    are not events, so this is the ordinary case rather than the edge case."""


async def test_a_merged_pair_infers_no_edge_to_itself(...):
    """The alias fix and inference, together, in `neighborhood`.

    Inference knows nothing about merges and an absorbed entity keeps its own
    `temporal`, so without Task 4 a canonical entity and its own alias produce
    an `EQUALS` between what is really one thing -- a duplicate node wired to
    itself. Reverting Task 4 turns this red.
    """
```

Give each a body. Fixtures: build `Entity` objects with `temporal=TemporalExtent(...)`, timezone-aware, seeded through `store.upsert_entities` as the file already does.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/application/test_graph_read.py -q`
Expected: the four inference tests fail (no inferred edges anywhere); `test_undated_entities_are_drawn_and_take_no_part` may pass vacuously — that is expected and it is guarding against a later regression.

- [ ] **Step 3: Implement**

In `graph_reader.py`: add `from redstring import TemporalRelation, infer_relations` and `from research_team.infrastructure.knowledge.temporal_rendering import render_extent`; add `_DRAWN_RELATIONS` with the spec's §2 comment in full (it is the reasoning for the densest decision in the change); add `_inferred_edges(entities) -> tuple[GraphRelationship, ...]` per the spec, applying `MAX_INFERRED_EDGES`.

Return the cap's verdict alongside the edges rather than recomputing it — a helper returning `tuple[tuple[GraphRelationship, ...], bool]` is fine and is better than a caller re-deriving "was it capped" from a length comparison, which is the same off-by-one `whole`'s truncation test already documents.

Wire into `whole` (over `kept`, populating `inferred_truncated`) and `neighborhood` (over `[root, *neighbors]`, discarding the flag — see the spec on why `Neighborhood` has none).

`_to_graph_entity` gains `temporal=render_extent(entity.temporal)`. Use `getattr(entity, "temporal", None)` only if a fixture without the attribute makes that necessary; prefer the direct attribute.

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/application/test_graph_read.py -q` → all pass.

- [ ] **Step 5: Prove the tests red before trusting them green**

Delete the `_inferred_edges` call from `whole` and run the suite. At least `test_a_temporal_edge_appears_between_entities_the_store_never_related` must fail. Restore it. A test that stays green under a deliberate break is evidence about the fixture, not about the code.

- [ ] **Step 6: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
git add research_team/infrastructure/knowledge/graph_reader.py tests/application/test_graph_read.py
git commit
```

Message: why `BEFORE` is out and why `AFTER`/`DURING` need no exemption; that inference adds no store round trip; what the cap protects against.

---

### Task 6: The wire

**Files:**
- Modify: `research_team/interfaces/web/presenters.py`
- Test: `tests/interfaces/test_web.py`

**Interfaces:**
- Consumes: the port fields (Task 3), populated by the adapter (Task 5).
- Produces: JSON keys `temporal` on each entity; `inferred` and `derivation` on each relationship; `inferred_truncated` on the whole-graph body. Task 7 onward depends on these exact snake_case names.

**Context you need:** `presenters.py` returns plain `dict[str, Any]` — no pydantic response models anywhere. `entity_view` (~line 713) and `relationship_view` (~line 722) are used by `graph_view`, `neighborhood_view` and `entity_page_view` alike, so editing the two leaf functions covers all three routes. There are no graph cases in `tests/interfaces/test_presenters.py`; assert the wire shape in `tests/interfaces/test_web.py`, where the graph routes are already tested (~lines 3343-3570), rather than adding a second place for it to drift.

- [ ] **Step 1: Write the failing test**

In `tests/interfaces/test_web.py`, near the existing graph route tests, assert against `/api/projects/{id}/graph` for a project seeded with two dated entities in a containment: the body's `entities` carry `temporal`, an inferred relationship carries `inferred: true` and a non-null `derivation`, and the body carries `inferred_truncated: false`.

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/interfaces/test_web.py -k graph -q`
Expected: `KeyError` on the new keys.

- [ ] **Step 3: Implement**

Add the fields to `entity_view`, `relationship_view` and `graph_view` as straight pass-throughs. `neighborhood_view` needs no change beyond what the leaf functions give it — confirm that by reading it rather than assuming.

- [ ] **Step 4: Run to verify passing**

Run: `uv run pytest tests/interfaces/test_web.py -k graph -q` → all pass.

- [ ] **Step 5: Gates and commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest -q
git add research_team/interfaces/web/presenters.py tests/interfaces/test_web.py
git commit
```

---

### Task 7: `linkKey` keeps both claims

**Files:**
- Modify: `frontend/src/domain/knowledge/graph.ts`
- Test: `frontend/src/domain/knowledge/graph.test.ts`

**Interfaces:**
- Consumes: nothing (pure frontend, independent of the backend tasks).
- Produces: `GraphLink.inferred?: boolean`, `GraphLink.derivation?: string | null`, `GraphNode.temporal?: string | null`; `linkKey` includes `inferred`.

**Context you need:** `linkKey` is a module-private function in `graph.ts`, currently `` `${link.source}|${link.target}|${link.relationshipType}` ``. It is used by `expand` (and by `loadWhole`/`remove` — check each) to deduplicate links. An asserted `contains` and an inferred `CONTAINS` between the same pair currently produce the same key, so one silently displaces the other by arrival order. They are different claims — the premise of the `inferred` flag — and the merge must keep both. The existing docstring already argues why the key is directed rather than unordered; extend that argument by one field rather than replacing it.

Fields are optional (`?`) rather than required because every existing test constructs `GraphLink` literals without them.

- [ ] **Step 1: Write the failing test**

```ts
it('keeps an asserted and an inferred edge between the same pair', () => {
  // Same two ends and the same type -- the case the old key collapsed. They
  // are different claims: one is what a document said, the other is
  // arithmetic over two dates that changes on re-extraction. Dropping either
  // silently is the failure; which one survived depended on arrival order.
})
```

Merge a neighborhood carrying both into an empty view via `expand`, and assert `view.links` has length 2.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/domain/knowledge/graph.test.ts`
Expected: FAIL, received length 1. **Run nothing else concurrently.**

- [ ] **Step 3: Implement**

Add the three interface fields, then extend `linkKey` to include `inferred`. Normalise it (`link.inferred === true`) so `undefined` and `false` produce the same key and an existing link does not duplicate itself on re-merge.

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npx vitest run src/domain/knowledge/graph.test.ts` → all pass.

- [ ] **Step 5: Commit**

```bash
cd frontend && npm run verify
git add frontend/src/domain/knowledge/graph.ts frontend/src/domain/knowledge/graph.test.ts
git commit
```

Message: the collision, why both must survive, and that the fix is one field on an existing key rather than a new merge strategy.

---

### Task 8: The DTOs and mappers

**Files:**
- Modify: `frontend/src/infrastructure/http/dto.ts`, `frontend/src/infrastructure/http/mappers.ts`
- Test: `frontend/src/infrastructure/http/mappers.test.ts`

**Interfaces:**
- Consumes: the wire keys (Task 6); the domain fields (Task 7).
- Produces: `toGraphNode` sets `temporal`; `toGraphLink` sets `inferred` and `derivation`; `toWholeGraph` sets `inferredTruncated`.

**Context you need:** `dto.ts` mirrors `presenters.py` verbatim in snake_case (its docstring says so). `graphEntityDto`/`graphRelationshipDto`/`graphWholeDto` are at ~lines 622-655; mappers at ~lines 611-633. `graphWholeDto` declares `truncated: z.boolean().default(false)` — match that style for `inferred_truncated`. Nullable string fields should be `z.string().nullable().default(null)`, so a body written before these fields existed still parses.

`WholeGraph` in `graph.ts` needs `inferredTruncated: boolean` — add it there in this task, not Task 7, since nothing before now produces it.

- [ ] **Step 1: Write the failing test**

In `mappers.test.ts`, assert `toGraphLink` carries `inferred`/`derivation` through, `toGraphNode` carries `temporal`, and `toWholeGraph` carries `inferredTruncated`.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/infrastructure/http/mappers.test.ts`
Expected: FAIL — properties undefined.

- [ ] **Step 3: Implement** — the zod fields, the mapper fields, and `WholeGraph.inferredTruncated`.

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npx vitest run src/infrastructure/http/mappers.test.ts` → pass.

- [ ] **Step 5: Verify and commit**

```bash
cd frontend && npm run verify
git add frontend/src/infrastructure/http/ frontend/src/domain/knowledge/graph.ts
git commit
```

If `npm run verify` fails on the graph store or `GraphPane` because `WholeGraph` gained a required field, fix the construction sites it names — that is the type system doing its job, not a scope increase.

---

### Task 9: The drawing

**Files:**
- Modify: `frontend/src/presentation/research/GraphCanvas.tsx`, `frontend/src/presentation/research/GraphLegend.tsx`, `frontend/src/styles/tokens.css`, `frontend/src/styles/research.css`
- Test: `frontend/src/presentation/research/GraphLegend.test.tsx`

**Interfaces:**
- Consumes: `GraphLink.inferred`/`derivation` (Tasks 7-8).
- Produces: the feature, visible.

**Context you need:** `GraphCanvas.tsx` is the only module importing `react-force-graph-2d`. Edges are **not** custom-painted — only nodes are. Edge appearance is four props at ~lines 230-233:

```tsx
linkLabel={(link) => String(link.relationshipType)}
linkDirectionalArrowLength={4}
linkColor={() => 'rgba(138, 149, 163, 0.35)'}
```

`linkColor` is the one colour on this canvas inlined rather than read from `tokens.css`. Making it branch on `inferred` means two literals where there was one, so both move to tokens in this task rather than doubling the exception. Read the surrounding colour code (`entity-colors.ts`, and the `getComputedStyle` pattern in `GraphLegend.tsx`) and follow it.

`linkLineDash` is the dash-pattern prop. Verified against the installed version's types — `react-force-graph-2d/dist/react-force-graph-2d.d.ts:75` declares it `LinkAccessor<NodeType, LinkType, number[] | null>`, so it takes an accessor and `null` means a solid line. No custom `linkCanvasObject` is needed and none should be written.

Dashed rather than a different hue: colour on this canvas already means entity type, and the node painter's own comment gives the rule — overriding a channel that carries a fact trades one fact for another instead of adding one. The dimming is a change of alpha within the same colour.

`GraphLegend.tsx` ends with a conditional prose note about hollow nodes. Add a sibling for inferred edges on exactly the same terms: prose, not a swatch, and withheld when the view contains no inferred edge, because a key explaining a mark that is not on the canvas sends the reader hunting for one.

- [ ] **Step 1: Write the failing test**

In `GraphLegend.test.tsx`, two cases: the note is present when `view.links` contains an inferred link, and absent when none do. Assert on the rendered text, which jsdom can judge.

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/research/GraphLegend.test.tsx`
Expected: FAIL — text not found.

- [ ] **Step 3: Implement**

The legend note; the two colour tokens; `linkColor`, `linkLineDash` and `linkLabel` as accessors branching on `link.inferred`. `linkLabel` returns `derivation` for an inferred edge and `relationshipType` otherwise — hovering a temporal line should show the arithmetic, not restate the word the dashes already imply.

- [ ] **Step 4: Run to verify passing**

Run: `cd frontend && npx vitest run src/presentation/research/` → pass.

- [ ] **Step 5: Note the deliberate gap**

The dash pattern is a canvas drawing operation and is not asserted: jsdom paints nothing, and a browser-mode test screenshotting a `<canvas>` would be asserting on pixels. Say so in a comment in `GraphCanvas.tsx` so the gap is a decision rather than an oversight.

- [ ] **Step 6: Full verification and commit**

```bash
cd frontend && npm run verify
cd .. && uv run ruff check . && uv run ruff format --check . && uv run pytest -q
git add frontend/src/presentation/research/ frontend/src/styles/
git commit
```

---

### Task 10: All four gates, together

**Files:** none necessarily.

- [ ] **Step 1: Run every gate from the repository root, in order**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
cd frontend && npm run verify
```

All four. Passing three is not passing, and the two ruff commands cover the whole repository rather than the files this change touched — an unsorted import in a new *test* file fails CI while `pytest` and `npm run verify` both stay green.

- [ ] **Step 2: Fix anything red, commit the fix, re-run the full set.**

- [ ] **Step 3: Report** — the four commands and their results, then the branch name and commit list.

---

## Self-Review

**Spec coverage.** §1 → Task 3. §2 → Task 5. §3 → Tasks 1, 2. §4 → Task 4. §5 → Tasks 3, 5. §6 → Task 3. §7 → Tasks 6, 7, 8, 9. §8 → distributed across each task's own test step, plus Task 10.

**Placeholders.** None. Task 1 Step 4, Task 5 Step 3 and Task 9 Step 3 describe behaviour rather than pasting a finished body — deliberate, because each is prose-heavy code whose comments *are* the deliverable, and every one of them is pinned by a test written in the preceding step.

**Type consistency.** `render_extent` (public, no underscore) is named identically in Tasks 1 and 5. `MAX_INFERRED_EDGES` is `2_000` in the constraints, Task 3 and the spec. `inferred_truncated` (Python/wire) maps to `inferredTruncated` (TS) — introduced in Task 3, serialized in Task 6, consumed in Task 8; the case change is the existing snake/camel convention at the mapper boundary, and no other field crosses it.

**Risks checked rather than assumed:** Task 9's `linkLineDash` and Task 1's claim that `render_temporal` returns `None` for a month range were both the kind of assumption that fails late. The first is verified against the installed types above; the second is Task 1 Step 3, which stops the task if the premise turns out false.

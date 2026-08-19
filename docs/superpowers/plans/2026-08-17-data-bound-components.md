# Data-bound Components Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add five *resolved* component types — `definition`, `evidence`, `graph`, `timeline`, `compare` — which carry a reference in their YAML body and fetch the project's own data in the browser.

**Architecture:** `ComponentType` gains a `resolved: bool` flag. Resolved types withhold nothing, grade nothing, and `project()` is identity for them in both views. The registry validates *shape only* — it cannot check that a referenced entity exists, and must not pretend to. Resolution happens in the browser: `useEntityReference` turns `{entity, entity_id}` into a discriminated union over four states, and `<ResolvedFrame>` renders the three non-resolved ones uniformly so five widgets cannot drift into five different ways of saying "not found".

**Tech Stack:** Python 3 / FastAPI / PyYAML on the server; React 19 + TypeScript + TanStack Query + Zod + Vitest (jsdom and Chromium browser mode) on the client.

**Spec:** `docs/superpowers/specs/2026-08-17-data-bound-components-design.md`

## Global Constraints

Copied from CLAUDE.md and the spec's §5. Every task's requirements implicitly include this section.

- **Four gates, and passing three is not passing.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The two ruff commands run over the whole repository, not the files you touched.
- **The committed console is a fifth gate.** `research_team/interfaces/web/static` is a build artefact committed to the repository, and CI fails if `npm run build` produces drift. `npm run verify` runs the build and never compares its output. **Any task touching `frontend/src` ends with `cd frontend && npm run build` and a commit of the rebuilt `research_team/interfaces/web/static/assets/app.js` and `assets/index.css`.**
- **Do not run two `vitest` processes at once.** Concurrent runs fail spuriously with a coverage temp-file error that names nothing about the real cause.
- **`npm run test:browser` is not in `verify` and not in CI.** Run it by hand for anything whose correctness is a computed style or a measurement. Tasks 5 and 6 require it.
- **`border-solid` beside one directional width draws three unwanted sides.** Pair `border-0` with the directional width, or use the directional width alone (Tailwind v4 emits solid by default in this build).
- **An unlayered rule in `tokens.css` beats any utility.** Before overriding anything declared there with a utility, check whether the rule is layered. `:focus-visible` is not.
- **`MAX_NEIGHBORHOOD_DEPTH = 2`** (`research_team/application/graph_read.py:47`).
- **`MAX_TIMELINE_BANDS = 1_000`** (`research_team/application/timeline_read.py:31`).
- **Commit messages carry reasoning.** What was considered and rejected, what the change costs, what is deliberately left undone. `git log` is a design record here.
- **If a test would pass with the change reverted, say so in its docstring.** Proving a test red before trusting it green is the convention.

## File Structure

**Server (Python).**

- `research_team/application/components.py` — modified. Gains `ComponentType.resolved`, two new checkers (`integer_between`, `string_list`), the five registry entries (one per widget task), and the `_component_json` change that carries `resolved` onto the wire.
- `research_team/application/ask_components.py` — modified in Task 8. `ASK_COMPONENT_TYPES` gains all five.
- `tests/application/test_components.py` — modified. One section per new type.
- `tests/application/test_resolved_components.py` — created in Task 1. The properties that hold across *all* resolved types: identity projection in both views, `withheld` empty, `gradeable` false, validation accepts a reference that cannot exist.
- `tests/application/test_ask_components.py` — modified in Task 8.

**Client (TypeScript).** Files that change together live together, so each widget's reader, renderer and test sit beside the widget it serves.

- `frontend/src/domain/lesson/resolved.ts` — created in Task 2. The `EntityReference`/`ResolvedEntity` types and the pure `matchEntities` fold. Pure, no React, no fetching — testable without a DOM, which is what makes the "exact match beats substring" rule provable.
- `frontend/src/application/lesson/use-entity-reference.ts` — created in Task 2. The TanStack Query hook.
- `frontend/src/presentation/lesson/ResolvedFrame.tsx` — created in Task 2.
- `frontend/src/domain/lesson/widgets.ts` — modified per widget task. One `read*` per new type, in the existing defaulting idiom.
- `frontend/src/presentation/lesson/{DefinitionWidget,EvidenceWidget,GraphWidget,TimelineWidget,CompareWidget}.tsx` — one per widget task.
- `frontend/src/presentation/lesson/LessonDocument.tsx` — modified in Task 2 (signature + threading) and once per widget task (a `RENDERERS` line).
- `frontend/src/styles/components.css` — modified per widget task.
- `frontend/src/application/queries/keys.ts` — modified in Tasks 2, 4, 6.
- `frontend/src/infrastructure/http/timeline-repository.ts` and `frontend/src/application/ports/repositories.ts` — modified in Task 6 to widen `timeline()`.

---

### Task 1: The `resolved` flag, and the properties that hold across every resolved type

Adds the registry field and the two new checkers the later widget tasks need, and pins the class-wide properties *before* any type exists to exercise them. The tests register a throwaway type into `REGISTRY` via `monkeypatch` rather than waiting for `definition`: a property that holds "for every resolved type" should be stated over the class, not over whichever member happened to land first.

**Files:**
- Modify: `research_team/application/components.py` (add `resolved` to `ComponentType` near :339; add `integer_between` and `string_list` after `one_of` at :240; add `"resolved"` to `_component_json`'s output at :913)
- Create: `tests/application/test_resolved_components.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ComponentType.resolved: bool = False`
  - `integer_between(low: int, high: int) -> Checker`
  - `string_list(minimum: int = 1) -> Checker`
  - `_component_json` output gains `"resolved": bool` on every component block, which the client DTO reads in Task 2.

- [ ] **Step 1: Write the failing test**

Create `tests/application/test_resolved_components.py`:

```python
"""What holds for every resolved component, stated over the class.

A resolved component carries a *reference* and fetches its data in the
browser. Structurally it is the inverse of `gradeable`: nothing is withheld,
nothing is graded, and the YAML body is a query rather than content.

These tests register a throwaway type rather than asserting against
`definition` or `graph`, because the claim is about the class. A test written
against one member passes for a build where a second member quietly grew a
`strip`, which is exactly the regression worth catching -- see the module
docstring on `components.py` for why "the learner projection is identity" is
the kind of property that stops holding silently.
"""

import pytest

from research_team.application.components import (
    REGISTRY,
    ComponentType,
    Spec,
    integer_between,
    parse_document,
    project,
    string_list,
    text,
    validation_report,
)

PROBE = """\\
```component:probe
id: p1
entity: An Entity No Extraction Has Ever Seen
```
"""


@pytest.fixture
def probe(monkeypatch):
    """A resolved type that exists only for the duration of one test.

    `monkeypatch.setitem` restores the registry afterwards, so a failure here
    cannot leak a fake type into another test's `component_reference()`.
    """
    monkeypatch.setitem(
        REGISTRY,
        "probe",
        ComponentType(
            name="probe",
            version=1,
            summary="A probe.",
            example="```component:probe\nid: p1\nentity: Something\n```",
            fields={"entity": Spec(text, required=True)},
            resolved=True,
        ),
    )
    return REGISTRY["probe"]


def test_a_resolved_type_withholds_nothing_and_grades_nothing(probe):
    """Both are defaults on `ComponentType`, so this is red only against a
    build where someone gave a resolved type an answer key -- which is the
    point: there is no answer to withhold, the data is the project's own."""
    assert probe.withheld == ()
    assert probe.gradeable is False
    assert probe.strip is None


def test_the_learner_projection_of_a_resolved_component_is_identity(probe):
    """The property `components.py`'s docstring warns stops holding silently.

    Red against a build that gives a resolved type a `strip`, and red against
    one that projects `withheld` non-empty for it.
    """
    document = parse_document(PROBE, path="probe.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert author["data"] == learner["data"]
    assert learner["withheld"] == []
    assert learner["gradeable"] is False


def test_a_resolved_component_says_so_on_the_wire(probe):
    """The client decides whether to thread `projectId` into a renderer on
    this flag rather than on a name list. Red against a `_component_json`
    that does not carry it."""
    block = project(parse_document(PROBE, path="probe.md"))["blocks"][0]

    assert block["resolved"] is True


def test_a_self_contained_component_is_not_resolved():
    """The other half of the flag, so a build that hardcodes `True` fails."""
    source = (
        "```component:flashcards\n"
        "id: deck\n"
        "cards:\n"
        "  - front: a\n"
        "    back: b\n"
        "```\n"
    )

    block = project(parse_document(source))["blocks"][0]

    assert block["resolved"] is False


def test_validation_accepts_a_reference_that_cannot_possibly_exist(probe):
    """The honest assertion, and the one the spec's section 2 asks for by name.

    `validation_report` runs on the server at parse time with no graph handle,
    so a name matching nothing is a *render* state and not a parse error. The
    natural instinct is to add an existence check to the validator; it cannot
    be written honestly, and this test is what makes adding one fail.
    """
    document = parse_document(PROBE, path="probe.md")

    assert validation_report(document) == ""
    assert document.components[0].ok is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1, []),
        (2, []),
        (3, ["depth: expected a whole number from 1 to 2, got 3"]),
        (0, ["depth: expected a whole number from 1 to 2, got 0"]),
        ("two", ["depth: expected a whole number from 1 to 2, got 'two'"]),
        (True, ["depth: expected a whole number from 1 to 2, got True"]),
    ],
)
def test_integer_between_bounds_a_field_against_the_server_s_own_limit(value, expected):
    """`True` is in the list deliberately: `isinstance(True, int)` is true in
    Python, so a naive check accepts `depth: true` and sends `1` to a route
    that never saw the author's intent."""
    assert [str(note) for note in integer_between(1, 2)(value, "depth")] == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (["A", "B"], []),
        (["A"], ["entities: expected at least 2 entries, got 1"]),
        ("A", ["entities: expected a list, got text"]),
        ([{"name": "A"}, "B"], ["entities[0]: expected text, got mapping"]),
    ],
)
def test_string_list_checks_each_entry_by_its_own_path(value, expected):
    assert [str(note) for note in string_list(minimum=2)(value, "entities")] == expected
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/application/test_resolved_components.py -v`
Expected: FAIL at import — `ImportError: cannot import name 'integer_between' from 'research_team.application.components'`.

- [ ] **Step 3: Add the two checkers**

In `research_team/application/components.py`, immediately after `one_of` (which ends at :240):

```python
def integer_between(low: int, high: int) -> Checker:
    """A whole number inside a bound the *server* already enforces.

    Both bounds this is used for -- `MAX_NEIGHBORHOOD_DEPTH` and
    `MAX_TIMELINE_BANDS` -- are refused by the route with a 422. Checking here
    turns a fetch-time failure the reader sees into an authoring-time note the
    model can act on, which is the whole reason validation feedback exists.

    `bool` is excluded explicitly: `isinstance(True, int)` is true in Python,
    so without that line `depth: true` validates and then travels to a route
    as `1`, having silently become a number the author never wrote.
    """

    def check(value: Any, path: str) -> list[Note]:
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            return [Note(path, f"expected a whole number from {low} to {high}, got {value!r}")]
        return []

    return check


def string_list(minimum: int = 1) -> Checker:
    """A list of bare strings, each checked at its own subscript path.

    Distinct from `listing`, which takes a list of *mappings*. `compare`'s
    `entities:` is a plain sequence of names, and wrapping each in a mapping to
    reuse `listing` would be schema noise a model has to get right for nothing.
    """

    def check(value: Any, path: str) -> list[Note]:
        if not isinstance(value, list):
            return [Note(path, f"expected a list, got {_typename(value)}")]
        if len(value) < minimum:
            plural = "entry" if minimum == 1 else "entries"
            return [Note(path, f"expected at least {minimum} {plural}, got {len(value)}")]
        notes: list[Note] = []
        for index, entry in enumerate(value):
            notes.extend(text(entry, f"{path}[{index}]"))
        return notes

    return check
```

- [ ] **Step 4: Add the `resolved` field**

In `ComponentType`, immediately after the `craft` docstring block and before `gradeable: bool = False` (:339):

```python
    resolved: bool = False
    """This component carries a reference and fetches its data in the browser.

    Structurally it is the inverse of `gradeable`: nothing is withheld (there
    is no answer key -- the data is the project's own), nothing is graded, and
    the YAML body is a *query*, not content. The flag exists so the projection,
    the prompt and the client can all tell the two classes apart without a name
    list, which is the shape that rots the moment a sixth type is added.

    Validation of a resolved body stays pure and shape-only. The registry
    cannot check that a referenced entity exists -- `validation_report` runs
    here at parse time with no graph handle -- so a name matching nothing is a
    *render* state, not a parse error. See
    `tests/application/test_resolved_components.py` for the assertion that
    keeps it that way.
    """
```

- [ ] **Step 5: Carry the flag onto the wire**

In `_component_json`, add one entry to the `out` dict beside `"gradeable"` (:913):

```python
        "gradeable": bool(spec and spec.gradeable),
        # The client threads `projectId` into a renderer on this rather than
        # on a name list, so a build that adds a sixth resolved type needs no
        # client change to give it a project.
        "resolved": bool(spec and spec.resolved),
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/application/test_resolved_components.py -v`
Expected: PASS, 13 tests.

- [ ] **Step 7: Run the gates this task needs**

```bash
uv run pytest tests/application/test_components.py tests/application/test_resolved_components.py tests/application/test_ask_components.py -q
uv run ruff check .
uv run ruff format --check .
```
Expected: all pass. No `frontend/src` change in this task, so no `npm run verify` and no rebuild.

- [ ] **Step 8: Commit**

```bash
git add research_team/application/components.py tests/application/test_resolved_components.py
git commit -m 'feat: add the resolved flag that splits reference components from content ones

A resolved component carries a reference and fetches its data in the browser.
A flag rather than a name list, so the projection, the prompt and the client
all tell the two classes apart the same way and a sixth type needs no edit at
three call sites.

The registry deliberately cannot check that a referenced entity exists:
validation runs here at parse time with no graph handle, so a name matching
nothing is a render state. test_validation_accepts_a_reference_that_cannot_
possibly_exist is what makes adding an existence check fail, because the
instinct to add one is strong and it cannot be written honestly.

integer_between excludes bool explicitly. isinstance(True, int) is true, so
without that line "depth: true" validates and reaches a route as 1 -- a number
the author never wrote, with nothing anywhere saying so.

No registry entries yet. Each of the five types lands with its own renderer,
tests and styles so each is independently reviewable.'
```

### Task 2: The client contract — `projectId` threading, `useEntityReference`, `ResolvedFrame`

The shared machinery all five widgets stand on. Nothing renders a new widget yet; what lands is the resolution hook, the frame that draws the three non-resolved states, and the renderer signature change that gives a widget a project at all.

`projectId` is optional for the reason already written at `LessonDocument.tsx:48` — a lesson file is read from a session, which has no project in scope. **A resolved component with no `projectId` renders `unavailable`**, which degrades to prose, the same answer as every other failure here.

**Files:**
- Create: `frontend/src/domain/lesson/resolved.ts`
- Create: `frontend/src/domain/lesson/resolved.test.ts`
- Create: `frontend/src/application/lesson/use-entity-reference.ts`
- Create: `frontend/src/application/lesson/use-entity-reference.test.tsx`
- Create: `frontend/src/presentation/lesson/ResolvedFrame.tsx`
- Create: `frontend/src/presentation/lesson/ResolvedFrame.test.tsx`
- Modify: `frontend/src/domain/lesson/document.ts` (add `resolved` to `ComponentBlock`)
- Modify: `frontend/src/infrastructure/http/dto.ts:129-142` (add `resolved` to `documentBlockDto`)
- Modify: `frontend/src/infrastructure/http/mappers.ts:159-173` (carry it through `toDocumentBlock`)
- Modify: `frontend/src/application/queries/keys.ts` (add `entityReference`)
- Modify: `frontend/src/presentation/lesson/LessonDocument.tsx:82-123` (`RENDERERS` signature + threading)
- Modify: `frontend/src/styles/components.css` (the `ResolvedFrame` states)
- Create: `frontend/src/presentation/ask/ask-resolved-context.browser.test.tsx`

**Interfaces:**
- Consumes: `"resolved": bool` on the wire (Task 1).
- Produces — every later task depends on these exact names:
  - `EntityReference = { readonly entity: string; readonly entityId: string | null }`
  - `ResolvedEntity` — a discriminated union on `state`: `'loading' | 'resolved' | 'ambiguous' | 'missing' | 'unavailable'`, carrying `entity: GraphNode` when `resolved` and `candidates: readonly GraphNode[]` when `ambiguous`
  - `readEntityReference(block: ComponentBlock): EntityReference`
  - `matchEntities(name: string, entities: readonly GraphNode[]): ResolvedEntity`
  - `useEntityReference(projectId: ProjectId | undefined, reference: EntityReference): ResolvedEntity`
  - `<ResolvedFrame reference={ResolvedEntity} name={string} children={(entity: GraphNode) => ReactNode} />`
  - `queryKeys.entityReference(project: ProjectId, name: string)`
  - `RENDERERS` entries are now `(props: { block: ComponentBlock; attempts: AttemptsApi; projectId?: ProjectId }) => React.ReactElement`
  - `ComponentBlock.resolved: boolean`

- [ ] **Step 1: Write the failing domain test**

Create `frontend/src/domain/lesson/resolved.test.ts`:

```ts
/** Turning a name search into one of four render states.
 *
 * The whole reason this is a fold rather than a branch inside the hook: the
 * "exact match wins over a substring" rule is the difference between
 * `Constantine` resolving and `Constantine` being ambiguous with
 * `Constantinople`, and that rule deserves a test that needs no DOM and no
 * fake repository to state.
 */
import { describe, expect, it } from 'vitest'

import type { GraphNode } from '@domain/knowledge/graph.ts'
import type { ComponentBlock } from './document.ts'
import { matchEntities, readEntityReference } from './resolved.ts'
import { ComponentId } from '@domain/shared/identifier.ts'

const node = (id: string, name: string, entityType = 'Person'): GraphNode => ({
  id,
  name,
  entityType,
})

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('c1'),
  type: 'definition',
  data,
  raw: '',
  lang: 'component:definition',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
})

describe('matchEntities', () => {
  it('resolves when exactly one entity comes back', () => {
    expect(matchEntities('Constantine', [node('e1', 'Constantine')])).toEqual({
      state: 'resolved',
      entity: node('e1', 'Constantine'),
    })
  })

  it('is missing when nothing comes back', () => {
    expect(matchEntities('Nobody', [])).toEqual({ state: 'missing' })
  })

  it('prefers the exact name over the substring that also matched', () => {
    // `/graph/entities?name=` is a substring, case-insensitive filter in
    // Python (`graph_reader.py:314`), so searching "Constantine" really does
    // return Constantinople too. Without this rule the commonest reference a
    // model writes about late antiquity is permanently ambiguous.
    const result = matchEntities('Constantine', [
      node('e1', 'Constantinople', 'Place'),
      node('e2', 'Constantine'),
    ])

    expect(result).toEqual({ state: 'resolved', entity: node('e2', 'Constantine') })
  })

  it('ignores case and surrounding space when judging an exact match', () => {
    const result = matchEntities('  constantine ', [
      node('e1', 'Constantinople', 'Place'),
      node('e2', 'Constantine'),
    ])

    expect(result).toEqual({ state: 'resolved', entity: node('e2', 'Constantine') })
  })

  it('is ambiguous when two entities carry the same exact name', () => {
    // Two real entities genuinely called "Constantine" is the case `entity_id`
    // exists for, and a picker is the only honest answer.
    const result = matchEntities('Constantine', [
      node('e1', 'Constantine', 'Person'),
      node('e2', 'Constantine', 'Place'),
    ])

    expect(result).toEqual({
      state: 'ambiguous',
      candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
    })
  })

  it('is ambiguous when several match loosely and none matches exactly', () => {
    const result = matchEntities('Constant', [
      node('e1', 'Constantine'),
      node('e2', 'Constantius'),
    ])

    expect(result.state).toBe('ambiguous')
  })
})

describe('readEntityReference', () => {
  it('reads the name and the escape-hatch id', () => {
    expect(readEntityReference(block({ entity: 'Constantine', entity_id: 'e1' }))).toEqual({
      entity: 'Constantine',
      entityId: 'e1',
    })
  })

  it('defaults a missing id to null rather than undefined', () => {
    // `exactOptionalPropertyTypes` is on in this build, and a widget spreading
    // `{...(entityId ? {entityId} : {})}` past this boundary is exactly the
    // kind of drift the null makes impossible.
    expect(readEntityReference(block({ entity: 'Constantine' }))).toEqual({
      entity: 'Constantine',
      entityId: null,
    })
  })

  it('reads a missing entity as the empty string, not a throw', () => {
    // Same defaulting rule as every other reader in `widgets.ts`: a viewer
    // gets a widget that says it found nothing, never a blank page.
    expect(readEntityReference(block({}))).toEqual({ entity: '', entityId: null })
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/domain/lesson/resolved.test.ts`
Expected: FAIL — `Failed to resolve import "./resolved.ts"`.

- [ ] **Step 3: Write the domain module**

Create `frontend/src/domain/lesson/resolved.ts`:

```ts
import type { GraphNode } from '@domain/knowledge/graph.ts'

import type { ComponentBlock } from './document.ts'

/** A resolved component's reference to one entity, as the author wrote it.
 *
 * `entityId` is an escape hatch and stays on every reference: a human editing
 * a lesson file *can* copy one out of the console, and it is the only way to
 * pin a genuinely ambiguous name. A model cannot write one -- entity ids are
 * opaque UUIDs straight out of redstring's store and nothing derives them
 * from a name -- which is the constraint the whole four-state design exists
 * to absorb.
 */
export interface EntityReference {
  readonly entity: string
  readonly entityId: string | null
}

/** What a reference turned into. Four states, and `ambiguous` is a
 *  first-class one rather than an error.
 *
 * `missing` and `unavailable` must degrade to readable prose, never to an
 * error panel: a model writing about an entity the extraction pipeline has
 * not reached yet is normal, not a defect, and an answer that renders a red
 * box for it is worse than one that renders a word.
 *
 * `loading` is the fifth member and is not in the spec's table, because the
 * table describes outcomes. A renderer still has to draw something while the
 * search is in flight, and folding it into `missing` would flash "not in this
 * project's graph" at a reader on every cold cache.
 */
export type ResolvedEntity =
  | { readonly state: 'loading' }
  | { readonly state: 'resolved'; readonly entity: GraphNode }
  | { readonly state: 'ambiguous'; readonly candidates: readonly GraphNode[] }
  | { readonly state: 'missing' }
  | { readonly state: 'unavailable' }

const str = (value: unknown): string | null => (typeof value === 'string' ? value : null)

/** The reference out of a component body, defaulting rather than throwing --
 *  the rule every reader in `widgets.ts` follows, for the same reason. */
export const readEntityReference = (block: ComponentBlock): EntityReference => ({
  entity: str(block.data['entity']) ?? '',
  entityId: str(block.data['entity_id']),
})

/** Which of the four states a page of search results puts a name in.
 *
 * The exact-match rule is the load-bearing part. `/graph/entities?name=` is a
 * substring, case-insensitive filter in Python (`graph_reader.py:314`,
 * deliberately not the store's exact `find_entities`), so a search for
 * "Constantine" returns Constantinople as well -- and without preferring the
 * exact hit, the commonest reference a model writes would render a picker
 * every time. Two entities sharing an exact name is the real ambiguity, and
 * the one `entity_id` exists to pin.
 */
export const matchEntities = (name: string, entities: readonly GraphNode[]): ResolvedEntity => {
  if (entities.length === 0) return { state: 'missing' }

  const wanted = name.trim().toLowerCase()
  const exact = entities.filter((entity) => entity.name.trim().toLowerCase() === wanted)
  const candidates = exact.length > 0 ? exact : entities

  const [only] = candidates
  if (candidates.length === 1 && only) return { state: 'resolved', entity: only }
  return { state: 'ambiguous', candidates }
}
```

- [ ] **Step 4: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/domain/lesson/resolved.test.ts`
Expected: PASS, 9 tests.

- [ ] **Step 5: Write the failing hook test**

Create `frontend/src/application/lesson/use-entity-reference.test.tsx`:

```tsx
/** Resolution as the widgets see it: a project, a reference, one of five states.
 *
 * The container is faked rather than the HTTP layer, matching every other hook
 * test in this suite -- what is under test is which state a page of results
 * becomes and when a fetch happens at all, not how a URL is spelled.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { GraphNode } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { useEntityReference } from './use-entity-reference.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const node = (id: string, name: string, entityType = 'Person'): GraphNode => ({
  id,
  name,
  entityType,
})

const wrapperFor = (search: ReturnType<typeof vi.fn>) => {
  const container = { graph: { search } } as unknown as AppContainer
  // `retry: false` so a rejected search reaches the assertion in one tick
  // rather than three -- the default backoff would make every failure case
  // here a multi-second test.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
}

it('resolves a name that matches exactly one entity', async () => {
  const search = vi.fn().mockResolvedValue({ entities: [node('e1', 'Constantine')], truncated: false })
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Constantine', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  await waitFor(() => expect(result.current.state).toBe('resolved'))
  expect(search).toHaveBeenCalledWith(PROJECT, 'Constantine')
})

it('is unavailable with no project in scope, and fetches nothing', () => {
  // A course file can carry a `definition` widget and be read from a session,
  // which has no project. Red against a hook that calls the port with
  // `undefined` -- the request would 404 on a URL with the word "undefined"
  // in it, and the reader would see a failure where the honest answer is
  // "this page cannot look that up".
  const search = vi.fn()
  const { result } = renderHook(
    () => useEntityReference(undefined, { entity: 'Constantine', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  expect(result.current).toEqual({ state: 'unavailable' })
  expect(search).not.toHaveBeenCalled()
})

it('short-circuits on entity_id without searching', async () => {
  // The escape hatch is exact by construction, so spending a request to
  // confirm it would buy nothing. The synthesised node carries the author's
  // name and an empty `entityType`, which is what the frame renders.
  const search = vi.fn()
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Constantine', entityId: 'e9' }),
    { wrapper: wrapperFor(search) },
  )

  expect(result.current).toEqual({
    state: 'resolved',
    entity: { id: 'e9', name: 'Constantine', entityType: '' },
  })
  expect(search).not.toHaveBeenCalled()
})

it('is missing when the search comes back empty', async () => {
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Nobody', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  await waitFor(() => expect(result.current).toEqual({ state: 'missing' }))
})

it('is ambiguous when two entities share the name', async () => {
  const search = vi.fn().mockResolvedValue({
    entities: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
    truncated: false,
  })
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Constantine', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  await waitFor(() => expect(result.current.state).toBe('ambiguous'))
})

it('is unavailable when the search rejects, not missing', async () => {
  // 503 (no graph read model wired) and "no such entity" say opposite things
  // about the corpus, and a reader told "not in this project's graph" by a
  // server that never looked has been told something false.
  const search = vi.fn().mockRejectedValue(new Error('503'))
  const { result } = renderHook(
    () => useEntityReference(PROJECT, { entity: 'Constantine', entityId: null }),
    { wrapper: wrapperFor(search) },
  )

  await waitFor(() => expect(result.current).toEqual({ state: 'unavailable' }))
})

it('is unavailable for an empty reference, and fetches nothing', () => {
  // `entity:` absent is a validation error the server already reported; the
  // widget still has to draw. Searching for "" would return the whole graph.
  const search = vi.fn()
  const { result } = renderHook(() => useEntityReference(PROJECT, { entity: '', entityId: null }), {
    wrapper: wrapperFor(search),
  })

  expect(result.current).toEqual({ state: 'unavailable' })
  expect(search).not.toHaveBeenCalled()
})
```

- [ ] **Step 6: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/application/lesson/use-entity-reference.test.tsx`
Expected: FAIL — `Failed to resolve import "./use-entity-reference.ts"`.

- [ ] **Step 7: Add the query key**

In `frontend/src/application/queries/keys.ts`, after `definition` (:96):

```ts
  /** One entity-name lookup, shared by every resolved widget on the page.
   *
   * Keyed on the name rather than on the component id: an answer that cites
   * "Constantine" in a `definition` and again in a `graph` is one search, not
   * two, and keying by component would make the same question a cache miss
   * per widget. Not the zustand graph store (`graph-store.ts:85`) for the
   * spec's reason -- that store is per-project console state with selection
   * and expansion in it, and a widget wants a cached read rather than a share
   * in someone else's cursor. */
  entityReference: (project: ProjectId, name: string) =>
    ['entity-reference', project, name] as const,
```

- [ ] **Step 8: Write the hook**

Create `frontend/src/application/lesson/use-entity-reference.ts`:

```ts
import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { EntityReference, ResolvedEntity } from '@domain/lesson/resolved.ts'
import { matchEntities } from '@domain/lesson/resolved.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

/** A resolved component's reference, turned into one of five render states.
 *
 * Three of the five never reach the network:
 *
 *  - no `projectId` -> `unavailable`. A course file is read from a session,
 *    which has no project in scope (`LessonDocument.tsx:48`), and that is a
 *    real case rather than a misuse. Calling the port with `undefined` would
 *    produce a request against a URL with the word "undefined" in it and
 *    report a network failure where the honest answer is "this page cannot
 *    look that up".
 *  - an `entityId` -> `resolved` immediately, on a synthesised node carrying
 *    the author's name. The escape hatch is exact by construction and
 *    confirming it would cost a request to learn nothing. The cost, stated:
 *    `entityType` is empty, so a frame that renders the type shows nothing
 *    for a pinned reference. That is the trade the escape hatch makes.
 *  - an empty name -> `unavailable`. `entity:` absent is already a validation
 *    error the server reported; searching for "" would ask for the graph.
 *
 * A rejected search is `unavailable`, never `missing`. 503 (nothing wired)
 * and "no such entity" say opposite things about the corpus, and a reader
 * told "not in this project's graph" by a server that never looked has been
 * told something false.
 */
export const useEntityReference = (
  projectId: ProjectId | undefined,
  reference: EntityReference,
): ResolvedEntity => {
  const { graph } = useContainer()
  const name = reference.entity.trim()
  const enabled = Boolean(projectId) && name.length > 0 && reference.entityId === null

  const search = useQuery({
    queryKey: queryKeys.entityReference(projectId ?? ('' as ProjectId), name),
    queryFn: () => graph.search(projectId as ProjectId, name),
    enabled,
  })

  if (reference.entityId !== null) {
    return {
      state: 'resolved',
      entity: { id: reference.entityId, name: reference.entity, entityType: '' },
    }
  }
  if (!enabled) return { state: 'unavailable' }
  if (search.isError) return { state: 'unavailable' }
  if (!search.data) return { state: 'loading' }
  return matchEntities(name, search.data.entities)
}
```

- [ ] **Step 9: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/application/lesson/use-entity-reference.test.tsx`
Expected: PASS, 7 tests.

- [ ] **Step 10: Write the failing `ResolvedFrame` test**

Create `frontend/src/presentation/lesson/ResolvedFrame.test.tsx`:

```tsx
/** The three non-resolved states, drawn once so five widgets cannot drift
 *  into five different ways of saying "not found".
 *
 * Every assertion here is about *prose*. `missing` and `unavailable` must
 * degrade to a readable sentence and never to an error panel: a model writing
 * about an entity the extraction pipeline has not reached yet is normal, not
 * a defect. `queryByRole('alert')` is what pins that -- an alert is what an
 * error panel would be.
 */
import { render, screen } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import type { GraphNode } from '@domain/knowledge/graph.ts'

import { ResolvedFrame } from './ResolvedFrame.tsx'

const node = (id: string, name: string, entityType = 'Person'): GraphNode => ({
  id,
  name,
  entityType,
})

it('yields to its child once resolved, and draws no frame of its own', () => {
  render(
    <ResolvedFrame reference={{ state: 'resolved', entity: node('e1', 'Constantine') }} name="Constantine">
      {(entity) => <p>definition of {entity.name}</p>}
    </ResolvedFrame>,
  )

  expect(screen.getByText(/definition of Constantine/)).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('renders the reference as plain prose when the entity is missing', () => {
  const child = vi.fn()
  render(
    <ResolvedFrame reference={{ state: 'missing' }} name="Theodosius">
      {child as unknown as (entity: GraphNode) => React.ReactNode}
    </ResolvedFrame>,
  )

  expect(screen.getByText('Theodosius')).toBeInTheDocument()
  expect(screen.getByText(/not in this project's graph/i)).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  // The child never runs: there is no entity to hand it, and a widget that
  // fetched on a null id is exactly the bug this shape prevents.
  expect(child).not.toHaveBeenCalled()
})

it('renders the reference and nothing else when the lookup is unavailable', () => {
  render(
    <ResolvedFrame reference={{ state: 'unavailable' }} name="Theodosius">
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  expect(screen.getByText('Theodosius')).toBeInTheDocument()
  // Deliberately quieter than `missing`: this page cannot look the name up,
  // so it has learned nothing about the corpus and must not imply it has.
  expect(screen.queryByText(/not in this project's graph/i)).not.toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('lists every candidate with its type when the name is ambiguous', () => {
  const picked = vi.fn()
  render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
      }}
      name="Constantine"
      onPick={picked}
    >
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  // The type is the whole of what makes a picker useful -- two rows reading
  // "Constantine" and "Constantine" are not a choice.
  expect(screen.getByRole('button', { name: /Constantine.*Person/ })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: /Constantine.*Place/ })).toBeInTheDocument()
})

it('hands a picked candidate back to the widget', async () => {
  const picked = vi.fn()
  const { getByRole } = render(
    <ResolvedFrame
      reference={{
        state: 'ambiguous',
        candidates: [node('e1', 'Constantine', 'Person'), node('e2', 'Constantine', 'Place')],
      }}
      name="Constantine"
      onPick={picked}
    >
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  getByRole('button', { name: /Place/ }).click()

  expect(picked).toHaveBeenCalledWith('e2')
})

it('says nothing at all while the search is in flight', () => {
  render(
    <ResolvedFrame reference={{ state: 'loading' }} name="Constantine">
      {() => <p>never</p>}
    </ResolvedFrame>,
  )

  // Red against a build that folds `loading` into `missing`: that one would
  // flash "not in this project's graph" at a reader on every cold cache.
  expect(screen.queryByText(/not in this project's graph/i)).not.toBeInTheDocument()
  expect(screen.getByText('Constantine')).toBeInTheDocument()
})
```

- [ ] **Step 11: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/lesson/ResolvedFrame.test.tsx`
Expected: FAIL — `Failed to resolve import "./ResolvedFrame.tsx"`.

- [ ] **Step 12: Write `ResolvedFrame`**

Create `frontend/src/presentation/lesson/ResolvedFrame.tsx`:

```tsx
import type { ReactNode } from 'react'

import type { GraphNode } from '@domain/knowledge/graph.ts'
import type { ResolvedEntity } from '@domain/lesson/resolved.ts'

/** The three states a resolved widget does not draw itself.
 *
 * Here rather than in each widget so five of them cannot drift into five
 * different ways of saying "not found" -- and so the *tone* is decided once.
 * The tone is the point: `missing` and `unavailable` degrade to readable
 * prose, never to an error panel, because a model writing about an entity the
 * extraction pipeline has not reached yet is normal rather than a defect.
 * Nothing here carries `role="alert"`, and that omission is load-bearing.
 *
 * `missing` and `unavailable` are worded differently on purpose. "Not in this
 * project's graph" is a claim about the corpus, and a page that could not look
 * the name up at all has not earned it.
 */
export const ResolvedFrame = ({
  reference,
  name,
  onPick,
  children,
}: {
  reference: ResolvedEntity
  /** What the author wrote, shown verbatim in every non-resolved state. The
   *  reference is the prose the widget degrades to, so it is never derived
   *  from a candidate -- a reader must see the word the answer used. */
  name: string
  /** Where a picked candidate goes. Optional because a widget may have
   *  nothing to do with one; the picker is still worth drawing, since seeing
   *  that two entities share a name is itself the answer to "why is this
   *  blank". */
  onPick?: (entityId: string) => void
  children: (entity: GraphNode) => ReactNode
}) => {
  if (reference.state === 'resolved') return <>{children(reference.entity)}</>

  if (reference.state === 'ambiguous') {
    return (
      <div className="cmp-ref cmp-ref-ambiguous">
        <span className="cmp-ref-name">{name}</span>
        <p className="cmp-ref-note">
          {reference.candidates.length} entities in this project share that name.
        </p>
        <ul className="cmp-ref-picker">
          {reference.candidates.map((candidate) => (
            <li key={candidate.id}>
              <button type="button" className="cmp-ref-pick" onClick={() => onPick?.(candidate.id)}>
                <span className="cmp-ref-pick-name">{candidate.name}</span>
                <span className="cmp-ref-pick-type">{candidate.entityType}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    )
  }

  if (reference.state === 'missing') {
    return (
      <div className="cmp-ref cmp-ref-missing">
        <span className="cmp-ref-name">{name}</span>
        <span className="cmp-ref-note">not in this project&rsquo;s graph</span>
      </div>
    )
  }

  // `loading` and `unavailable` draw the same thing: the reference, and
  // nothing that would be a claim about the corpus. They differ only in
  // whether an answer is still coming, which is not worth a spinner on a
  // block a reader is scrolling past.
  return (
    <div className="cmp-ref cmp-ref-quiet">
      <span className="cmp-ref-name">{name}</span>
    </div>
  )
}
```

- [ ] **Step 13: Add the styles**

Append to `frontend/src/styles/components.css`:

```css
/* A resolved component that did not resolve. Deliberately typographic rather
   than panelled: these states are prose the reader should be able to read
   past, and a bordered box would make an ordinary gap in the corpus look like
   a failure of the page. */
.cmp-ref {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.5rem;
}

.cmp-ref-name {
  font-weight: 600;
  color: var(--fg);
}

.cmp-ref-note {
  font-size: 0.875rem;
  color: var(--fg-muted);
}

.cmp-ref-ambiguous {
  flex-direction: column;
  align-items: stretch;
}

.cmp-ref-picker {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin: 0;
  padding: 0;
  list-style: none;
}

.cmp-ref-pick {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
  /* `border-0` beside the directional width, per CLAUDE.md: a bare
     `border-solid` would give the three sides with no explicit width the
     browser's `medium` (~3px) and draw a box where one edge was meant. */
  border: 1px solid var(--line);
  border-radius: 0.375rem;
  padding: 0.25rem 0.5rem;
  background: var(--bg-raised);
  cursor: pointer;
}

.cmp-ref-pick-type {
  font-size: 0.75rem;
  color: var(--fg-muted);
}
```

Check the token names against `frontend/src/styles/tokens.css` before writing them; if `--bg-raised` or `--fg-muted` is spelled differently there, use the spelling `components.css` already uses elsewhere in the file rather than inventing one.

- [ ] **Step 14: Run it to verify it passes**

Run: `cd frontend && npx vitest run src/presentation/lesson/ResolvedFrame.test.tsx`
Expected: PASS, 6 tests.

- [ ] **Step 15: Carry `resolved` across the wire boundary**

In `frontend/src/domain/lesson/document.ts`, add to `ComponentBlock` after `withheld` (:43):

```ts
  /** Whether this component fetches its data from the project rather than
   *  carrying it. The renderer threads `projectId` on this rather than on a
   *  name list, so a sixth resolved type needs no client change. */
  readonly resolved: boolean
```

In `frontend/src/infrastructure/http/dto.ts:140`, add to the component member of `documentBlockDto`:

```ts
    withheld: z.array(z.string()).default([]),
    // Defaulted for `graphEntityDto.temporal`'s reason: fixtures in this
    // suite predate the field and should not have to be found and updated
    // because a block gained a flag. `false` is the honest default -- every
    // component that existed before this field carried its own data.
    resolved: z.boolean().default(false),
```

In `frontend/src/infrastructure/http/mappers.ts:170`, add to `toDocumentBlock`'s `block`:

```ts
    withheld: raw.withheld,
    resolved: raw.resolved,
```

- [ ] **Step 16: Thread `projectId` through the renderers**

In `frontend/src/presentation/lesson/LessonDocument.tsx`, change `RENDERERS` (:82-89) and `Component` (:91-123):

```tsx
const RENDERERS: Readonly<
  Record<
    string,
    (props: {
      block: ComponentBlock
      attempts: AttemptsApi
      /** Optional because a lesson file is read from a session, which has no
       *  project in scope -- see this module's `projectId` prop. A resolved
       *  component handed none renders its `unavailable` state, which is
       *  prose, which is the same answer as every other failure here. */
      projectId?: ProjectId
    }) => React.ReactElement
  >
> = {
  flashcards: Flashcards,
  mcq: Mcq,
  cloze: Cloze,
  checklist: Checklist,
}

const Component = ({
  block,
  attempts,
  withheldExplanation,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  withheldExplanation: string
  projectId?: ProjectId
}) => {
  if (block.unknown) return <UnknownComponent block={block} />
  if (block.errors.length > 0) return <BrokenComponent block={block} />

  const Renderer = RENDERERS[block.type]
  if (!Renderer) return <UnknownComponent block={block} />

  return (
    <section
      className={`cmp cmp-${block.type}`}
      data-component={block.id}
      aria-label={`${block.type} component`}
    >
      <div className="cmp-kind">
        <span className="cmp-kind-name">{block.type}</span>
        {block.withheld.length > 0 ? (
          <Tooltip explanation={withheldExplanation}>
            <span className="cmp-withheld">answers withheld</span>
          </Tooltip>
        ) : null}
      </div>
      {/* Spread rather than a bare `projectId={projectId}`, matching the
          `Markdown` call above: `exactOptionalPropertyTypes` treats an
          explicit `undefined` differently from an omitted prop. */}
      <Renderer block={block} attempts={attempts} {...(projectId ? { projectId } : {})} />
    </section>
  )
}
```

and pass it at the call site (:71-77):

```tsx
        <Component
          key={block.id}
          block={block}
          attempts={attempts}
          withheldExplanation={withheldExplanation}
          {...(projectId ? { projectId } : {})}
        />
```

- [ ] **Step 17: Write the browser test that pins the ask-turn context**

Create `frontend/src/presentation/ask/ask-resolved-context.browser.test.tsx`:

```tsx
/** That a resolved widget inside an ask turn has a QueryClient and a container.
 *
 * A browser test rather than a jsdom one for what it protects against: if
 * either provider is missing, `useEntityReference` throws during render, and a
 * thrown hook takes the whole answer down rather than one block. That is the
 * one failure mode in this feature that is not per-block, so it is worth a
 * test that mounts the real tree rather than a wrapper a test built.
 *
 * The assertion is deliberately about the *sibling prose surviving*, not about
 * the widget rendering: a widget that renders proves the providers are there,
 * but so would a widget that silently fell back, and only the prose surviving
 * distinguishes "one block degraded" from "the answer went down".
 */
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import { AskTurn } from './AskTurn.tsx'
import { PROJECT, turn } from './ask-fixtures.ts'

it('renders the prose beside a resolved widget rather than losing the turn', async () => {
  // Substitute for a red proof, since the providers are already in the tree:
  // removing `QueryClientProvider` from `AskPage.tsx`'s subtree, or the
  // `ContainerProvider` above it, makes this red -- the hook throws and the
  // error boundary replaces the whole turn, so "Two papers cover this" is
  // gone rather than merely unaccompanied.
  //
  // Fill this in against the real `AskTurn` mounting path once Task 3 has
  // shipped a resolved renderer; until then this file asserts the existing
  // mcq path and is widened in Task 3.
  const { getByText } = render(
    <AskTurn
      projectId={PROJECT}
      turn={turn({ blocks: [] })}
      open={false}
      onToggle={() => {}}
      conversationId="c1"
    />,
  )

  await expect.element(getByText(/Two papers cover this/)).toBeInTheDocument()
})
```

Read `frontend/src/presentation/ask/ask-fixtures.ts` before writing this and match its `turn()` signature and its default answer text exactly; if the default answer is not "Two papers cover this", assert against whatever it is.

- [ ] **Step 18: Run every test this task touched**

```bash
cd frontend && npx vitest run src/domain/lesson src/application/lesson src/presentation/lesson src/presentation/ask
```
Expected: PASS, including the pre-existing `AskTurn.test.tsx` and `use-attempts.test.tsx`, which the `RENDERERS` signature change must not disturb.

Then, alone (never concurrently with the above — two vitest processes fail spuriously):

```bash
cd frontend && npm run test:browser
```

- [ ] **Step 19: Run the gates**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd frontend && npm run verify
```

- [ ] **Step 20: Rebuild the committed console**

`npm run verify` runs the build and never compares its output against the committed tree, so a stale console passes it green every time. This is a real CI gate.

```bash
cd frontend && npm run build
cd .. && git status --short research_team/interfaces/web/static
```
Expected: `assets/app.js` and `assets/index.css` show as modified.

- [ ] **Step 21: Commit**

```bash
git add frontend/src research_team/interfaces/web/static
git commit -m 'feat: resolve an entity reference in the browser, in four states

The machinery all five resolved widgets stand on. A reference is a *search*,
not a resolve -- /graph/entities?name= is a substring filter in Python -- so
ambiguity is a first-class render state rather than an error, and the picker
is the answer to it.

matchEntities prefers an exact name over the substrings that also matched.
Without that rule the commonest reference a model writes about late antiquity
("Constantine") renders a picker every time, because Constantinople matches
the same query. Two entities sharing an exact name is the real ambiguity and
the one entity_id exists to pin.

A rejected search is unavailable, never missing: 503 and "no such entity" say
opposite things about the corpus, and a reader told "not in this project s
graph" by a server that never looked has been told something false. Nothing in
ResolvedFrame carries role=alert, and that omission is load-bearing -- an
entity the extraction pipeline has not reached yet is normal, and a red box
for it is worse than a word.

Cost: an entity_id short-circuit synthesises a node with an empty entityType,
so a pinned reference shows no type. That is the trade the escape hatch makes,
and confirming the id would spend a request to learn nothing.'
```

### Task 3: `definition`

The smallest of the five, and first for that reason: `useDefinition` already exists (`use-definition.ts:27`) and `GET .../definition` is synchronous with a documented `text: null` for "undefinable" rather than a 404 (`app.py:2437`).

`text: null` is a **fifth state, distinct from `missing`**: the entity exists and the project cannot define it. It renders as the name with a note saying so, and is deliberately not folded into `missing`, because the two say opposite things about the corpus.

**Files:**
- Modify: `research_team/application/components.py` (a `definition` entry in `REGISTRY`)
- Modify: `tests/application/test_components.py` (the registry-shape and reference-rendering cases)
- Create: `tests/integration/test_resolved_widget_routes.py` (the fixture-trap file, shared by Tasks 3, 5 and 6)
- Modify: `frontend/src/domain/lesson/widgets.ts` (`readDefinitionRef`)
- Create: `frontend/src/presentation/lesson/DefinitionWidget.tsx`
- Create: `frontend/src/presentation/lesson/DefinitionWidget.test.tsx`
- Modify: `frontend/src/presentation/lesson/LessonDocument.tsx` (one `RENDERERS` line)
- Modify: `frontend/src/styles/components.css`

**Interfaces:**
- Consumes: `readEntityReference`, `useEntityReference`, `ResolvedFrame`, `RENDERERS`'s `projectId?: ProjectId` prop (Task 2); `useDefinition(projectId, entityId, {enabled})` (`presentation/research/use-definition.ts:27`); `Definition = { text: string | null; citations: readonly DefinitionCitation[]; model: string | null; generatedAt: string | null; stale: boolean }` (`domain/knowledge/graph.ts:143`).
- Produces:
  - `REGISTRY["definition"]`, fields `entity` (required text) and `entity_id` (text)
  - `readDefinitionRef(block: ComponentBlock): EntityReference` — re-exported from `widgets.ts` so every widget's reader lives in one module
  - `<DefinitionWidget block attempts projectId? />`
  - `_untouched_project(client) -> UUID` in `tests/integration/test_resolved_widget_routes.py`

**A decision this task locks in, so later tasks match it.** `entity` is **required** on every reference and `entity_id` is optional beside it, even though a human pinning an id has already said which entity they mean. The registry checks fields one at a time (`_check_fields`) and has no mechanism for "one of these two"; adding one for this would be new validation machinery serving five fields. Requiring the name costs a human eight keystrokes and buys the widget the prose it degrades to in every non-resolved state — which it needs regardless, since `ResolvedFrame` renders the author's word, not a candidate's.

- [ ] **Step 1: Write the failing registry test**

Append to `tests/application/test_components.py`:

```python
DEFINITION = """\\
```component:definition
id: nicene
entity: Nicene Christianity
```
"""


def test_a_definition_carries_its_reference_through_both_views():
    """The body is a query, so there is nothing to strip and nothing to grade.

    Red against a `definition` entry that sets `gradeable=True` or a `strip`,
    both of which are the shape every other registered type has and therefore
    the shape a copy-paste addition would arrive in.
    """
    document = parse_document(DEFINITION, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert author["data"]["entity"] == "Nicene Christianity"
    assert learner["data"] == author["data"]
    assert learner["resolved"] is True
    assert learner["gradeable"] is False


def test_a_definition_without_an_entity_says_which_field_is_missing():
    source = "```component:definition\nid: nope\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == ["entity: required field missing"]


def test_a_definition_may_pin_an_ambiguous_name_with_an_entity_id():
    """`entity_id` is the escape hatch, and it is *not* a warned-about unknown
    key -- a human copying one out of the console must not be told the field
    they were told to use is unrecognised."""
    source = (
        "```component:definition\n"
        "id: c\n"
        "entity: Constantine\n"
        "entity_id: 8f2c1e00-0000-4000-8000-000000000000\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert block.errors == ()
    assert block.warnings == ()
    assert block.data["entity_id"] == "8f2c1e00-0000-4000-8000-000000000000"


def test_the_generated_reference_renders_the_definition_example():
    """`component_reference` is what the authoring model reads. A type whose
    example does not appear in it is a type the model will never write."""
    reference = component_reference(only=["definition"])

    assert "component:definition" in reference
    assert "entity:" in reference
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/application/test_components.py -k definition -v`
Expected: FAIL — the blocks come back `unknown=True`, so `resolved` is `False` and `errors` is empty where the test wants `entity: required field missing`.

- [ ] **Step 3: Register `definition`**

In `research_team/application/components.py`, add to `REGISTRY` after `"checklist"`:

```python
    "definition": ComponentType(
        name="definition",
        version=1,
        summary=(
            "This project's own grounded definition of an entity, with the "
            "passages it was drawn from. Reference by name; the browser looks "
            "it up."
        ),
        example=(
            "```component:definition\n"
            "id: nicene-christianity\n"
            "entity: Nicene Christianity\n"
            "```"
        ),
        fields={
            "entity": Spec(text, required=True),
            "entity_id": Spec(text),
        },
        resolved=True,
        craft=(
            "Write the entity name exactly as your prose does, and exactly as "
            "the sources spell it. The lookup is a name search over what "
            "extraction actually stored, so a tidier canonical name -- "
            "'Constantine I' for an entity stored as 'Constantine' -- finds "
            "nothing and the widget renders as the plain name.",
            "Use this where a reader needs the project's grounded account of a "
            "term, not where you would define it yourself in a clause. A "
            "definition widget beside a sentence that already defines the word "
            "is two definitions competing.",
            "`entity_id` is for pinning a name two entities share. You will not "
            "have one; leave it out.",
        ),
    ),
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/application/test_components.py tests/application/test_resolved_components.py -q`
Expected: PASS.

- [ ] **Step 5: Write the failing fixture-trap test**

Create `tests/integration/test_resolved_widget_routes.py`:

```python
"""The routes the resolved widgets call, against a project nothing has opened.

CLAUDE.md's "Read models" section names the trap this file exists for: a
fixture that seeds through the same call the code under test depends on cannot
see that dependency go missing. `test_definition_wiring.py`'s `_seed` calls
`application.graphs.open(project_id)` to plant its entity, so from every test
in that file the project is always already open -- and a route that stopped
opening it would answer 503 exactly once per project, on the first request,
and be invisible.

So every test here creates a project and then *does not touch it*. The claim
is narrow and worth stating plainly: these routes answer, rather than 503,
for a project no fixture has opened. An empty graph is the right corpus for
that claim -- what is under test is the open, not the answer.

These would pass with the resolved components reverted entirely: they cover
the routes the widgets call, which predate this feature. They are here
because the widgets are the first callers to hit those routes on a project
the console has never displayed, which is exactly the path the once-per-
project 503 lives on.
"""

from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from research_team.composition import build_application
from research_team.interfaces.web import create_app


@pytest.fixture
async def client(db_path):
    application = build_application(db_path=db_path)
    await application.start()
    api = create_app(
        application.service,
        application.feed,
        application.turns,
        corpus=application.corpus,
        blob_store=application.blob_store,
        graphs=application.graphs,
        definitions=application.definition_readers,
    )
    transport = ASGITransport(app=api)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def _untouched_project(client: AsyncClient) -> UUID:
    """A project created through the API and opened by nothing.

    Deliberately does not call `graphs.open`, `graphs.chunks`, or any route
    that would. That omission is the entire test.
    """
    created = await client.post("/api/projects", json={"name": f"widget-{uuid4()}"})
    assert created.status_code == 200
    return UUID(created.json()["id"])


async def test_a_name_search_answers_for_a_project_nothing_has_opened(client):
    """The first request a `definition` widget makes.

    Red against a build whose `/graph/entities` route fetches a reader without
    opening the project first -- 503 on the first call for every project, 200
    on every call after it, which reads as flakiness rather than as a bug.
    """
    project_id = await _untouched_project(client)

    response = await client.get(f"/api/projects/{project_id}/graph/entities?name=Constantine")

    assert response.status_code == 200
    assert response.json()["entities"] == []
```

Check `tests/conftest.py` for the real name of the temporary-database fixture and the exact `build_application` signature before writing this; `db_path` is what `tests/integration/test_definition_wiring.py` uses, and if `build_application` requires `model=` there, pass the same `FakeMessagesListChatModel` that file builds.

- [ ] **Step 6: Run it**

Run: `uv run pytest tests/integration/test_resolved_widget_routes.py -v`
Expected: PASS against the current server. It is a regression guard, not a red-first test, and its docstring says so.

- [ ] **Step 7: Add the reader**

In `frontend/src/domain/lesson/widgets.ts`, after `readChecklist` (:113) and before the `rec`/`list`/`str` helpers:

```ts
/** A `definition` widget's reference. A thin alias over the shared reader
 *  rather than its own parse: every resolved widget reads the same two
 *  fields, and five copies of that would be five places to forget
 *  `entity_id`. Re-exported here so a renderer imports its reader from the
 *  module every other renderer imports one from. */
export { readEntityReference as readDefinitionRef } from './resolved.ts'
```

- [ ] **Step 8: Write the failing widget test**

Create `frontend/src/presentation/lesson/DefinitionWidget.test.tsx`:

```tsx
/** The five states a `definition` renders, from a faked container.
 *
 * `text: null` is the fifth and the one worth reading the spec over: the
 * entity exists and the project cannot define it, which says the opposite of
 * `missing`. Folding them together would tell a reader an entity is absent
 * from a graph that contains it.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Definition } from '@domain/knowledge/graph.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { DefinitionWidget } from './DefinitionWidget.tsx'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('nicene'),
  type: 'definition',
  data,
  raw: '',
  lang: 'component:definition',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
})

/** Never called: a resolved component is not gradeable and nothing posts. It
 *  is passed because `RENDERERS` types every renderer with it. */
const attempts = {} as unknown as AttemptsApi

const definition = (over: Partial<Definition> = {}): Definition => ({
  text: 'The creed affirmed at Nicaea in 325.',
  citations: [{ sourceId: 'doc-1', start: 10, end: 40, atSeconds: null }],
  model: 'fake',
  generatedAt: '2026-01-01T00:00:00Z',
  stale: false,
  ...over,
})

const renderWidget = (
  data: Record<string, unknown>,
  {
    entities = [{ id: 'e1', name: 'Nicene Christianity', entityType: 'Concept' }],
    define = vi.fn().mockResolvedValue(definition()),
    projectId = PROJECT as ProjectId | undefined,
  } = {},
) => {
  const container = {
    graph: { search: vi.fn().mockResolvedValue({ entities, truncated: false }) },
    definitions: { definition: define },
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    define,
    ...render(
      <DefinitionWidget
        block={block(data)}
        attempts={attempts}
        {...(projectId ? { projectId } : {})}
      />,
      { wrapper },
    ),
  }
}

it('shows the project definition and its citations once resolved', async () => {
  renderWidget({ entity: 'Nicene Christianity' })

  await waitFor(() =>
    expect(screen.getByText(/creed affirmed at Nicaea/)).toBeInTheDocument(),
  )
  expect(screen.getByRole('link', { name: /doc-1/ })).toBeInTheDocument()
})

it('says the project cannot define an entity it does hold', async () => {
  const { define } = renderWidget(
    { entity: 'Nicene Christianity' },
    { define: vi.fn().mockResolvedValue(definition({ text: null })) },
  )

  await waitFor(() => expect(define).toHaveBeenCalled())
  // Distinct wording from `missing`, and the assertion that keeps it distinct:
  // this entity *is* in the graph, and saying otherwise would be false.
  expect(screen.getByText(/no definition/i)).toBeInTheDocument()
  expect(screen.queryByText(/not in this project's graph/i)).not.toBeInTheDocument()
})

it('degrades to the plain name when the entity is not in the graph', async () => {
  const { define } = renderWidget({ entity: 'Theodosius' }, { entities: [] })

  await waitFor(() =>
    expect(screen.getByText(/not in this project's graph/i)).toBeInTheDocument(),
  )
  expect(screen.getByText('Theodosius')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  // The definition is never fetched for an entity with no id -- red against a
  // widget that calls the port with `null` and shows a network error.
  expect(define).not.toHaveBeenCalled()
})

it('renders the reference as prose when there is no project in scope', () => {
  const { define } = renderWidget({ entity: 'Nicene Christianity' }, { projectId: undefined })

  expect(screen.getByText('Nicene Christianity')).toBeInTheDocument()
  expect(define).not.toHaveBeenCalled()
})

it('offers a picker when two entities share the name', async () => {
  renderWidget(
    { entity: 'Constantine' },
    {
      entities: [
        { id: 'e1', name: 'Constantine', entityType: 'Person' },
        { id: 'e2', name: 'Constantine', entityType: 'Place' },
      ],
    },
  )

  await waitFor(() =>
    expect(screen.getByRole('button', { name: /Constantine.*Person/ })).toBeInTheDocument(),
  )
})

it('defines the candidate a reader picks out of the ambiguity', async () => {
  const { define } = renderWidget(
    { entity: 'Constantine' },
    {
      entities: [
        { id: 'e1', name: 'Constantine', entityType: 'Person' },
        { id: 'e2', name: 'Constantine', entityType: 'Place' },
      ],
    },
  )

  await waitFor(() => screen.getByRole('button', { name: /Place/ }))
  screen.getByRole('button', { name: /Place/ }).click()

  await waitFor(() => expect(define).toHaveBeenCalledWith(PROJECT, 'e2'))
})
```

Read `frontend/src/presentation/research/GraphDetail.tsx` before writing the citation link assertion and match how it renders a `DefinitionCitation` — if it does not produce a `role="link"`, assert against whatever element it does produce rather than adding a link this widget alone has.

- [ ] **Step 9: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/lesson/DefinitionWidget.test.tsx`
Expected: FAIL — `Failed to resolve import "./DefinitionWidget.tsx"`.

- [ ] **Step 10: Write the widget**

Create `frontend/src/presentation/lesson/DefinitionWidget.tsx`:

```tsx
import { useState } from 'react'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { useEntityReference } from '@application/lesson/use-entity-reference.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readDefinitionRef } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'
import { useDefinition } from '../research/use-definition.ts'
import { Prose } from './widgets.tsx'
import { ResolvedFrame } from './ResolvedFrame.tsx'

/** This project's own grounded account of an entity, beside the prose that
 *  named it.
 *
 * `attempts` is in the signature and unused. Every renderer in `RENDERERS`
 * takes it, and a resolved component is not gradeable -- nothing here posts,
 * and there is no answer key to withhold. Narrowing the record's type per
 * entry to drop it would buy one unused parameter and cost the uniform
 * signature that makes `RENDERERS` a lookup rather than a switch.
 */
export const DefinitionWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const reference = readDefinitionRef(block)
  const resolved = useEntityReference(projectId, reference)
  // A reader's pick out of the ambiguity picker, which overrides the search.
  // Local state rather than a store: it is one reader's choice about one
  // block in one answer, and nothing else on the page has a use for it.
  const [picked, setPicked] = useState<string | null>(null)

  return (
    <div className="cmp-body">
      <ResolvedFrame
        reference={picked ? { state: 'resolved', entity: { id: picked, name: reference.entity, entityType: '' } } : resolved}
        name={reference.entity}
        onPick={setPicked}
      >
        {(entity) => <Defined projectId={projectId as ProjectId} entity={entity} />}
      </ResolvedFrame>
    </div>
  )
}

/** Split out so `useDefinition` is mounted only once there is an id to give
 *  it. A hook cannot be called conditionally, so the alternative is calling
 *  it with a null id and an `enabled` flag on every non-resolved state --
 *  which works and which reads as though a fetch might happen when it cannot.
 */
const Defined = ({ projectId, entity }: { projectId: ProjectId; entity: { id: string; name: string } }) => {
  const definition = useDefinition(projectId, entity.id)

  if (definition.isPending) return <p className="cmp-ref-note">looking that up…</p>
  // A failed *definition* is not a failed resolution: the entity is known to
  // be in the graph, so saying "not in this project's graph" here would be
  // false. Quiet prose, matching every other failure in this feature.
  if (definition.isError || !definition.data) {
    return <p className="cmp-ref-note">{entity.name} — could not be defined just now</p>
  }

  const { text, citations } = definition.data
  // `text: null` is a 200, not a 404, and means "this entity exists and the
  // project has nothing to ground a definition in" -- the opposite claim from
  // `missing`. See the route's own docstring (`app.py:2447`) for why it is not
  // a 404, and the spec's section 4 for why it is not folded into `missing`.
  if (text === null) {
    return (
      <p className="cmp-ref-note">
        <span className="cmp-ref-name">{entity.name}</span> — no definition yet; nothing in this
        project&rsquo;s corpus grounds one.
      </p>
    )
  }

  return (
    <>
      <Prose text={text} className="cmp-definition-text" />
      {citations.length > 0 ? (
        <ul className="cmp-definition-citations">
          {citations.map((citation, index) => (
            <li key={index}>
              <a href={`#source-${citation.sourceId}`}>
                {citation.sourceId} {citation.start}–{citation.end}
              </a>
            </li>
          ))}
        </ul>
      ) : null}
    </>
  )
}
```

Before writing the citation list, read `frontend/src/presentation/research/GraphDetail.tsx` and reuse whatever it already renders a `DefinitionCitation` with. A second, differently-shaped citation link in this codebase is the drift `ResolvedFrame` exists to prevent, one layer down — if `GraphDetail` has an extractable piece, extract it and use it in both.

- [ ] **Step 11: Wire it into `RENDERERS`**

In `frontend/src/presentation/lesson/LessonDocument.tsx`:

```tsx
import { DefinitionWidget } from './DefinitionWidget.tsx'
```

and one line in the record:

```tsx
  checklist: Checklist,
  definition: DefinitionWidget,
```

- [ ] **Step 12: Add the styles**

Append to `frontend/src/styles/components.css`:

```css
.cmp-definition-citations {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  margin: 0.5rem 0 0;
  padding: 0;
  list-style: none;
  font-size: 0.75rem;
  color: var(--fg-muted);
}
```

- [ ] **Step 13: Run the frontend tests**

Run: `cd frontend && npx vitest run src/presentation/lesson src/domain/lesson src/application/lesson`
Expected: PASS.

- [ ] **Step 14: Run the gates**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd frontend && npm run verify
```

- [ ] **Step 15: Rebuild the committed console**

```bash
cd frontend && npm run build
cd .. && git status --short research_team/interfaces/web/static
```
Expected: `assets/app.js` and `assets/index.css` modified.

- [ ] **Step 16: Commit**

```bash
git add research_team/application/components.py tests frontend/src research_team/interfaces/web/static
git commit -m 'feat: add the definition component, resolved in the browser

The smallest of the five and first for that reason: useDefinition already
exists and the route is synchronous.

text: null is a fifth render state and is deliberately not folded into
missing. The route answers 200 with a null text when an entity exists and
nothing in the corpus grounds a definition; missing means the entity is not
in the graph at all. The two say opposite things about the corpus, and one
wording for both would tell a reader an entity is absent from a graph that
contains it.

entity is required and entity_id is optional beside it, rather than
one-of-two. _check_fields validates one field at a time and has no
mechanism for a disjunction; building one for five fields is not worth it,
and the widget needs the name anyway -- ResolvedFrame degrades to the word
the author wrote, never to a candidate.

tests/integration/test_resolved_widget_routes.py is the fixture trap
CLAUDE.md names: every other test of these routes seeds through
graphs.open, so a route that stopped opening the project would 503 once
per project and be invisible. Those tests would pass with this feature
reverted, and their docstring says so -- they guard the path the widgets
are the first callers on.'
```

---

### Task 4: `evidence`

A claim beside the actual passages it rests on. **Takes source ids directly, with no name resolution** — source ids are already in the model's context via `[[src:...]]`, and `references.ts` proves the model handles that shape.

`GET /sources/{sid}?start&end` clamps the range rather than 422-ing (`app.py:1635`), and returns the offsets it actually served — so a bad range degrades to a nearby excerpt rather than an error.

**Cost, stated plainly:** a model can write a `claim` the excerpt does not support. The widget makes that *visible* rather than preventing it, which is the whole point — prose can do the same thing today and nothing shows the reader.

**Files:**
- Modify: `research_team/application/components.py` (an `evidence` entry in `REGISTRY`)
- Modify: `tests/application/test_components.py`
- Modify: `frontend/src/domain/lesson/widgets.ts` (`readEvidence`)
- Modify: `frontend/src/application/queries/keys.ts` — **no change needed**; `queryKeys.document(project, source, {start, end})` (:73) is already the ranged-read key and is exactly this widget's read
- Create: `frontend/src/presentation/lesson/EvidenceWidget.tsx`
- Create: `frontend/src/presentation/lesson/EvidenceWidget.test.tsx`
- Modify: `frontend/src/presentation/lesson/LessonDocument.tsx`
- Modify: `frontend/src/styles/components.css`

**Interfaces:**
- Consumes: `RENDERERS`'s `projectId?` prop (Task 2); `DocumentRepository.read(projectId, sourceId, range?: { start?: number; end?: number }): Promise<DocumentText>` (`application/ports/repositories.ts:273`); `DocumentText extends TextSummary { text: string; start: number; end: number }` (`domain/research/document.ts:94`); `queryKeys.document`.
- Produces:
  - `REGISTRY["evidence"]`
  - `EvidenceSource = { readonly source: string; readonly start: number | null; readonly end: number | null }`
  - `Evidence = { readonly claim: string; readonly sources: readonly EvidenceSource[] }`
  - `readEvidence(block: ComponentBlock): Evidence`
  - `<EvidenceWidget block attempts projectId? />`

**No `useEntityReference` here.** This is the one resolved type with no name to resolve, so it uses none of Task 2's resolution machinery — only the `projectId` threading. Its `unavailable` state (no project in scope) is drawn by the widget itself as the claim in plain prose, because there is no entity reference for `ResolvedFrame` to frame.

- [ ] **Step 1: Write the failing registry test**

Append to `tests/application/test_components.py`:

```python
EVIDENCE = """\\
```component:evidence
id: state-religion
claim: |
  Theodosius made Nicene Christianity the state religion in AD 380.
sources:
  - source: doc-1
    start: 4120
    end: 4380
```
"""


def test_evidence_carries_its_claim_and_ranges_through_both_views():
    document = parse_document(EVIDENCE, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["sources"][0] == {"source": "doc-1", "start": 4120, "end": 4380}
    assert learner["resolved"] is True


def test_evidence_needs_at_least_one_source():
    """A claim with no passage behind it is prose wearing a widget's clothes,
    and the widget's entire value is that the reader can check it."""
    source = "```component:evidence\nid: e\nclaim: Something happened.\nsources: []\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "sources: expected at least 1 entry, got 0"
    ]


def test_evidence_names_the_offending_source_by_its_subscript():
    source = (
        "```component:evidence\n"
        "id: e\n"
        "claim: Something happened.\n"
        "sources:\n"
        "  - start: 10\n"
        "    end: 20\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == ["sources[0].source: required field missing"]


def test_evidence_refuses_a_negative_offset():
    """Red against `Spec(text)` on the offsets, which would accept `start: -5`
    and send it to a route that clamps it to 0 without saying so."""
    source = (
        "```component:evidence\n"
        "id: e\n"
        "claim: Something happened.\n"
        "sources:\n"
        "  - source: doc-1\n"
        "    start: -5\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "sources[0].start: expected a whole number from 0 to 100000000, got -5"
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/application/test_components.py -k evidence -v`
Expected: FAIL — the blocks are `unknown=True`.

- [ ] **Step 3: Register `evidence`**

In `research_team/application/components.py`, add to `REGISTRY` after `"definition"`:

```python
    "evidence": ComponentType(
        name="evidence",
        version=1,
        summary=(
            "A claim beside the passages it rests on, quoted from this "
            "project's sources. Takes source ids directly -- the same ids "
            "`[[src:...]]` uses."
        ),
        example=(
            "```component:evidence\n"
            "id: state-religion\n"
            "claim: |\n"
            "  Theodosius made Nicene Christianity the state religion in AD 380.\n"
            "sources:\n"
            "  - source: doc-4f2a\n"
            "    start: 4120\n"
            "    end: 4380\n"
            "```"
        ),
        fields={
            "claim": Spec(text, required=True),
            "sources": Spec(
                listing(
                    {
                        "source": Spec(text, required=True),
                        # Bounded rather than merely non-negative: the route
                        # clamps whatever it is given, so an offset typed with
                        # an extra digit returns the end of the document and
                        # nothing tells the reader the range was nonsense.
                        # The ceiling is generous on purpose -- it is a typo
                        # guard, not a document-length check, which this layer
                        # has no way to make.
                        "start": Spec(integer_between(0, 100_000_000)),
                        "end": Spec(integer_between(0, 100_000_000)),
                    }
                ),
                required=True,
            ),
        },
        resolved=True,
        craft=(
            "Quote the passage that actually carries the claim, not the "
            "paragraph around it. The reader is going to read both and compare "
            "them, which is the entire point of the widget -- a range that only "
            "nearly supports the claim is more damaging here than in prose, "
            "because you have invited the check.",
            "Use the source ids already in your context. A `source:` you cannot "
            "find in what you were given is one you invented, and the widget "
            "will show nothing.",
            "One claim per block. Two claims sharing a passage list leaves the "
            "reader unable to tell which range supports which.",
        ),
    ),
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/application/test_components.py -k evidence -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add the reader**

In `frontend/src/domain/lesson/widgets.ts`, after the `readDefinitionRef` re-export:

```ts
/** One passage an `evidence` claim rests on. Offsets are nullable rather
 *  than defaulted to 0: absent means "from the start" / "to the end", and
 *  `{start: 0, end: 0}` would be a request for nothing. */
export interface EvidenceSource {
  readonly source: string
  readonly start: number | null
  readonly end: number | null
}

export interface Evidence {
  readonly claim: string
  readonly sources: readonly EvidenceSource[]
}

export const readEvidence = (block: ComponentBlock): Evidence => ({
  claim: str(block.data['claim']) ?? '',
  sources: list(block.data['sources']).map((raw) => {
    const entry = rec(raw)
    return {
      source: str(entry['source']) ?? '',
      start: num(entry['start']),
      end: num(entry['end']),
    }
  }),
})
```

and add the missing helper beside `str` at the bottom of the file:

```ts
const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null
```

- [ ] **Step 6: Write the failing widget test**

Create `frontend/src/presentation/lesson/EvidenceWidget.test.tsx`:

```tsx
/** A claim, and the passages a reader can check it against.
 *
 * The load-bearing case is the last one: the widget shows the offsets the
 * server *actually served*, not the ones the author asked for. The route
 * clamps rather than 422s, so an author who guessed past the end of a
 * document gets a nearby excerpt -- and a widget that printed the requested
 * range beside a different excerpt would be lying about what the reader is
 * looking at.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { EvidenceWidget } from './EvidenceWidget.tsx'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('state-religion'),
  type: 'evidence',
  data,
  raw: '',
  lang: 'component:evidence',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
})

const attempts = {} as unknown as AttemptsApi

const renderWidget = (
  data: Record<string, unknown>,
  {
    read = vi.fn().mockResolvedValue({
      sourceId: 'doc-1',
      title: 'Theodosian Code',
      text: 'cunctos populos, quos clementiae nostrae regit imperium',
      start: 4120,
      end: 4175,
    }),
    projectId = PROJECT as ProjectId | undefined,
  } = {},
) => {
  const container = { documents: { read } } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    read,
    ...render(
      <EvidenceWidget block={block(data)} attempts={attempts} {...(projectId ? { projectId } : {})} />,
      { wrapper },
    ),
  }
}

const CLAIM = 'Theodosius made Nicene Christianity the state religion in AD 380.'

it('shows the claim and the passage it rests on', async () => {
  const { read } = renderWidget({
    claim: CLAIM,
    sources: [{ source: 'doc-1', start: 4120, end: 4380 }],
  })

  expect(screen.getByText(CLAIM)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText(/cunctos populos/)).toBeInTheDocument())
  expect(read).toHaveBeenCalledWith(PROJECT, 'doc-1', { start: 4120, end: 4380 })
})

it('reports the offsets the server served, not the ones asked for', async () => {
  // The route clamps (`app.py:1635`) and answers with the real range. Red
  // against a widget that prints its own `start`/`end` from the YAML: the
  // reader would see "4120-4380" over an excerpt that is neither.
  renderWidget({ claim: CLAIM, sources: [{ source: 'doc-1', start: 4120, end: 99999 }] })

  await waitFor(() => expect(screen.getByText(/4120/)).toBeInTheDocument())
  expect(screen.getByText(/4175/)).toBeInTheDocument()
  expect(screen.queryByText(/99999/)).not.toBeInTheDocument()
})

it('keeps the claim readable when the passage cannot be fetched', async () => {
  // A source id the model invented is the ordinary failure here, and the
  // claim is still the answer's sentence. An error panel over a reader's own
  // prose is the degradation this feature refuses everywhere.
  renderWidget(
    { claim: CLAIM, sources: [{ source: 'doc-nope', start: 0, end: 10 }] },
    { read: vi.fn().mockRejectedValue(new Error('404')) },
  )

  expect(screen.getByText(CLAIM)).toBeInTheDocument()
  await waitFor(() => expect(screen.getByText(/could not be quoted/i)).toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('renders the claim alone with no project in scope, and fetches nothing', () => {
  const { read } = renderWidget(
    { claim: CLAIM, sources: [{ source: 'doc-1', start: 0, end: 10 }] },
    { projectId: undefined },
  )

  expect(screen.getByText(CLAIM)).toBeInTheDocument()
  expect(read).not.toHaveBeenCalled()
})

it('omits an absent offset from the range it asks for', async () => {
  // `start:` absent means "from the beginning", not `0`-and-`0`. Red against
  // a reader that defaults both to 0, which asks for an empty excerpt.
  const { read } = renderWidget({ claim: CLAIM, sources: [{ source: 'doc-1' }] })

  await waitFor(() => expect(read).toHaveBeenCalledWith(PROJECT, 'doc-1', {}))
})
```

Read `frontend/src/presentation/research/DocumentReader.tsx` (or whichever component already calls `documents.read` with a range) before writing this, and match the exact argument shape it passes — if the port takes `{ start, end }` with `undefined` rather than an omitted key, assert that instead.

- [ ] **Step 7: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/lesson/EvidenceWidget.test.tsx`
Expected: FAIL — `Failed to resolve import "./EvidenceWidget.tsx"`.

- [ ] **Step 8: Write the widget**

Create `frontend/src/presentation/lesson/EvidenceWidget.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'

import { useContainer } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { queryKeys } from '@application/queries/keys.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { EvidenceSource } from '@domain/lesson/widgets.ts'
import { readEvidence } from '@domain/lesson/widgets.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { Prose } from './widgets.tsx'

/** A claim beside the passages it rests on.
 *
 * The one resolved type with nothing to resolve: source ids are already in
 * the authoring model's context via `[[src:...]]`, so this takes them
 * directly and uses none of `useEntityReference`. Its "no project in scope"
 * state is drawn here rather than by `ResolvedFrame`, because there is no
 * entity reference for a frame to frame -- the claim itself is the prose it
 * degrades to.
 *
 * The cost the spec states plainly and this widget does not prevent: a model
 * can write a claim the excerpt does not support. Making that visible is the
 * point. Prose can do the same today and nothing shows the reader.
 */
export const EvidenceWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const evidence = readEvidence(block)

  return (
    <div className="cmp-body">
      <Prose text={evidence.claim} className="cmp-claim" />
      <ol className="cmp-evidence-list">
        {evidence.sources.map((source, index) => (
          <li key={index}>
            {projectId ? (
              <Passage projectId={projectId} source={source} />
            ) : (
              <span className="cmp-ref-note">{source.source}</span>
            )}
          </li>
        ))}
      </ol>
    </div>
  )
}

const Passage = ({ projectId, source }: { projectId: ProjectId; source: EvidenceSource }) => {
  const { documents } = useContainer()
  // Omitted rather than `undefined`, because absent means "from the start" /
  // "to the end" and `0` would ask for nothing. The key already carries the
  // same nullable pair, so two ranges over one source stay two cache entries.
  const range = {
    ...(source.start === null ? {} : { start: source.start }),
    ...(source.end === null ? {} : { end: source.end }),
  }

  const passage = useQuery({
    queryKey: queryKeys.document(projectId, source.source as SourceId, {
      ...(source.start === null ? {} : { start: source.start }),
      ...(source.end === null ? {} : { end: source.end }),
    }),
    queryFn: () => documents.read(projectId, source.source as SourceId, range),
  })

  if (passage.isPending) return <span className="cmp-ref-note">fetching the passage…</span>
  if (passage.isError || !passage.data) {
    return (
      <span className="cmp-ref-note">
        {source.source} — could not be quoted from this project&rsquo;s corpus
      </span>
    )
  }

  return (
    <figure className="cmp-passage">
      <blockquote>{passage.data.text}</blockquote>
      {/* The offsets the server *served*, not the ones asked for: the route
          clamps rather than refusing, so printing the request beside a
          different excerpt would misdescribe what the reader is looking at. */}
      <figcaption>
        {source.source} {passage.data.start}–{passage.data.end}
      </figcaption>
    </figure>
  )
}
```

- [ ] **Step 9: Wire it into `RENDERERS`**

```tsx
import { EvidenceWidget } from './EvidenceWidget.tsx'
```

```tsx
  definition: DefinitionWidget,
  evidence: EvidenceWidget,
```

- [ ] **Step 10: Add the styles**

Append to `frontend/src/styles/components.css`:

```css
.cmp-evidence-list {
  margin: 0.75rem 0 0;
  padding: 0;
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.cmp-passage {
  margin: 0;
  /* `border-0` first, then the one directional width: a bare `border-solid`
     beside `border-left` gives the other three sides the browser's `medium`
     (~3px) and draws a box. See CLAUDE.md. */
  border: 0;
  border-left: 2px solid var(--line);
  padding-left: 0.75rem;
}

.cmp-passage blockquote {
  margin: 0;
  font-style: italic;
}

.cmp-passage figcaption {
  margin-top: 0.25rem;
  font-size: 0.75rem;
  color: var(--fg-muted);
}
```

- [ ] **Step 11: Run the frontend tests**

Run: `cd frontend && npx vitest run src/presentation/lesson src/domain/lesson`
Expected: PASS.

- [ ] **Step 12: Run the gates**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd frontend && npm run verify
```

- [ ] **Step 13: Rebuild the committed console and commit**

```bash
cd frontend && npm run build
cd ..
git add research_team/application/components.py tests frontend/src research_team/interfaces/web/static
git commit -m 'feat: add the evidence component, a claim beside its passages

The one resolved type with nothing to resolve. Source ids are already in the
authoring model context via [[src:...]] and references.ts proves the model
handles that shape, so this takes ids directly and uses none of
useEntityReference.

The widget prints the offsets the server served, not the ones the author
asked for. GET /sources/{sid} clamps rather than 422s, so a range typed with
an extra digit comes back as a nearby excerpt -- and a caption showing the
requested range over a different passage would misdescribe what the reader is
looking at.

Cost, stated rather than prevented: a model can write a claim its excerpt
does not support. Making that visible is the entire point. Prose can do the
same today and nothing shows the reader.

The offsets are bounded in the registry rather than merely non-negative. It
is a typo guard, not a document-length check -- this layer has no way to make
the second one, and saying so in the comment is cheaper than someone later
believing it does.'
```

---

### Task 5: `graph`

The neighbourhood subgraph. `GET .../neighborhood?depth=` 404s on an unknown id and **422s past `MAX_NEIGHBORHOOD_DEPTH` (= 2)** (`app.py:2364`), so `depth` is validated in the registry against the same bound rather than discovered at fetch time.

Reuses `GraphCanvas` (`GraphCanvas.tsx:52`, props `{view, selected, onNodeClick}`, memoized and self-measuring) rather than `GraphBrowser`, whose props are a console's worth of search and filter state.

**Sizing is the open risk.** `GraphCanvas` measures its container via `ResizeObserver` and a markdown flow gives it no height. The widget sets an explicit aspect-ratio box, and **this needs a browser test, not a jsdom one** — per CLAUDE.md, a measurement is exactly what jsdom cannot judge (`scrollHeight` is 0 everywhere and `getComputedStyle` returns only what an inline style said).

**Files:**
- Modify: `research_team/application/components.py` (a `graph` entry in `REGISTRY`)
- Modify: `tests/application/test_components.py`
- Modify: `tests/integration/test_resolved_widget_routes.py` (the neighbourhood fixture-trap case)
- Modify: `frontend/src/domain/lesson/widgets.ts` (`readGraphRef`)
- Create: `frontend/src/presentation/lesson/GraphWidget.tsx`
- Create: `frontend/src/presentation/lesson/GraphWidget.test.tsx`
- Create: `frontend/src/presentation/lesson/GraphWidget.browser.test.tsx`
- Modify: `frontend/src/presentation/lesson/LessonDocument.tsx`
- Modify: `frontend/src/styles/components.css`

**Interfaces:**
- Consumes: `readEntityReference`, `useEntityReference`, `ResolvedFrame` (Task 2); `GraphRepository.neighborhood(projectId, entityId, depth?): Promise<Neighborhood>` (`application/ports/repositories.ts:469`); `expand(view: GraphView, hood: Neighborhood): GraphView` and `emptyGraph: GraphView` (`domain/knowledge/graph.ts:194,151`); `GraphCanvas` (`presentation/research/GraphCanvas.tsx:52`).
- Produces:
  - `REGISTRY["graph"]`, fields `entity` (required text), `entity_id` (text), `depth` (`integer_between(1, MAX_NEIGHBORHOOD_DEPTH)`, default 1)
  - `GraphRef = EntityReference & { readonly depth: number }`
  - `readGraphRef(block: ComponentBlock): GraphRef`
  - `queryKeys.neighborhood(project, entityId, depth)`
  - `<GraphWidget block attempts projectId? />`, rendering a container carrying `data-graph-widget` and the class `cmp-graph-box`

- [ ] **Step 1: Write the failing registry test**

Append to `tests/application/test_components.py`:

```python
GRAPH = """\\
```component:graph
id: constantine-around
entity: Constantine
depth: 1
```
"""


def test_a_graph_carries_its_reference_and_depth_through_both_views():
    document = parse_document(GRAPH, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["depth"] == 1
    assert learner["resolved"] is True


def test_a_graph_defaults_its_depth_to_one():
    """One hop is the readable neighbourhood; two is a hairball in a markdown
    column. Red against a registry entry with no `default`, which would leave
    `depth` absent and the client picking a second bound to keep in step."""
    source = "```component:graph\nid: g\nentity: Constantine\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert block.data["depth"] == 1


def test_a_graph_depth_past_the_server_s_bound_is_an_authoring_error():
    """The route answers 422 for this. Catching it here turns a failure the
    reader sees into a note the model can act on -- which is what the whole
    validation report exists for. Red against `Spec(text)` on `depth`."""
    source = "```component:graph\nid: g\nentity: Constantine\ndepth: 5\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "depth: expected a whole number from 1 to 2, got 5"
    ]


def test_a_graph_depth_bound_tracks_the_server_s_constant():
    """Red against a hardcoded `2` in the registry the day someone raises
    `MAX_NEIGHBORHOOD_DEPTH` -- the failure being a widget that validates to
    one bound and fetches against another, which nothing else would report."""
    from research_team.application.graph_read import MAX_NEIGHBORHOOD_DEPTH

    source = (
        f"```component:graph\nid: g\nentity: Constantine\n"
        f"depth: {MAX_NEIGHBORHOOD_DEPTH}\n```\n"
    )

    assert parse_document(source, path="lesson.md").components[0].errors == ()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/application/test_components.py -k graph -v`
Expected: FAIL — the blocks are `unknown=True`.

- [ ] **Step 3: Register `graph`**

Add the import at the top of `research_team/application/components.py`, beside the existing `from research_team.domain.workflow import ArtifactType`:

```python
from research_team.application.graph_read import MAX_NEIGHBORHOOD_DEPTH
```

Check that this import does not create a cycle before writing it — run `uv run python -c "import research_team.application.components"`. If `graph_read` imports `components` (directly or transitively), inline the constant here with a comment naming `graph_read.py:47` as its source and add an assertion to `test_a_graph_depth_bound_tracks_the_server_s_constant` comparing the two, so a divergence is still caught.

Add to `REGISTRY` after `"evidence"`:

```python
    "graph": ComponentType(
        name="graph",
        version=1,
        summary=(
            "The neighbourhood around one entity in this project's knowledge "
            "graph: what it connects to, and how. Reference by name."
        ),
        example=(
            "```component:graph\nid: constantine-around\nentity: Constantine\ndepth: 1\n```"
        ),
        fields={
            "entity": Spec(text, required=True),
            "entity_id": Spec(text),
            # Bounded here against the same constant the route refuses past,
            # so an over-deep request is an authoring note rather than a 422
            # the reader discovers. Default 1 because one hop is the readable
            # neighbourhood -- two is a hairball in a markdown column.
            "depth": Spec(integer_between(1, MAX_NEIGHBORHOOD_DEPTH), default=1),
        },
        resolved=True,
        craft=(
            "Write the entity name exactly as your prose does, and exactly as "
            "the sources spell it. The lookup is a name search over what "
            "extraction actually stored, so a tidier canonical name finds "
            "nothing and the widget renders as the plain name.",
            "Reach for this when the *shape* of the connections is the point. "
            "If what matters is one relationship, a sentence says it better "
            "than a drawing the reader has to find it in.",
            "Leave `depth` at 1 unless the second hop is the thing you are "
            "showing. Two hops on a well-extracted entity is a hairball.",
        ),
    ),
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/application/test_components.py -k graph -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add the neighbourhood fixture-trap case**

Append to `tests/integration/test_resolved_widget_routes.py`:

```python
async def test_a_neighbourhood_answers_404_not_503_on_an_unopened_project(client):
    """The second request a `graph` widget makes.

    404 is the *right* answer here -- no such entity in an empty graph -- and
    503 is the fixture trap: it means the route reached for a reader without
    opening the project. The two are a character apart in a log and say
    opposite things about whether the build is wired.
    """
    project_id = await _untouched_project(client)
    unknown = uuid4()

    response = await client.get(
        f"/api/projects/{project_id}/graph/entities/{unknown}/neighborhood?depth=1"
    )

    assert response.status_code == 404
```

- [ ] **Step 6: Add the reader and the key**

In `frontend/src/domain/lesson/widgets.ts`:

```ts
import type { EntityReference } from './resolved.ts'
import { readEntityReference } from './resolved.ts'

/** A `graph` widget's reference, plus how far out to draw. */
export interface GraphRef extends EntityReference {
  readonly depth: number
}

export const readGraphRef = (block: ComponentBlock): GraphRef => ({
  ...readEntityReference(block),
  // The server defaults this too, so a body that reached here without one is
  // a body the registry did not normalise -- a hand-built test block, in
  // practice. 1 is the same default the registry writes.
  depth: num(block.data['depth']) ?? 1,
})
```

In `frontend/src/application/queries/keys.ts`, after `entityReference`:

```ts
  /** One entity's neighbourhood at one depth. Depth is in the key rather than
   *  refetched over: two widgets on the same entity at depths 1 and 2 are two
   *  different graphs, and a shared key would draw one under the other. */
  neighborhood: (project: ProjectId, entityId: string, depth: number) =>
    ['neighborhood', project, entityId, depth] as const,
```

- [ ] **Step 7: Write the failing jsdom test**

Create `frontend/src/presentation/lesson/GraphWidget.test.tsx`:

```tsx
/** What jsdom *can* judge about the graph widget: which request it makes,
 *  and which of the four states it draws.
 *
 * It cannot judge the one thing this widget's design turns on -- whether the
 * canvas has a height inside a markdown flow -- because jsdom lays nothing
 * out and applies no stylesheet. That assertion lives in
 * `GraphWidget.browser.test.tsx`, and writing it here as a comment is
 * precisely the failure CLAUDE.md names.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { GraphWidget } from './GraphWidget.tsx'

// The canvas is `React.lazy` over `react-force-graph-2d`; a real force
// simulation is not what any assertion here is about, and letting it mount
// would make every case wait on a d3 tick. Same mock as
// `graph-dressing.browser.test.tsx` uses, for the same reason.
vi.mock('../research/GraphCanvas.tsx', () => ({
  GraphCanvas: ({ view }: { view: { nodes: readonly { id: string }[] } }) => (
    <div data-fake-canvas data-nodes={view.nodes.length} />
  ),
}))

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('constantine-around'),
  type: 'graph',
  data,
  raw: '',
  lang: 'component:graph',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
})

const attempts = {} as unknown as AttemptsApi

const hood = {
  root: { id: 'e1', name: 'Constantine', entityType: 'Person' },
  entities: [{ id: 'e2', name: 'Nicaea', entityType: 'Place' }],
  relationships: [{ source: 'e1', target: 'e2', relationshipType: 'convened' }],
}

const renderWidget = (
  data: Record<string, unknown>,
  {
    entities = [{ id: 'e1', name: 'Constantine', entityType: 'Person' }],
    neighborhood = vi.fn().mockResolvedValue(hood),
    projectId = PROJECT as ProjectId | undefined,
  } = {},
) => {
  const container = {
    graph: { search: vi.fn().mockResolvedValue({ entities, truncated: false }), neighborhood },
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    neighborhood,
    ...render(
      <GraphWidget block={block(data)} attempts={attempts} {...(projectId ? { projectId } : {})} />,
      { wrapper },
    ),
  }
}

it('draws the neighbourhood of a name that resolved', async () => {
  const { neighborhood } = renderWidget({ entity: 'Constantine', depth: 1 })

  await waitFor(() => expect(neighborhood).toHaveBeenCalledWith(PROJECT, 'e1', 1))
  // The root arrives in its own field and is not repeated in `entities`, so a
  // merge that reads only `entities` draws the edges without the node. Two is
  // the count that catches it.
  await waitFor(() => expect(screen.getByTestId('graph-canvas')).toHaveAttribute('data-nodes', '2'))
})

it('asks for the depth the author wrote', async () => {
  const { neighborhood } = renderWidget({ entity: 'Constantine', depth: 2 })

  await waitFor(() => expect(neighborhood).toHaveBeenCalledWith(PROJECT, 'e1', 2))
})

it('degrades to the plain name when the entity is not in the graph', async () => {
  const { neighborhood } = renderWidget({ entity: 'Theodosius', depth: 1 }, { entities: [] })

  await waitFor(() => expect(screen.getByText(/not in this project's graph/i)).toBeInTheDocument())
  expect(neighborhood).not.toHaveBeenCalled()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('renders the reference as prose with no project in scope', () => {
  const { neighborhood } = renderWidget({ entity: 'Constantine', depth: 1 }, { projectId: undefined })

  expect(screen.getByText('Constantine')).toBeInTheDocument()
  expect(neighborhood).not.toHaveBeenCalled()
})

it('keeps the reference readable when the neighbourhood 404s', async () => {
  // An inferred node's id comes from the ontology table and belongs to no
  // stored entity, so `/neighborhood` really does 404 for a name that
  // resolved. Prose, not a panel.
  renderWidget(
    { entity: 'Constantine', depth: 1 },
    { neighborhood: vi.fn().mockRejectedValue(new Error('404')) },
  )

  await waitFor(() => expect(screen.getByText(/no neighbourhood/i)).toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})
```

Change the mock's element to carry `data-testid="graph-canvas"` if `getByTestId` is the idiom this suite uses; check a neighbouring test first and match whichever query the repository already reaches for.

- [ ] **Step 8: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/lesson/GraphWidget.test.tsx`
Expected: FAIL — `Failed to resolve import "./GraphWidget.tsx"`.

- [ ] **Step 9: Write the widget**

Create `frontend/src/presentation/lesson/GraphWidget.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense, useMemo, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { useEntityReference } from '@application/lesson/use-entity-reference.ts'
import { queryKeys } from '@application/queries/keys.ts'
import { emptyGraph, expand } from '@domain/knowledge/graph.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readGraphRef } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ResolvedFrame } from './ResolvedFrame.tsx'

// Lazy for `GraphPane`'s reason: the ~60 kB canvas/d3-force bundle should be
// fetched when a reader actually meets a graph, not as part of rendering an
// ask answer that mostly is not one.
const GraphCanvas = lazy(() =>
  import('../research/GraphCanvas.tsx').then((module) => ({ default: module.GraphCanvas })),
)

/** One entity's neighbourhood, drawn inside an answer.
 *
 * `GraphCanvas` rather than `GraphBrowser`: the browser's props are a
 * console's worth of search and filter state, none of which a block in a
 * document has or wants.
 *
 * **The box is the load-bearing part.** `GraphCanvas` measures its container
 * with a `ResizeObserver` and a markdown flow gives it no height, so without
 * an explicit box the canvas measures 0 and draws nothing -- with no error
 * anywhere. `aspect-ratio` rather than a fixed pixel height so it stays
 * sensible in a narrow column. Asserted in `GraphWidget.browser.test.tsx`,
 * because a computed height is exactly what jsdom cannot judge.
 */
export const GraphWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const reference = readGraphRef(block)
  const resolved = useEntityReference(projectId, reference)
  const [picked, setPicked] = useState<string | null>(null)

  return (
    <div className="cmp-body">
      <ResolvedFrame
        reference={
          picked
            ? { state: 'resolved', entity: { id: picked, name: reference.entity, entityType: '' } }
            : resolved
        }
        name={reference.entity}
        onPick={setPicked}
      >
        {(entity) => (
          <Neighbourhood
            projectId={projectId as ProjectId}
            entityId={entity.id}
            name={entity.name}
            depth={reference.depth}
          />
        )}
      </ResolvedFrame>
    </div>
  )
}

const Neighbourhood = ({
  projectId,
  entityId,
  name,
  depth,
}: {
  projectId: ProjectId
  entityId: string
  name: string
  depth: number
}) => {
  const { graph } = useContainer()
  const hood = useQuery({
    queryKey: queryKeys.neighborhood(projectId, entityId, depth),
    queryFn: () => graph.neighborhood(projectId, entityId, depth),
  })

  // `expand` off `emptyGraph` rather than a hand-built `GraphView`: it is the
  // one place that knows the root arrives in its own field and is not
  // repeated in `entities`, so a merge written here would draw the root's
  // edges without the root.
  const view = useMemo(() => (hood.data ? expand(emptyGraph, hood.data) : emptyGraph), [hood.data])

  if (hood.isPending) return <p className="cmp-ref-note">drawing {name}&rsquo;s neighbourhood…</p>
  if (hood.isError || !hood.data) {
    // A resolved name whose neighbourhood 404s is a real case: an inferred
    // node's id comes from the ontology table and belongs to no stored
    // entity. Prose, like every other failure here.
    return <p className="cmp-ref-note">{name} — no neighbourhood to draw in this project</p>
  }

  return (
    <div className="cmp-graph-box" data-graph-widget>
      <Suspense fallback={<p className="cmp-ref-note">loading the canvas…</p>}>
        <GraphCanvas view={view} selected={entityId} onNodeClick={() => {}} />
      </Suspense>
    </div>
  )
}
```

`onNodeClick` is a no-op deliberately: a block inside an answer has no detail panel to open and nowhere to navigate to. If a later slice gives it one, that is a separate change with its own test.

- [ ] **Step 10: Add the styles**

Append to `frontend/src/styles/components.css`:

```css
/* The canvas measures this box with a ResizeObserver, and a markdown flow
   gives it no height -- so without an explicit one it measures 0 and draws
   nothing, silently. `aspect-ratio` rather than a fixed height so a narrow
   column gets a shorter graph rather than a squashed one.
   Asserted in `GraphWidget.browser.test.tsx`: jsdom reports 0 here whatever
   this rule says, so no jsdom test can defend it. */
.cmp-graph-box {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 10;
  /* A floor as well as a ratio: at a very narrow width the ratio alone gives
     a box too short to show a neighbourhood in. */
  min-height: 15rem;
  overflow: hidden;
  border: 0;
  border-radius: 0.5rem;
  background: var(--bg-raised);
}
```

- [ ] **Step 11: Write the browser measurement test**

Create `frontend/src/presentation/lesson/GraphWidget.browser.test.tsx`:

```tsx
/** That the graph widget has a height inside a markdown flow.
 *
 * The assertion this whole file exists for, and the one no jsdom test can
 * make: jsdom lays nothing out and applies no stylesheet, so `getBoundingClientRect`
 * is `0x0` there whatever `.cmp-graph-box` says. `GraphCanvas` measures its
 * container with a `ResizeObserver` and draws into whatever it measures, so a
 * box with no height is a canvas that draws nothing -- with nothing raised,
 * nothing logged, and a block that simply is not there.
 *
 * **Proved red** by deleting `aspect-ratio` and `min-height` from
 * `.cmp-graph-box` in `components.css`: the box measures 0 high and both
 * assertions below fail. Re-take that measurement if the rule is edited.
 *
 * The wrapper is a real `.md.doc` flow rather than a bare div, because that
 * is the context the widget actually lands in and the height it gets is a
 * property of that context, not of the element alone.
 */
import { render } from 'vitest-browser-react'
import { expect, it, vi } from 'vitest'

import '../../styles/index.css'

import { GraphWidget } from './GraphWidget.tsx'

vi.mock('../research/GraphCanvas.tsx', () => ({
  // Fills its container, which is the point: what is measured is the *box*,
  // and a canvas that did not stretch would measure the mock rather than the
  // rule under test.
  GraphCanvas: () => <div data-fake-canvas style={{ position: 'absolute', inset: 0 }} />,
}))

it('gives the canvas a box with a real height inside a document flow', async () => {
  const { container } = render(
    <div className="md doc" style={{ width: '640px' }}>
      <p>Prose before the widget.</p>
      <GraphWidget {...harness()} />
      <p>Prose after it.</p>
    </div>,
  )

  const box = await waitForBox(container)
  const rect = box.getBoundingClientRect()

  expect(rect.width).toBeGreaterThan(300)
  expect(rect.height).toBeGreaterThan(200)
  // The canvas fills the box rather than collapsing inside it -- the failure
  // a `position: relative` box with an absolutely-positioned child has when
  // the box itself is fine and the child is not.
  const canvas = box.querySelector('[data-fake-canvas]') as HTMLElement
  expect(canvas.getBoundingClientRect().height).toBeCloseTo(rect.height, 0)
})
```

Write `harness()` and `waitForBox()` in the same file: `harness()` builds the props (a `block` with `entity`/`depth`, the `attempts` cast, and a `projectId`) wrapped in the `ContainerProvider`/`QueryClientProvider` pair the jsdom test already builds — lift that wrapper into a small local helper rather than duplicating it, and have `waitForBox` poll for `[data-graph-widget]` until the resolution and neighbourhood queries have settled. Copy the provider construction verbatim from `GraphWidget.test.tsx` so the two files cannot disagree about what a resolved fixture looks like.

- [ ] **Step 12: Wire it into `RENDERERS`**

```tsx
import { GraphWidget } from './GraphWidget.tsx'
```

```tsx
  evidence: EvidenceWidget,
  graph: GraphWidget,
```

- [ ] **Step 13: Run the tests**

```bash
cd frontend && npx vitest run src/presentation/lesson src/domain/lesson
```

Then, alone — never at the same time as the above:

```bash
cd frontend && npm run test:browser
```
Expected: both pass. Before trusting the browser test green, delete `aspect-ratio` and `min-height` from `.cmp-graph-box`, re-run `npm run test:browser` and confirm it goes red, then restore them.

- [ ] **Step 14: Run the gates**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd frontend && npm run verify
```

- [ ] **Step 15: Rebuild the committed console and commit**

```bash
cd frontend && npm run build
cd ..
git add research_team/application/components.py tests frontend/src research_team/interfaces/web/static
git commit -m 'feat: add the graph component, one entity neighbourhood in an answer

GraphCanvas rather than GraphBrowser: the browser props are a console worth
of search and filter state, none of which a block in a document has.

The box is the load-bearing part and it has a browser test. GraphCanvas
measures its container with a ResizeObserver, and a markdown flow gives it no
height -- so without an explicit aspect-ratio box the canvas measures 0 and
draws nothing, with nothing raised and nothing logged. jsdom reports 0 there
whatever the stylesheet says, so no jsdom test can defend it; the assertion
was proved red by deleting the rule.

depth is bounded in the registry against MAX_NEIGHBORHOOD_DEPTH itself rather
than a copied 2, so raising the server constant cannot leave a widget
validating to one bound and fetching against another.

expand(emptyGraph, hood) rather than a hand-built GraphView: it is the one
place that knows the root arrives in its own field and is not repeated in
entities, and a merge written at the call site would draw the root edges
without the root.

onNodeClick is a no-op. A block inside an answer has no detail panel to open;
giving it one is a separate change with its own test.'
```

---

### Task 6: `timeline`

**Not entity-scoped, and the syntax must not imply it is.** `GET /timeline` takes `entity_type`, `from`, `to`, `limit` and has *no* topic or entity filter (`app.py:2629`). Writing `entity:` here would be a field that silently does nothing, which is worse than the capability being absent.

The response carries `undated_count` and `truncated`, and **both are rendered**. A timeline that quietly drops two thirds of its bands is the read-model failure this project has already had once, and the counts are the only thing that shows it.

`timeline-repository.ts:11` currently passes only `entityType` through and must be widened to carry `from`/`to`/`limit`.

**Files:**
- Modify: `research_team/application/components.py` (a `timeline` entry in `REGISTRY`)
- Modify: `tests/application/test_components.py`
- Modify: `tests/integration/test_resolved_widget_routes.py`
- Modify: `frontend/src/application/ports/repositories.ts:513-521` (widen `TimelineRepository.timeline`)
- Modify: `frontend/src/infrastructure/http/timeline-repository.ts`
- Create: `frontend/src/infrastructure/http/timeline-repository.test.ts`
- Modify: `frontend/src/application/queries/keys.ts`
- Modify: `frontend/src/domain/lesson/widgets.ts` (`readTimelineQuery`)
- Create: `frontend/src/presentation/lesson/TimelineWidget.tsx`
- Create: `frontend/src/presentation/lesson/TimelineWidget.test.tsx`
- Create: `frontend/src/presentation/lesson/TimelineWidget.browser.test.tsx`
- Modify: `frontend/src/presentation/lesson/LessonDocument.tsx`
- Modify: `frontend/src/styles/components.css`
- Check: every existing caller of `timeline(...)` — `frontend/src/presentation/research/TimelinePane.tsx` and any hook beneath it — still compiles against the widened signature. It will, because the new parameter is optional, but confirm rather than assume.

**Interfaces:**
- Consumes: `TimelineCanvas` (`presentation/research/TimelineCanvas.tsx:89`, props `{bands, selected, onSelect}`); `Timeline = { bands: readonly TimelineBand[]; undatedCount: number; truncated: boolean }`; `toTimeline` (`mappers.ts`).
- Produces:
  - `REGISTRY["timeline"]`, fields `entity_type` (text), `from` (text), `to` (text), `limit` (`integer_between(1, MAX_TIMELINE_BANDS)`)
  - `TimelineWindow = { readonly entityType: string | null; readonly from: string | null; readonly to: string | null; readonly limit: number | null }`
  - `readTimelineQuery(block: ComponentBlock): TimelineWindow`
  - `TimelineRepository.timeline(projectId: ProjectId, window?: { entityType?: string; from?: string; to?: string; limit?: number }): Promise<Timeline>` — **a signature change; the second positional `entityType?: string` becomes an options object**
  - `queryKeys.timeline(project, window)`
  - `<TimelineWidget block attempts projectId? />`, rendering a container carrying `data-timeline-widget` and the class `cmp-timeline-box`

- [ ] **Step 1: Write the failing registry test**

Append to `tests/application/test_components.py`:

```python
TIMELINE = """\\
```component:timeline
id: fourth-century-people
entity_type: Person
from: "0300-01-01"
to: "0400-01-01"
```
"""


def test_a_timeline_carries_its_window_through_both_views():
    document = parse_document(TIMELINE, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["entity_type"] == "Person"
    assert author["data"]["from"] == "0300-01-01"
    assert learner["resolved"] is True


def test_a_timeline_has_no_entity_field_and_warns_about_one():
    """`GET /timeline` has no entity filter, so `entity:` here would be a
    field that silently does nothing -- and a widget that quietly ignores what
    the author asked for is worse than one that cannot do it at all.

    The warning is `_unknown_keys`' existing behaviour, so this is red only
    against a registry entry that *added* an `entity` field to be helpful.
    """
    source = "```component:timeline\nid: t\nentity: Constantine\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.warnings] == ["entity: unrecognised field, ignored"]
    assert block.errors == ()


def test_a_timeline_with_no_window_at_all_is_valid():
    """Every field is optional: the whole timeline is a real thing to ask for,
    and requiring a range would make the commonest use the fiddliest."""
    block = parse_document("```component:timeline\nid: t\n```\n", path="lesson.md").components[0]

    assert block.errors == ()


def test_a_timeline_limit_past_the_server_s_cap_is_an_authoring_error():
    from research_team.application.timeline_read import MAX_TIMELINE_BANDS

    source = f"```component:timeline\nid: t\nlimit: {MAX_TIMELINE_BANDS + 1}\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        f"limit: expected a whole number from 1 to {MAX_TIMELINE_BANDS}, "
        f"got {MAX_TIMELINE_BANDS + 1}"
    ]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/application/test_components.py -k timeline -v`
Expected: FAIL — the blocks are `unknown=True`.

- [ ] **Step 3: Register `timeline`**

Add the import beside the `MAX_NEIGHBORHOOD_DEPTH` one, subject to the same cycle check:

```python
from research_team.application.timeline_read import MAX_TIMELINE_BANDS
```

Add to `REGISTRY` after `"graph"`:

```python
    "timeline": ComponentType(
        name="timeline",
        version=1,
        summary=(
            "This project's dated entities on an axis, filtered by type and "
            "date range. Not scoped to one entity -- there is no such filter."
        ),
        example=(
            "```component:timeline\n"
            "id: fourth-century-people\n"
            "entity_type: Person\n"
            'from: "0300-01-01"\n'
            'to: "0400-01-01"\n'
            "```"
        ),
        fields={
            "entity_type": Spec(text),
            # `from` and `to` are ISO instants bounding a half-open window;
            # either may be omitted for an open end. Checked as text rather
            # than parsed here: the route answers its own 422 naming which
            # parameter was wrong, and a second date parser in this module
            # would be a second thing to keep in step with it.
            "from": Spec(text),
            "to": Spec(text),
            "limit": Spec(integer_between(1, MAX_TIMELINE_BANDS)),
        },
        resolved=True,
        craft=(
            "Quote the dates. An unquoted `from: 0300-01-01` is a YAML date, "
            "not a string, and YAML will not give you back the leading zero.",
            "There is no entity filter, and `entity:` here does nothing -- the "
            "route filters by type and range only. If you want one entity's "
            "dates, say them in a sentence.",
            "Narrow the window to the span you are actually discussing. A "
            "timeline of everything is a bar chart of the corpus rather than "
            "an illustration of your point.",
        ),
    ),
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/application/test_components.py -k timeline -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add the timeline fixture-trap case**

Append to `tests/integration/test_resolved_widget_routes.py`:

```python
async def test_a_timeline_answers_for_a_project_nothing_has_opened(client):
    """The only request a `timeline` widget makes.

    `_timeline_reader` opens through `graphs` so the timeline and the graph
    read the *same* store rather than two folds of one log -- which is exactly
    the call a refactor drops, and dropping it is a 503 on the first request
    for every project and a 200 on every one after.
    """
    project_id = await _untouched_project(client)

    response = await client.get(
        f"/api/projects/{project_id}/timeline?entity_type=Person&from=0300-01-01"
    )

    assert response.status_code == 200
    assert response.json()["bands"] == []
```

- [ ] **Step 6: Write the failing repository test**

Create `frontend/src/infrastructure/http/timeline-repository.test.ts`:

```ts
/** The widened timeline read: a window, not just a type.
 *
 * `from` is spelled `from` on the wire and `from_` in the route signature --
 * FastAPI's `Query(alias="from")` is what reconciles them, and a client that
 * sent `from_` would get the whole timeline back with nothing saying the
 * window was ignored. That is what the first assertion is really about.
 */
import { expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { HttpTimelineRepository } from './timeline-repository.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const clientReturning = (body: unknown) => ({
  get: vi.fn().mockResolvedValue(body),
})

const EMPTY = { bands: [], undated_count: 0, truncated: false }

it('carries every part of the window into the query string', async () => {
  const http = clientReturning(EMPTY)
  const repository = new HttpTimelineRepository(http as never)

  await repository.timeline(PROJECT, {
    entityType: 'Person',
    from: '0300-01-01',
    to: '0400-01-01',
    limit: 50,
  })

  const [url] = http.get.mock.calls[0] as [string]
  expect(url).toContain('entity_type=Person')
  expect(url).toContain('from=0300-01-01')
  expect(url).toContain('to=0400-01-01')
  expect(url).toContain('limit=50')
  expect(url).not.toContain('from_=')
})

it('omits what the caller did not ask for', async () => {
  // `query()` drops undefined keys, so an absent bound is an open end rather
  // than an empty parameter the route would have to interpret.
  const http = clientReturning(EMPTY)
  const repository = new HttpTimelineRepository(http as never)

  await repository.timeline(PROJECT)

  const [url] = http.get.mock.calls[0] as [string]
  expect(url).not.toContain('?')
})

it('carries the counts that say what was left out', async () => {
  const http = clientReturning({ bands: [], undated_count: 412, truncated: true })
  const repository = new HttpTimelineRepository(http as never)

  const timeline = await repository.timeline(PROJECT)

  expect(timeline.undatedCount).toBe(412)
  expect(timeline.truncated).toBe(true)
})
```

Read `frontend/src/infrastructure/http/http-client.ts` for `query()`'s exact behaviour with an empty object before writing the second assertion — if it emits `?` for an empty record, assert `toBe(...)` on the bare path instead.

- [ ] **Step 7: Widen the port and the repository**

In `frontend/src/application/ports/repositories.ts`, replace `TimelineRepository.timeline` (:520):

```ts
/** A window over the project's timeline. Every part optional: the whole
 *  timeline is a real thing to ask for, and it is the console's own request. */
export interface TimelineWindowQuery {
  readonly entityType?: string
  /** ISO instants bounding a half-open `[from, to)` window; either may be
   *  omitted for an open end. Sent as `from`/`to` -- the route aliases them
   *  back onto `from_`, because `from` is a Python keyword. */
  readonly from?: string
  readonly to?: string
  readonly limit?: number
}

export interface TimelineRepository {
  /** The project's dated entities in time order, inside `window`, up to the
   *  server's cap.
   *
   * `undatedCount` on the result is not optional dressing -- most entities in
   * a real graph carry no dates, so a timeline is a view of a minority of the
   * corpus and the caller must show the denominator. `truncated` says the cap
   * bit, the same way `WholeGraph.truncated` does.
   *
   * An options object rather than the positional `entityType` this replaced:
   * three of the four parameters are optional and independent, and a
   * positional list of four optionals is a call site nobody can read. */
  timeline(projectId: ProjectId, window?: TimelineWindowQuery): Promise<Timeline>
}
```

In `frontend/src/infrastructure/http/timeline-repository.ts`:

```ts
import type { TimelineRepository, TimelineWindowQuery } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toTimeline } from './mappers.ts'

export class HttpTimelineRepository implements TimelineRepository {
  constructor(private readonly http: HttpClient) {}

  async timeline(projectId: ProjectId, window: TimelineWindowQuery = {}) {
    const body = await this.http.get(
      // `from`/`to` are the wire names. The route's parameter is `from_`
      // because `from` is a Python keyword, and FastAPI's `Query(alias=...)`
      // is what reconciles the two -- a client sending `from_` would get the
      // whole timeline back with nothing saying its window was ignored.
      `/api/projects/${seg(projectId)}/timeline${query({
        entity_type: window.entityType,
        from: window.from,
        to: window.to,
        limit: window.limit,
      })}`,
      dto.timelineDto,
    )
    return toTimeline(body)
  }
}
```

Then update every existing call site. `frontend/src/presentation/research/TimelinePane.tsx` (or the hook beneath it) passes `entityType` positionally today; change it to `{ entityType }`, using the spread guard where the value may be undefined:

```ts
timeline(projectId, { ...(entityType ? { entityType } : {}) })
```

- [ ] **Step 8: Run the repository test**

Run: `cd frontend && npx vitest run src/infrastructure/http/timeline-repository.test.ts`
Expected: PASS, 3 tests. Then `cd frontend && npx tsc --noEmit` (or `npm run typecheck`) to confirm no caller was missed.

- [ ] **Step 9: Add the reader and the key**

In `frontend/src/domain/lesson/widgets.ts`:

```ts
/** A `timeline` widget's window. Nullable rather than defaulted throughout:
 *  an omitted bound is an open end, and a default would silently narrow a
 *  request the author left wide. */
export interface TimelineWindow {
  readonly entityType: string | null
  readonly from: string | null
  readonly to: string | null
  readonly limit: number | null
}

export const readTimelineQuery = (block: ComponentBlock): TimelineWindow => ({
  entityType: str(block.data['entity_type']),
  from: str(block.data['from']),
  to: str(block.data['to']),
  limit: num(block.data['limit']),
})
```

In `frontend/src/application/queries/keys.ts`, after `neighborhood`:

```ts
  /** One window over the timeline. Every bound is in the key: two widgets
   *  asking for two centuries are two different answers, and a key on the
   *  project alone would show one century's bands under the other's heading
   *  -- the same mistake `document`'s range key exists to avoid. */
  timeline: (
    project: ProjectId,
    window: {
      entityType?: string | null
      from?: string | null
      to?: string | null
      limit?: number | null
    },
  ) =>
    [
      'timeline',
      project,
      window.entityType ?? null,
      window.from ?? null,
      window.to ?? null,
      window.limit ?? null,
    ] as const,
```

- [ ] **Step 10: Write the failing jsdom test**

Create `frontend/src/presentation/lesson/TimelineWidget.test.tsx`:

```tsx
/** What jsdom can judge about the timeline widget: the request it makes and
 *  the counts it is obliged to show.
 *
 * The height assertion is in `TimelineWidget.browser.test.tsx` for
 * `GraphWidget`'s reason, and the same one CLAUDE.md gives: jsdom lays
 * nothing out.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { TimelineWidget } from './TimelineWidget.tsx'

vi.mock('../research/TimelineCanvas.tsx', () => ({
  TimelineCanvas: ({ bands }: { bands: readonly unknown[] }) => (
    <div data-testid="timeline-canvas" data-bands={bands.length} />
  ),
}))

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('fourth-century'),
  type: 'timeline',
  data,
  raw: '',
  lang: 'component:timeline',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
})

const attempts = {} as unknown as AttemptsApi

const band = (id: string) => ({
  id,
  name: `Entity ${id}`,
  entityType: 'Person',
  extent: 'AD 300–400',
  start: '0300-01-01',
  end: '0400-01-01',
  precision: 'year',
  uncertainty: '',
})

const renderWidget = (
  data: Record<string, unknown>,
  {
    timeline = vi
      .fn()
      .mockResolvedValue({ bands: [band('b1')], undatedCount: 0, truncated: false }),
    projectId = PROJECT as ProjectId | undefined,
  } = {},
) => {
  const container = { timeline: { timeline } } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    timeline,
    ...render(
      <TimelineWidget block={block(data)} attempts={attempts} {...(projectId ? { projectId } : {})} />,
      { wrapper },
    ),
  }
}

it('asks for exactly the window the author wrote', async () => {
  const { timeline } = renderWidget({
    entity_type: 'Person',
    from: '0300-01-01',
    to: '0400-01-01',
  })

  await waitFor(() =>
    expect(timeline).toHaveBeenCalledWith(PROJECT, {
      entityType: 'Person',
      from: '0300-01-01',
      to: '0400-01-01',
    }),
  )
})

it('asks for the whole timeline when the author bounded nothing', async () => {
  // An omitted bound is an open end. Red against a reader that defaults
  // `from` to anything -- the request would silently narrow.
  const { timeline } = renderWidget({})

  await waitFor(() => expect(timeline).toHaveBeenCalledWith(PROJECT, {}))
})

it('says how many entities carry no dates at all', async () => {
  // The denominator. Most entities in a real graph carry no dates, so a
  // timeline is a view of a minority of the corpus -- and a widget that shows
  // eight bands without saying four hundred were undated has misrepresented
  // the project. Red against a widget that renders only `bands`.
  renderWidget(
    { entity_type: 'Person' },
    {
      timeline: vi
        .fn()
        .mockResolvedValue({ bands: [band('b1')], undatedCount: 412, truncated: false }),
    },
  )

  await waitFor(() => expect(screen.getByText(/412/)).toBeInTheDocument())
})

it('says when the server capped the answer', async () => {
  // A timeline that quietly drops two thirds of its bands is the read-model
  // failure this project has already had once, and `truncated` is the only
  // thing that shows it.
  renderWidget(
    {},
    {
      timeline: vi
        .fn()
        .mockResolvedValue({ bands: [band('b1')], undatedCount: 0, truncated: true }),
    },
  )

  await waitFor(() => expect(screen.getByText(/more than could be shown|truncated/i)).toBeInTheDocument())
})

it('says so plainly when nothing in the window is dated', async () => {
  renderWidget(
    { entity_type: 'Person' },
    { timeline: vi.fn().mockResolvedValue({ bands: [], undatedCount: 9, truncated: false }) },
  )

  await waitFor(() => expect(screen.getByText(/nothing dated/i)).toBeInTheDocument())
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('renders nothing but a note with no project in scope, and fetches nothing', () => {
  const { timeline } = renderWidget({ entity_type: 'Person' }, { projectId: undefined })

  expect(timeline).not.toHaveBeenCalled()
  expect(screen.getByText(/no project/i)).toBeInTheDocument()
})
```

- [ ] **Step 11: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/lesson/TimelineWidget.test.tsx`
Expected: FAIL — `Failed to resolve import "./TimelineWidget.tsx"`.

- [ ] **Step 12: Write the widget**

Create `frontend/src/presentation/lesson/TimelineWidget.tsx`:

```tsx
import { useQuery } from '@tanstack/react-query'
import { lazy, Suspense } from 'react'

import { useContainer } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { queryKeys } from '@application/queries/keys.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import type { TimelineWindow } from '@domain/lesson/widgets.ts'
import { readTimelineQuery } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

const TimelineCanvas = lazy(() =>
  import('../research/TimelineCanvas.tsx').then((module) => ({ default: module.TimelineCanvas })),
)

/** The project's dated entities on an axis, inside an answer.
 *
 * **Not entity-scoped, and the syntax deliberately does not imply it is.**
 * `GET /timeline` filters by type and range and has no entity or topic
 * filter, so an `entity:` field here would be one that silently did nothing
 * -- worse than the capability being absent, because the author would believe
 * they had asked for something.
 *
 * `undatedCount` and `truncated` are both rendered, and that is not dressing.
 * Most entities in a real graph carry no dates, so this is a view of a
 * minority of the corpus; a timeline that quietly drops two thirds of its
 * bands is the read-model failure this project has already had once, and
 * these counts are the only thing that shows it.
 *
 * The box has an explicit height for `GraphWidget`'s reason, measured in
 * `TimelineWidget.browser.test.tsx`.
 */
export const TimelineWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const window = readTimelineQuery(block)

  if (!projectId) {
    // The `unavailable` state, drawn here rather than by `ResolvedFrame`:
    // there is no entity reference to frame, and the honest degradation is a
    // sentence saying this page cannot look it up.
    return (
      <div className="cmp-body">
        <p className="cmp-ref-note">A timeline needs a project in scope, and this page has none.</p>
      </div>
    )
  }

  return (
    <div className="cmp-body">
      <Bands projectId={projectId} window={window} />
    </div>
  )
}

/** The window as the port wants it: absent keys rather than nulls, so an
 *  omitted bound stays an open end all the way to the query string. */
const asQuery = (window: TimelineWindow) => ({
  ...(window.entityType ? { entityType: window.entityType } : {}),
  ...(window.from ? { from: window.from } : {}),
  ...(window.to ? { to: window.to } : {}),
  ...(window.limit === null ? {} : { limit: window.limit }),
})

const Bands = ({ projectId, window }: { projectId: ProjectId; window: TimelineWindow }) => {
  const { timeline } = useContainer()
  const result = useQuery({
    queryKey: queryKeys.timeline(projectId, window),
    queryFn: () => timeline.timeline(projectId, asQuery(window)),
  })

  if (result.isPending) return <p className="cmp-ref-note">reading the timeline…</p>
  if (result.isError || !result.data) {
    return <p className="cmp-ref-note">This project&rsquo;s timeline could not be read just now.</p>
  }

  const { bands, undatedCount, truncated } = result.data

  return (
    <>
      {bands.length === 0 ? (
        <p className="cmp-ref-note">Nothing dated matches that window in this project.</p>
      ) : (
        <div className="cmp-timeline-box" data-timeline-widget>
          <Suspense fallback={<p className="cmp-ref-note">loading the axis…</p>}>
            <TimelineCanvas bands={bands} selected={null} onSelect={() => {}} />
          </Suspense>
        </div>
      )}
      <p className="cmp-timeline-counts">
        {bands.length} dated
        {undatedCount > 0 ? `, ${undatedCount} with no dates at all` : ''}
        {truncated ? ' — more than could be shown' : ''}
      </p>
    </>
  )
}
```

The counts render even when `bands` is empty, deliberately: "nothing dated matches, and 412 entities carry no dates" is a more useful answer than either half alone.

- [ ] **Step 13: Add the styles**

Append to `frontend/src/styles/components.css`:

```css
/* An explicit height for `.cmp-graph-box`'s reason: `TimelineCanvas` draws
   into an SVG sized by its container, and a markdown flow gives it none.
   Measured in `TimelineWidget.browser.test.tsx`; jsdom reports 0 here
   whatever this rule says. */
.cmp-timeline-box {
  position: relative;
  width: 100%;
  min-height: 12rem;
  overflow: hidden;
  border: 0;
  border-radius: 0.5rem;
  background: var(--bg-raised);
}

.cmp-timeline-counts {
  margin: 0.5rem 0 0;
  font-size: 0.75rem;
  color: var(--fg-muted);
}
```

- [ ] **Step 14: Write the browser measurement test**

Create `frontend/src/presentation/lesson/TimelineWidget.browser.test.tsx`, in `GraphWidget.browser.test.tsx`'s shape:

```tsx
/** That the timeline widget has a height inside a markdown flow.
 *
 * `TimelineCanvas` is pure SVG sized by its container, and a markdown flow
 * gives it none. jsdom reports `0x0` here whatever `.cmp-timeline-box` says,
 * so this is the suite that can judge it.
 *
 * **Proved red** by deleting `min-height` from `.cmp-timeline-box`: the box
 * measures 0 high and the assertion fails. Re-take that measurement if the
 * rule is edited.
 *
 * The canvas is *not* mocked here, unlike the jsdom test: `TimelineCanvas`
 * returns `null` when `spanOf(bands)` is null (`TimelineCanvas.tsx:120`), so
 * a fixture with no usable dates would measure an empty box and pass for the
 * wrong reason. The bands below carry real ISO bounds for that reason.
 */
```

Write the body against the real `TimelineCanvas`, with two bands carrying distinct `start`/`end` values, assert `getBoundingClientRect().height` on `[data-timeline-widget]` is greater than 150, and reuse the provider helper from `TimelineWidget.test.tsx` — lift it into a shared local helper rather than duplicating the fixture, so the two files cannot disagree about what a resolved timeline looks like.

- [ ] **Step 15: Wire it into `RENDERERS`**

```tsx
import { TimelineWidget } from './TimelineWidget.tsx'
```

```tsx
  graph: GraphWidget,
  timeline: TimelineWidget,
```

- [ ] **Step 16: Run the tests**

```bash
cd frontend && npx vitest run src/presentation/lesson src/domain/lesson src/infrastructure/http src/presentation/research
```

Then, alone:

```bash
cd frontend && npm run test:browser
```
Expected: both pass. Before trusting the browser test green, delete `min-height` from `.cmp-timeline-box`, re-run it, confirm red, restore.

- [ ] **Step 17: Run the gates**

```bash
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd frontend && npm run verify
```

- [ ] **Step 18: Rebuild the committed console and commit**

```bash
cd frontend && npm run build
cd ..
git add research_team/application/components.py tests frontend/src research_team/interfaces/web/static
git commit -m 'feat: add the timeline component, and widen the timeline read to a window

The component is not entity-scoped and the syntax deliberately does not imply
it is. GET /timeline filters by type and range and has no entity or topic
filter, so an entity: field here would be one that silently did nothing --
worse than the capability being absent, because the author would believe they
had asked for something. The registry has no such field and the craft note
says so outright.

TimelineRepository.timeline takes an options object rather than a positional
entityType. Three of the four parameters are optional and independent, and a
positional list of four optionals is a call site nobody can read. Every
existing caller is updated in this commit.

from/to are the wire names; the route parameter is from_ because from is a
Python keyword, and FastAPI Query(alias=) reconciles them. A client sending
from_ would get the whole timeline back with nothing saying its window was
ignored, which is what the repository test pins.

undated_count and truncated are both rendered, and the counts show even when
no band does. Most entities in a real graph carry no dates, so this is a view
of a minority of the corpus; a timeline that quietly drops two thirds of its
bands is the read-model failure this project has already had once, and these
counts are the only thing that shows it.

The box height has a browser test. jsdom reports 0 whatever the stylesheet
says, and the canvas draws into what it measures. TimelineCanvas is not
mocked there: it returns null when no band has a usable span, so a mocked one
would measure an empty box and pass for the wrong reason.'
```

---

### Task 7: `compare`

**Columns are author-declared, and this is a constraint discovered, not a choice.** The natural design fills a table from per-type properties, and `GET /ontology` (`app.py:2535`) does not have them: a class's `members` are `{name, ordinal}` strings, with no attribute schema anywhere. There is nothing to derive columns from.

So `compare` resolves each named entity — linking it, and showing its `entity_type` — and the model writes the row labels and cell prose itself. **The resolution is what it adds over a markdown table:** every column head is a real entity or is visibly not one.

Lowest value of the five and last for that reason. It is included because the resolution machinery is already paid for by the other four.

**Files:**
- Modify: `research_team/application/components.py` (a `compare` entry in `REGISTRY`)
- Modify: `tests/application/test_components.py`
- Modify: `frontend/src/domain/lesson/widgets.ts` (`readCompare`)
- Create: `frontend/src/presentation/lesson/CompareWidget.tsx`
- Create: `frontend/src/presentation/lesson/CompareWidget.test.tsx`
- Modify: `frontend/src/presentation/lesson/LessonDocument.tsx`
- Modify: `frontend/src/styles/components.css`

No fixture-trap case is added here: `compare` makes exactly the same request `definition` does (`/graph/entities?name=`), which Task 3's `test_a_name_search_answers_for_a_project_nothing_has_opened` already covers. Adding a second identical test would be a second name for one claim.

No browser test either: nothing here is a measurement. The table is ordinary flow layout, and its correctness is roles, headers and text, which jsdom judges in a second.

**Interfaces:**
- Consumes: `useEntityReference`, `ResolvedFrame` (Task 2).
- Produces:
  - `REGISTRY["compare"]`, fields `entities` (`string_list(minimum=2)`, required), `rows` (`listing({label, cells})`, required)
  - `CompareRow = { readonly label: string; readonly cells: readonly string[] }`
  - `Compare = { readonly entities: readonly string[]; readonly rows: readonly CompareRow[] }`
  - `readCompare(block: ComponentBlock): Compare`
  - `<CompareWidget block attempts projectId? />`

- [ ] **Step 1: Write the failing registry test**

Append to `tests/application/test_components.py`:

```python
COMPARE = """\\
```component:compare
id: two-emperors
entities: [Diocletian, Constantine]
rows:
  - label: Reign
    cells:
      - "284-305"
      - "306-337"
  - label: Religious policy
```
"""


def test_compare_carries_its_entities_and_rows_through_both_views():
    document = parse_document(COMPARE, path="lesson.md")

    author = project(document, view="author")["blocks"][0]
    learner = project(document, view="learner")["blocks"][0]

    assert learner["data"] == author["data"]
    assert author["data"]["entities"] == ["Diocletian", "Constantine"]
    assert author["data"]["rows"][0]["label"] == "Reign"
    assert learner["resolved"] is True


def test_compare_needs_two_entities_to_compare():
    """One column is not a comparison, and a table of one is a definition
    with extra ceremony."""
    source = "```component:compare\nid: c\nentities: [Constantine]\nrows:\n  - label: Reign\n```\n"

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == [
        "entities: expected at least 2 entries, got 1"
    ]


def test_compare_names_a_non_string_entity_by_its_subscript():
    source = (
        "```component:compare\n"
        "id: c\n"
        "entities:\n"
        "  - name: Constantine\n"
        "  - Diocletian\n"
        "rows:\n"
        "  - label: Reign\n"
        "```\n"
    )

    block = parse_document(source, path="lesson.md").components[0]

    assert [str(note) for note in block.errors] == ["entities[0]: expected text, got mapping"]


def test_a_compare_row_may_carry_no_cells_at_all():
    """A row label with nothing under it is a real thing to write -- it is the
    spec's own example -- and it renders as an empty row rather than an error.
    Red against `cells` being required."""
    source = (
        "```component:compare\nid: c\nentities: [A, B]\nrows:\n  - label: Reign\n```\n"
    )

    assert parse_document(source, path="lesson.md").components[0].errors == ()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/application/test_components.py -k compare -v`
Expected: FAIL — the blocks are `unknown=True`.

- [ ] **Step 3: Register `compare`**

Add to `REGISTRY` after `"timeline"`:

```python
    "compare": ComponentType(
        name="compare",
        version=1,
        summary=(
            "A side-by-side table over two or more named entities. You write "
            "the rows; the browser resolves each column head against this "
            "project's graph and links the ones it finds."
        ),
        example=(
            "```component:compare\n"
            "id: two-emperors\n"
            "entities: [Diocletian, Constantine]\n"
            "rows:\n"
            "  - label: Reign\n"
            "    cells:\n"
            '      - "284-305"\n'
            '      - "306-337"\n'
            "  - label: Religious policy\n"
            "    cells:\n"
            '      - "Persecution"\n'
            '      - "Toleration, then patronage"\n'
            "```"
        ),
        fields={
            "entities": Spec(string_list(minimum=2), required=True),
            "rows": Spec(
                listing(
                    {
                        "label": Spec(text, required=True),
                        # Optional, and short rows are fine: a label with
                        # nothing under it is a real thing to write, and the
                        # renderer pads to the column count rather than
                        # refusing. Requiring one cell per entity would make
                        # the commonest edit -- adding a third column --
                        # invalidate every row at once.
                        "cells": Spec(string_list(minimum=0)),
                    }
                ),
                required=True,
            ),
        },
        resolved=True,
        craft=(
            "Write each entity name exactly as your prose does, and exactly as "
            "the sources spell it -- the column heads are looked up by name, "
            "and one this project does not hold renders as plain text with the "
            "rest of the table intact.",
            "You write the rows yourself: nothing in this project stores "
            "per-type attributes, so there is no schema to derive columns from. "
            "Pick the dimensions the comparison actually turns on.",
            "Cells are in the same order as `entities`. A short row is padded, "
            "so a dimension one entity has and another does not is fine to "
            "leave blank -- that blank is itself the comparison.",
        ),
    ),
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/application/test_components.py -k compare -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Add the reader**

In `frontend/src/domain/lesson/widgets.ts`:

```ts
export interface CompareRow {
  readonly label: string
  /** In the same order as `Compare.entities`. Short rows are padded at
   *  render, not here: how many columns there are is the table's business,
   *  and a reader that padded would need the entity list to do it. */
  readonly cells: readonly string[]
}

export interface Compare {
  readonly entities: readonly string[]
  readonly rows: readonly CompareRow[]
}

export const readCompare = (block: ComponentBlock): Compare => ({
  entities: list(block.data['entities']).map((name) => str(name) ?? ''),
  rows: list(block.data['rows']).map((raw) => {
    const row = rec(raw)
    return {
      label: str(row['label']) ?? '',
      cells: list(row['cells']).map((cell) => str(cell) ?? ''),
    }
  }),
})
```

- [ ] **Step 6: Write the failing widget test**

Create `frontend/src/presentation/lesson/CompareWidget.test.tsx`:

```tsx
/** A table whose column heads are resolved against the project's graph.
 *
 * The resolution is the whole of what this adds over a markdown table, so the
 * cases that matter are the mixed ones: a table where one head resolved and
 * another did not must still be a readable table. A widget that refused to
 * draw because one name missed would be strictly worse than the prose it
 * replaced.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { CompareWidget } from './CompareWidget.tsx'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('two-emperors'),
  type: 'compare',
  data,
  raw: '',
  lang: 'component:compare',
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
})

const attempts = {} as unknown as AttemptsApi

/** Resolves whichever names are in `known`, and finds nothing for the rest --
 *  which is how a mixed table is built. */
const searchOver = (known: Record<string, string>) =>
  vi.fn().mockImplementation((_project: unknown, name: string) =>
    Promise.resolve({
      entities: known[name]
        ? [{ id: known[name], name, entityType: 'Person' }]
        : [],
      truncated: false,
    }),
  )

const DATA = {
  entities: ['Diocletian', 'Constantine'],
  rows: [
    { label: 'Reign', cells: ['284-305', '306-337'] },
    { label: 'Religious policy', cells: ['Persecution'] },
  ],
}

const renderWidget = (
  data: Record<string, unknown> = DATA,
  {
    search = searchOver({ Diocletian: 'e1', Constantine: 'e2' }),
    projectId = PROJECT as ProjectId | undefined,
  } = {},
) => {
  const container = { graph: { search } } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
  return {
    search,
    ...render(
      <CompareWidget block={block(data)} attempts={attempts} {...(projectId ? { projectId } : {})} />,
      { wrapper },
    ),
  }
}

it('draws a column per entity and a row per label', async () => {
  renderWidget()

  const table = screen.getByRole('table')
  // Three columns: the row-label column, then one per entity.
  expect(within(table).getAllByRole('columnheader')).toHaveLength(3)
  expect(within(table).getAllByRole('rowheader')).toHaveLength(2)
  expect(within(table).getByText('284-305')).toBeInTheDocument()
})

it('shows the entity type of a head that resolved', async () => {
  renderWidget()

  // The resolution is what this adds over a markdown table, and the type is
  // how a reader sees it happened.
  await waitFor(() => expect(screen.getAllByText('Person')).toHaveLength(2))
})

it('keeps the table readable when one head is not in the graph', async () => {
  renderWidget(DATA, { search: searchOver({ Constantine: 'e2' }) })

  await waitFor(() => expect(screen.getByText(/not in this project's graph/i)).toBeInTheDocument())
  // The rest of the table is intact -- red against a widget that refuses to
  // draw when any head misses.
  expect(screen.getByText('284-305')).toBeInTheDocument()
  expect(screen.getByRole('table')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it('pads a short row rather than shifting its cells left', async () => {
  // "Religious policy" has one cell and two entities. Red against a renderer
  // that maps over `cells`: the single value would land under Diocletian and
  // Constantine would silently lose a column, which reads as data rather
  // than as a gap.
  renderWidget()

  const row = screen.getByRole('row', { name: /Religious policy/ })
  expect(within(row).getAllByRole('cell')).toHaveLength(2)
})

it('draws the table with no project in scope, and looks nothing up', () => {
  const { search } = renderWidget(DATA, { projectId: undefined })

  expect(screen.getByRole('table')).toBeInTheDocument()
  expect(screen.getByText('Diocletian')).toBeInTheDocument()
  expect(search).not.toHaveBeenCalled()
})
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cd frontend && npx vitest run src/presentation/lesson/CompareWidget.test.tsx`
Expected: FAIL — `Failed to resolve import "./CompareWidget.tsx"`.

- [ ] **Step 8: Write the widget**

Create `frontend/src/presentation/lesson/CompareWidget.tsx`:

```tsx
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { useEntityReference } from '@application/lesson/use-entity-reference.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { readCompare } from '@domain/lesson/widgets.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { ResolvedFrame } from './ResolvedFrame.tsx'
import { Prose } from './widgets.tsx'

/** A side-by-side table whose column heads are resolved against the graph.
 *
 * **Columns are author-declared, and that is a constraint discovered rather
 * than chosen.** The natural design fills the table from per-type properties,
 * and `GET /ontology` does not have them -- a class's members are
 * `{name, ordinal}` strings with no attribute schema anywhere. There is
 * nothing to derive columns from, so the model writes them.
 *
 * What resolution adds over a plain markdown table is therefore narrow and
 * worth stating: every column head is a real entity in this project or is
 * visibly not one. A head that misses does not take the table down -- the
 * rows are the author's prose, and they are still the answer.
 */
export const CompareWidget = ({
  block,
  projectId,
}: {
  block: ComponentBlock
  attempts: AttemptsApi
  projectId?: ProjectId
}) => {
  const compare = readCompare(block)

  return (
    <div className="cmp-body">
      <table className="cmp-compare">
        <thead>
          <tr>
            {/* The corner cell. Empty and `scope`-less on purpose: it heads
                neither a row nor a column, and giving it a scope would put a
                blank string into the accessibility tree as a header. */}
            <th />
            {compare.entities.map((name) => (
              <th key={name} scope="col">
                <Head projectId={projectId} name={name} />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {compare.rows.map((row) => (
            <tr key={row.label}>
              <th scope="row">{row.label}</th>
              {/* Mapped over `entities`, never over `cells`: a short row must
                  pad on the right, and mapping over cells would shift a
                  single value under the first column and silently drop a
                  column from the table. */}
              {compare.entities.map((name, column) => (
                <td key={name}>
                  <Prose text={row.cells[column] ?? ''} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

const Head = ({ projectId, name }: { projectId: ProjectId | undefined; name: string }) => {
  const resolved = useEntityReference(projectId, { entity: name, entityId: null })

  return (
    // No `onPick`: a picker inside a column head would be a control in a
    // table header, and there is nothing this widget does differently with a
    // pinned id -- it shows the name and the type either way.
    <ResolvedFrame reference={resolved} name={name}>
      {(entity) => (
        <>
          <span className="cmp-ref-name">{entity.name}</span>
          {entity.entityType ? (
            <span className="cmp-ref-pick-type">{entity.entityType}</span>
          ) : null}
        </>
      )}
    </ResolvedFrame>
  )
}
```

`useEntityReference` is called once per column head, from a child component — a hook cannot be called in a loop from the parent. That is why `Head` exists as its own component rather than as a helper function.

- [ ] **Step 9: Wire it into `RENDERERS`**

```tsx
import { CompareWidget } from './CompareWidget.tsx'
```

```tsx
  timeline: TimelineWidget,
  compare: CompareWidget,
```

- [ ] **Step 10: Add the styles**

Append to `frontend/src/styles/components.css`:

```css
.cmp-compare {
  width: 100%;
  border-collapse: collapse;
  /* Wide tables scroll inside their own container rather than pushing the
     document sideways -- a markdown column is narrow and three entities is
     already wider than it. */
  display: block;
  overflow-x: auto;
}

.cmp-compare th,
.cmp-compare td {
  /* `border-0` first, then the one edge that is wanted. A bare `border-solid`
     beside `border-bottom` gives the other three sides the browser's `medium`
     (~3px) and puts a box round every cell. */
  border: 0;
  border-bottom: 1px solid var(--line);
  padding: 0.5rem 0.75rem;
  text-align: left;
  vertical-align: top;
}

.cmp-compare thead th {
  font-weight: 600;
}
```

- [ ] **Step 11: Run the tests, the gates, and rebuild**

```bash
cd frontend && npx vitest run src/presentation/lesson src/domain/lesson
cd .. && uv run pytest -q && uv run ruff check . && uv run ruff format --check .
cd frontend && npm run verify && npm run build
cd .. && git status --short research_team/interfaces/web/static
```
Expected: all pass; `assets/app.js` and `assets/index.css` modified.

- [ ] **Step 12: Commit**

```bash
git add research_team/application/components.py tests frontend/src research_team/interfaces/web/static
git commit -m 'feat: add the compare component, with author-declared columns

Columns are author-declared and that is a constraint discovered, not chosen.
The natural design fills the table from per-type properties and GET /ontology
does not have them: a class members are {name, ordinal} strings with no
attribute schema anywhere. There is nothing to derive columns from.

What resolution adds over a markdown table is therefore narrow and worth
stating plainly: every column head is a real entity in this project or is
visibly not one. A head that misses does not take the table down -- the rows
are the author prose and they are still the answer.

Cells are mapped over entities, never over cells. A short row pads on the
right; mapping over cells would shift a single value under the first column
and silently drop a column, which reads as data rather than as a gap.

No browser test: nothing here is a measurement, and roles, headers and text
are what jsdom judges well. No fixture-trap case either -- compare makes
exactly the request definition does, and a second name for one claim is not
a second test.

Lowest value of the five and last for that reason. It is here because the
resolution machinery was already paid for by the other four.'
```

---

### Task 8: Prompt wiring, `ASK_COMPONENT_TYPES`, and the final rebuild

The five types exist and render; nothing has told a model it may write one. This task opens them to the ask agent and checks that the generated reference actually carries them.

`ASK_COMPONENT_TYPES` (`ask_components.py:24`) gains all five. Unlike `checklist`, they are wanted in an ask — **an ask is precisely where a reader asks about the corpus**.

`COMPONENTS_FOR` is deliberately left alone. It maps *artifact types* to components for a stage writing a course file, and none of the five is an assessment item or a practice activity; adding them there would put two kilobytes of corpus-widget syntax into the prompt of a stage writing an evidence spec. If a stage should reach for them later, that is a decision with its own reasoning, not a line to add for symmetry.

**Files:**
- Modify: `research_team/application/ask_components.py:24`
- Modify: `tests/application/test_ask_components.py`
- Modify: `tests/application/test_components.py` (the `craft`-coverage assertion)
- Rebuild: `research_team/interfaces/web/static/assets/*`

**Interfaces:**
- Consumes: `REGISTRY["definition"|"evidence"|"graph"|"timeline"|"compare"]` (Tasks 3–7); `component_reference(only=...)`.
- Produces: `ASK_COMPONENT_TYPES` containing all eight names.

- [ ] **Step 1: Write the failing tests**

Append to `tests/application/test_ask_components.py`:

```python
def test_every_resolved_type_is_offered_to_the_ask_agent():
    """An ask is precisely where a reader asks about the corpus, so a widget
    that shows the corpus belongs there. `checklist` stays out for its own
    stated reason -- it needs a learner identity the ask path does not have --
    and that ruling is unaffected by these five."""
    assert set(ASK_COMPONENT_TYPES) >= {
        "definition",
        "evidence",
        "graph",
        "timeline",
        "compare",
    }
    assert "checklist" not in ASK_COMPONENT_TYPES


def test_a_resolved_component_in_an_answer_keeps_its_reference():
    """The learner default must not strip a reference. A resolved component
    has no answer key, so `project()` is identity for it -- and if that ever
    stopped holding, the ask surface is where it would show first, as a widget
    that renders nothing with no error anywhere."""
    answer = "```component:definition\nid: d1\nentity: Nicene Christianity\n```\n"

    block = answer_document(answer)["blocks"][0]

    assert block["data"]["entity"] == "Nicene Christianity"
    assert block["resolved"] is True
    assert block["withheld"] == []
```

Append to `tests/application/test_components.py`:

```python
@pytest.mark.parametrize(
    "name", ["definition", "evidence", "graph", "timeline", "compare"]
)
def test_every_resolved_type_tells_the_model_how_to_write_a_good_one(name):
    """`craft` is not decoration: the failure mode this format produces is a
    model inventing a tidy canonical name for an entity extraction stored as
    it appeared. A type with no craft notes is one whose failure mode nobody
    wrote down, and the model reads this every time it authors."""
    component = REGISTRY[name]

    assert component.craft, f"{name} has no craft guidance"
    assert component.summary
    assert f"component:{name}" in component.example


@pytest.mark.parametrize("name", ["definition", "graph", "compare"])
def test_every_name_resolved_type_warns_about_inventing_a_canonical_name(name):
    """The one thing every by-name reference has to say, and the only failure
    mode of this design a model can avoid on its own.

    Red against craft guidance that describes the syntax and not the trap:
    'Constantine I' for an entity stored as 'Constantine' resolves to nothing,
    the widget renders as a plain word, and nothing tells the author why.
    """
    craft = " ".join(REGISTRY[name].craft).lower()

    assert "exactly as" in craft


def test_the_generated_reference_carries_every_resolved_example():
    """What the ask agent is actually handed. A type absent from here is a
    type the model will never write, however well registered it is."""
    reference = component_reference(
        only=["definition", "evidence", "graph", "timeline", "compare"]
    )

    for name in ("definition", "evidence", "graph", "timeline", "compare"):
        assert f"component:{name}" in reference
```

Add `REGISTRY` to that file's import list from `research_team.application.components` if it is not there already.

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/application/test_ask_components.py tests/application/test_components.py -k resolved -v`
Expected: FAIL — `test_every_resolved_type_is_offered_to_the_ask_agent` fails on the set comparison; the `craft` cases pass already, since Tasks 3–7 wrote that guidance.

- [ ] **Step 3: Open the five to the ask agent**

In `research_team/application/ask_components.py`, replace `ASK_COMPONENT_TYPES` (:24-32):

```python
ASK_COMPONENT_TYPES: tuple[str, ...] = (
    "mcq",
    "cloze",
    "flashcards",
    "definition",
    "evidence",
    "graph",
    "timeline",
    "compare",
)
"""What the ask agent may author.

`checklist` is absent and that is a ruling, not an omission. A checklist is a
record of a procedure someone performed, and its only interesting mode is
`persist: true` -- which needs a learner identity the ask path deliberately
does not have. A checklist that cannot remember a tick is a list of bullets
with worse affordances than a list of bullets.

The five resolved types are all here, and for the opposite reason. An ask is
precisely where a reader asks about the corpus, and a resolved component is
the only thing in this registry that can answer with what the project
actually holds rather than with what the model can describe. A widget whose
reference misses renders as prose, so the cost of offering one that does not
land is a word rather than an error -- which is what makes offering all five
at once reasonable rather than reckless.
"""
```

- [ ] **Step 4: Run them to verify they pass**

Run: `uv run pytest tests/application/test_ask_components.py tests/application/test_components.py tests/application/test_resolved_components.py -q`
Expected: PASS.

- [ ] **Step 5: Read the generated reference by eye, once**

```bash
uv run python -c "
from research_team.application.components import component_reference
print(component_reference(only=['definition','evidence','graph','timeline','compare']))
"
```

This is the text a model reads on every authoring turn, and length is a cost paid per turn. Read it as the model will: check that each example is valid YAML for its own schema, that the `timeline` example's dates are quoted, and that no craft note has drifted into a course in assessment design. Fix anything that reads badly in `components.py` and re-run Step 4.

- [ ] **Step 6: Check the prompt's size against what it replaced**

```bash
uv run python -c "
from research_team.application.ask_components import ASK_COMPONENT_TYPES
from research_team.application.components import component_reference
print(len(component_reference(only=list(ASK_COMPONENT_TYPES))))
print(len(component_reference(only=['mcq','cloze','flashcards'])))
"
```

Record both numbers in the commit message. This is not a gate — there is no budget to fail — but the ask prompt just grew by whatever the difference is, on every ask turn, and a number in `git log` is what makes that visible to whoever next wonders where the tokens went.

- [ ] **Step 7: Find the ask prompt's own render of the reference**

```bash
grep -rn "ASK_COMPONENT_TYPES" research_team/
```

Confirm the caller renders `component_reference(only=ASK_COMPONENT_TYPES)` rather than a hardcoded list, and that nothing else enumerates the ask's component names. If a second list exists, that is the drift `only=` was built to prevent — fix it in this task and say so in the commit message.

- [ ] **Step 8: Run all four gates in full**

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
cd frontend && npm run verify
```

Then, alone:

```bash
cd frontend && npm run test:browser
```

- [ ] **Step 9: Rebuild the committed console and confirm no drift remains**

The final rebuild for the whole feature. Even though this task changes no `frontend/src` file, run it and confirm the tree is clean — a drift surviving here means an earlier task committed a stale bundle, and this is the last place to catch it before CI does.

```bash
cd frontend && npm run build
cd .. && git status --short research_team/interfaces/web/static
```
Expected: **no output**. If anything is modified, an earlier task's rebuild was skipped or its build ran against different sources; commit the rebuilt assets here and note in the message which task they belong to.

- [ ] **Step 10: Commit**

```bash
git add research_team/application/ask_components.py tests research_team/interfaces/web/static
git commit -m 'feat: offer the five resolved components to the ask agent

An ask is precisely where a reader asks about the corpus, and a resolved
component is the only thing in this registry that answers with what the
project actually holds rather than with what the model can describe. checklist
stays out for its own unchanged reason: it needs a learner identity the ask
path does not have.

Offering all five at once rather than one at a time, because the cost of a
reference that does not land is a word rather than an error -- every miss
degrades to prose by construction.

The ask prompt grew from N to M characters, paid on every ask turn. Recorded
here rather than gated: there is no budget to fail, and a number in the log is
what makes the cost visible to whoever next wonders where the tokens went.

COMPONENTS_FOR is deliberately untouched. It maps artifact types to components
for a stage writing a course file, and none of the five is an assessment item
or a practice activity -- adding them for symmetry would put two kilobytes of
corpus-widget syntax into the prompt of a stage writing an evidence spec.

The craft guidance for every by-name type says to write the entity name
exactly as the prose and the sources do, and there is a test asserting it. That
is the one failure mode of this design a model can avoid on its own: a tidy
canonical name for an entity extraction stored as it appeared resolves to
nothing, renders as a plain word, and nothing tells the author why.'
```

Replace `N` and `M` with the numbers Step 6 printed.

---

## Self-Review

Run against the spec after the plan was complete. Findings, and what was done about each.

**Spec coverage.** Every section maps to a task: §1's four render states → Task 2 (`ResolvedEntity`, `ResolvedFrame`); §2's registry changes → Task 1 (`resolved`, identity projection, honest validation) and Task 8 (`ASK_COMPONENT_TYPES`, craft guidance); §3's client contract → Task 2 (`RENDERERS` signature, `projectId` threading, `useEntityReference`, `ResolvedFrame`, the ask-turn provider test); §4's five components → Tasks 3–7, each with its registry entry, reader, renderer, tests and styles; §5's testing requirements → the gate steps, the two `*.browser.test.tsx` files, and `tests/integration/test_resolved_widget_routes.py`; §6's exclusions are excluded.

Three gaps were found and closed inline:

1. **The spec says `entity_id:` "remains accepted on every reference" but the registry validates fields one at a time.** There is no "one of these two" mechanism in `_check_fields`, so a literal reading needs new validation machinery. Task 3 states the decision instead: `entity` is required and `entity_id` optional beside it. The name is needed anyway — `ResolvedFrame` degrades to the word the author wrote.
2. **The spec's four states have no `loading`.** A renderer still has to draw something while a search is in flight, and folding it into `missing` would flash "not in this project's graph" on every cold cache. Added as a fifth union member with that reasoning on the type.
3. **`timeline` needs a repository signature change the spec mentions only in passing** ("must be widened to carry `from`/`to`/`limit`"). Task 6 makes it an options object rather than four positionals, updates the port and every existing caller, and adds `timeline-repository.test.ts` to pin the `from`/`from_` alias — which is the part that would fail silently.

**Placeholder scan.** No "TBD", no "write tests for the above", no "similar to Task N". Every test step carries real code. Five steps ask the implementer to read a specific existing file and match its idiom before writing (the citation link in Task 3, the `documents.read` range shape in Task 4, the canvas query in Task 5, `query()`'s empty-object behaviour in Task 6, the `ask-fixtures.ts` default in Task 2) — these are verification instructions against named files, not deferred decisions, and each says what to do if the file disagrees. Two browser-test bodies (Task 5's `harness()`/`waitForBox()`, Task 6's) are specified rather than written out, with the fixture, the assertion and the red-proof named; that is the one place the plan asks for construction rather than transcription, and it does so to keep the two files sharing one provider helper rather than duplicating a fixture.

**Type consistency.** Checked across tasks: `EntityReference`/`ResolvedEntity`/`matchEntities`/`readEntityReference` (Task 2) are used under exactly those names in Tasks 3, 5 and 7. `readDefinitionRef` is the re-export of `readEntityReference`, not a second parse. `GraphRef extends EntityReference` adds only `depth`. `TimelineWindow` (domain, nullable fields) and `TimelineWindowQuery` (port, optional fields) are two names on purpose — the first is what a YAML body reads as, the second is what a query string wants — and `asQuery` in Task 6 is the one conversion between them. `num()` is introduced in Task 4 and used again in Tasks 5 and 6; if Task 4 is skipped or reordered, Task 5 must add it. `queryKeys.document` is reused rather than duplicated for `evidence`. `_untouched_project` is created in Task 3 and used in Tasks 5 and 6.

**One thing left undone deliberately.** The `graph` and `compare` widgets call `useEntityReference` and then hold a `picked` id in local state, which means an ambiguity a reader resolves is forgotten when the block unmounts. Persisting it would need per-occurrence state no ask has (the same gap `BACKLOG.md` B33 records against `socratic`), so it is out of scope here and worth a backlog entry rather than a half-measure.


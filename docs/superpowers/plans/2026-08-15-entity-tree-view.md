# Entity Tree View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Tree" tab to the project page's MATERIAL region that lists the project's entities under collapsible entity-type headings, as an alternative reading of the same material the Graph tab draws.

**Architecture:** A pure fold (`groupByType`) in `domain/knowledge/`, a presentational component (`EntityTree`) that renders it with the existing `Disclosure` primitive, a subscription pane (`EntityTreePane`) modelled directly on `TimelinePane`, and four lines of wiring in `routes.ts` and `ProjectView.tsx`. No backend change, no new dependency, no new stylesheet.

**Tech Stack:** React 19, TypeScript, zustand (via `createGraphStore`), Tailwind utilities, vitest + testing-library (jsdom), vitest browser mode (Chromium) for measurements.

**Spec:** `docs/superpowers/specs/2026-08-15-entity-tree-view-design.md`

## Global Constraints

- **Four gates, and passing three is not passing.** `uv run ruff check .`, `uv run ruff format --check .`, `uv run pytest`, and `cd frontend && npm run verify`. The ruff gates run over the whole repository and are a separate CI job; a frontend-only change still has to pass them.
- **Never run two vitest processes at once.** Concurrent runs fail spuriously with a coverage temp-file error that names nothing about the real cause.
- **`border-solid` needs `border-0` before any directional width.** This build imports no Tailwind preflight, so the three sides with a style and no explicit width fall back to the browser's `medium` (~3px). A rule meant for one edge draws a box. No gate catches it.
- **Do not use `focus-visible:outline-offset-[-2px]`.** It is inert: `tokens.css`'s global `:focus-visible` is unlayered and beats any `@layer utilities` rule regardless of specificity. Use the `lay-ring-inward` class from `layout.css`.
- **New surfaces are dressed in Tailwind utilities; no stylesheet is added.** Standing policy, stated in `ProjectView.tsx`.
- **Comments explain why, not what.** State costs and trade-offs, name what a test would fail on, and say when something was measured rather than reasoned. Commit messages carry what was considered and rejected.
- **A test that would pass with the code under test removed is not a test.** Assert the data is on screen, not that rendering did not throw.
- **Pre-release: no backwards compatibility is required.** Break shapes rather than migrating.

## File Structure

| File | Responsibility |
| --- | --- |
| `frontend/src/domain/knowledge/entity-tree.ts` | **Create.** The pure fold: filter, group, sort. No React, no store. |
| `frontend/src/domain/knowledge/entity-tree.test.ts` | **Create.** The fold's contract. |
| `frontend/src/presentation/research/EntityTree.tsx` | **Create.** Presentational: groups in, three callbacks out. No fetching. |
| `frontend/src/presentation/research/EntityTree.test.tsx` | **Create.** Disclosure, rows, selection, empty states. |
| `frontend/src/presentation/research/EntityTreePane.tsx` | **Create.** Subscription: store per project, `loadAll`, frame refresh, open-set, `GraphDetail`. |
| `frontend/src/presentation/research/EntityTreePane.test.tsx` | **Create.** Load, refresh, cap notice, default openness, selection round-trip. |
| `frontend/src/presentation/routing/routes.ts` | **Modify.** `'tree'` joins `FACETS`. |
| `frontend/src/presentation/routing/routes.test.ts` | **Modify.** A `tree` row in the `cases` table. |
| `frontend/src/presentation/project/ProjectView.tsx` | **Modify.** `MaterialFacet`, `MATERIAL_TABS`, `regionOf`, the `TabPanel`. |
| `frontend/src/presentation/project/use-project-panes.ts` | **Modify.** MATERIAL's floor, re-measured. |
| `frontend/src/presentation/project/project-tracks.browser.test.tsx` | **Modify only if its own comment demands it.** The assertion does not get relaxed. |
| `frontend/scripts/check-size.mjs` | **Modify if a bucket trips.** Raise, with the measurement recorded. |

---

### Task 1: The fold

**Files:**
- Create: `frontend/src/domain/knowledge/entity-tree.ts`
- Test: `frontend/src/domain/knowledge/entity-tree.test.ts`

**Interfaces:**
- Consumes: `GraphNode` from `@domain/knowledge/graph.ts` — `{ id, name, entityType, temporal? }`.
- Produces:
  ```ts
  export interface EntityGroup {
    readonly entityType: string
    readonly entities: readonly GraphNode[]
  }
  export const groupByType: (
    nodes: readonly GraphNode[],
    filter?: string,
  ) => readonly EntityGroup[]
  ```

- [ ] **Step 1: Write the failing test**

Create `frontend/src/domain/knowledge/entity-tree.test.ts`:

```ts
import { describe, expect, it } from 'vitest'

import type { GraphNode } from './graph.ts'
import { groupByType } from './entity-tree.ts'

const node = (id: string, name: string, entityType: string): GraphNode => ({
  id,
  name,
  entityType,
})

describe('groupByType', () => {
  it('puts each entity under its own type, with the types in name order', () => {
    const groups = groupByType([
      node('1', 'Hinton', 'person'),
      node('2', 'Backprop', 'concept'),
      node('3', 'LeCun', 'person'),
    ])

    expect(groups.map((group) => group.entityType)).toEqual(['concept', 'person'])
    expect(groups[1].entities.map((entity) => entity.name)).toEqual(['Hinton', 'LeCun'])
  })

  it('sorts entities by name rather than by arrival', () => {
    const groups = groupByType([node('1', 'Zeta', 'concept'), node('2', 'Alpha', 'concept')])

    expect(groups[0].entities.map((entity) => entity.name)).toEqual(['Alpha', 'Zeta'])
  })

  /** Not a code-point sort: `Ångström` before `Zeta` is what a reader expects,
   *  and `'Å' > 'Z'` is what a naive comparison gives. Fails if `localeCompare`
   *  is replaced with `<`. */
  it('orders accented names the way a reader reads them', () => {
    const groups = groupByType([node('1', 'Zeta', 'concept'), node('2', 'Ångström', 'concept')])

    expect(groups[0].entities.map((entity) => entity.name)).toEqual(['Ångström', 'Zeta'])
  })

  it('filters on the name, case-insensitively, before grouping', () => {
    const groups = groupByType(
      [
        node('1', 'Hinton', 'person'),
        node('2', 'Backprop', 'concept'),
        node('3', 'LeCun', 'person'),
      ],
      'hint',
    )

    expect(groups).toHaveLength(1)
    expect(groups[0].entityType).toBe('person')
    expect(groups[0].entities.map((entity) => entity.name)).toEqual(['Hinton'])
  })

  /** The whole reason filtering happens before grouping: a filter that matched
   *  nothing in a type must remove that type's heading, not leave an empty one
   *  for the reader to open. Fails if the filter moves inside the groups. */
  it('leaves no empty group behind when a filter excludes a whole type', () => {
    const groups = groupByType(
      [node('1', 'Hinton', 'person'), node('2', 'Backprop', 'concept')],
      'hint',
    )

    expect(groups.map((group) => group.entityType)).toEqual(['person'])
  })

  it('is empty for no entities, and for a filter that matches none', () => {
    expect(groupByType([])).toEqual([])
    expect(groupByType([node('1', 'Hinton', 'person')], 'zzz')).toEqual([])
  })

  /** A blank or whitespace-only box is not a filter. Fails if the pane's
   *  empty-string term is passed straight through as a predicate. */
  it('treats a blank filter as no filter', () => {
    expect(groupByType([node('1', 'Hinton', 'person')], '   ')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
cd frontend && npx vitest run src/domain/knowledge/entity-tree.test.ts
```

Expected: FAIL — `Failed to resolve import "./entity-tree.ts"`.

- [ ] **Step 3: Write the fold**

Create `frontend/src/domain/knowledge/entity-tree.ts`:

```ts
/** The knowledge graph's entities, grouped for reading rather than for drawing.
 *
 * A pure fold, the same shape and for the same reason as `graph.ts` beside it:
 * the sorting and the empty-group rule are the parts with a correctness story,
 * and they are worth holding somewhere no React render can reach.
 */

import type { GraphNode } from './graph.ts'

/** One type's entities. There is no empty group: a group exists because an
 *  entity landed in it, which is what keeps a filter from leaving a screen of
 *  headings that open onto nothing. */
export interface EntityGroup {
  readonly entityType: string
  readonly entities: readonly GraphNode[]
}

/** Group entities by type, optionally narrowed to a substring of their names.
 *
 * **Filtering happens before grouping**, and that ordering is the contract:
 * done the other way, a type with no matching entity would keep its heading
 * and its count would disagree with what opening it showed.
 *
 * `localeCompare` rather than `<` in both sorts. A code-point comparison puts
 * `Ångström` after `Zeta`, which is wrong in the only sense that matters here
 * -- the list exists to be scanned by a person. The cost is a slower sort on a
 * capped node set, which is not a size where it shows.
 *
 * Ties keep input order: `Array.prototype.sort` is required to be stable, so
 * two entities with the same name stay in the order the server sent them
 * rather than being scrambled by the client.
 */
export const groupByType = (
  nodes: readonly GraphNode[],
  filter?: string,
): readonly EntityGroup[] => {
  const needle = (filter ?? '').trim().toLowerCase()
  const matching =
    needle === '' ? nodes : nodes.filter((node) => node.name.toLowerCase().includes(needle))

  const byType = new Map<string, GraphNode[]>()
  for (const node of matching) {
    const existing = byType.get(node.entityType)
    if (existing) existing.push(node)
    else byType.set(node.entityType, [node])
  }

  return [...byType.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([entityType, entities]) => ({
      entityType,
      entities: [...entities].sort((left, right) => left.name.localeCompare(right.name)),
    }))
}
```

- [ ] **Step 4: Run the test and watch it pass**

```bash
cd frontend && npx vitest run src/domain/knowledge/entity-tree.test.ts
```

Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/domain/knowledge/entity-tree.ts frontend/src/domain/knowledge/entity-tree.test.ts
git commit -m "$(cat <<'EOF'
Group a graph's entities by type, as a fold with no view attached

The first piece of the tree view: a pure function from the nodes
`loadAll` already fetches to the groups a list draws. Beside `graph.ts`
and pure for the same reason -- the two rules with a correctness story
live here rather than inside a render.

Filtering before grouping is the contract, not an implementation
detail. The other order leaves a heading whose count disagrees with
what opening it shows, and there is a test that fails on it.

`localeCompare` rather than `<`, because a code-point sort puts
`Ångström` after `Zeta` and this list exists to be scanned by a person.
The cost is a slower sort over a node set the server already caps,
which is not a size where it shows.
EOF
)"
```

---

### Task 2: The drawing

**Files:**
- Create: `frontend/src/presentation/research/EntityTree.tsx`
- Test: `frontend/src/presentation/research/EntityTree.test.tsx`

**Interfaces:**
- Consumes: `EntityGroup` from Task 1; `Disclosure` from `../common/primitives.tsx`; `colorForType`, `KIND_TOKENS` from `./entity-colors.ts`.
- Produces:
  ```ts
  export const EntityTree: (props: {
    groups: readonly EntityGroup[]
    open: ReadonlySet<string>
    selected: string | null
    onToggle: (entityType: string) => void
    onSelect: (id: string) => void
  }) => JSX.Element
  ```

Check `colorForType`'s exact signature before writing the swatch — it is `(entityType: string, palette: readonly string[]) => string`, and `KIND_TOKENS` is the palette every other caller passes. Read `GraphLegend.tsx` for the established call site rather than inventing one.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/presentation/research/EntityTree.test.tsx`:

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { EntityGroup } from '@domain/knowledge/entity-tree.ts'

import { EntityTree } from './EntityTree.tsx'

const groups: readonly EntityGroup[] = [
  {
    entityType: 'concept',
    entities: [
      { id: 'c1', name: 'Backprop', entityType: 'concept' },
      { id: 'c2', name: 'Gradient descent', entityType: 'concept' },
    ],
  },
  { entityType: 'person', entities: [{ id: 'p1', name: 'Hinton', entityType: 'person' }] },
]

const noop = () => {}

describe('EntityTree', () => {
  it('names every type, with how many entities are under it', () => {
    render(
      <EntityTree
        groups={groups}
        open={new Set()}
        selected={null}
        onToggle={noop}
        onSelect={noop}
      />,
    )

    expect(screen.getByRole('button', { name: /concept/ })).toHaveTextContent('2')
    expect(screen.getByRole('button', { name: /person/ })).toHaveTextContent('1')
  })

  /** The assertion is the entity's name, not that the component rendered: a
   *  test asserting only the headings would pass with every row dropped. */
  it('shows an open group’s entities and hides a closed one’s', () => {
    render(
      <EntityTree
        groups={groups}
        open={new Set(['concept'])}
        selected={null}
        onToggle={noop}
        onSelect={noop}
      />,
    )

    expect(screen.getByText('Backprop')).toBeInTheDocument()
    expect(screen.getByText('Gradient descent')).toBeInTheDocument()
    expect(screen.queryByText('Hinton')).not.toBeInTheDocument()
  })

  it('says which groups are open, for a screen reader as well as a caret', () => {
    render(
      <EntityTree
        groups={groups}
        open={new Set(['concept'])}
        selected={null}
        onToggle={noop}
        onSelect={noop}
      />,
    )

    expect(screen.getByRole('button', { name: /concept/ })).toHaveAttribute(
      'aria-expanded',
      'true',
    )
    expect(screen.getByRole('button', { name: /person/ })).toHaveAttribute(
      'aria-expanded',
      'false',
    )
  })

  it('asks for a group to be toggled rather than toggling it itself', async () => {
    const onToggle = vi.fn()
    render(
      <EntityTree
        groups={groups}
        open={new Set()}
        selected={null}
        onToggle={onToggle}
        onSelect={noop}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /person/ }))

    expect(onToggle).toHaveBeenCalledWith('person')
  })

  it('selects by id, not by name', async () => {
    const onSelect = vi.fn()
    render(
      <EntityTree
        groups={groups}
        open={new Set(['person'])}
        selected={null}
        onToggle={noop}
        onSelect={onSelect}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Hinton' }))

    expect(onSelect).toHaveBeenCalledWith('p1')
  })

  /** `aria-current` rather than a colour alone: which row is selected is
   *  information, and a border is not available to a screen reader. */
  it('marks the selected row', () => {
    render(
      <EntityTree
        groups={groups}
        open={new Set(['person'])}
        selected="p1"
        onToggle={noop}
        onSelect={noop}
      />,
    )

    expect(screen.getByRole('button', { name: 'Hinton' })).toHaveAttribute('aria-current', 'true')
  })
})
```

- [ ] **Step 2: Run the test and watch it fail**

```bash
cd frontend && npx vitest run src/presentation/research/EntityTree.test.tsx
```

Expected: FAIL — cannot resolve `./EntityTree.tsx`.

- [ ] **Step 3: Write the component**

Create `frontend/src/presentation/research/EntityTree.tsx`:

```tsx
import type { EntityGroup } from '@domain/knowledge/entity-tree.ts'

import { Disclosure } from '../common/primitives.tsx'
import { colorForType, KIND_TOKENS } from './entity-colors.ts'

/** An entity row: the same full-width bare button the graph's edge rows and
 *  the search results are, and deliberately the same vocabulary rather than a
 *  third one -- a left gutter that lights up on hover and focus is how this
 *  console says "this one" everywhere else.
 *
 * `border-0` comes first and is not optional: `border-solid` sets the style on
 * all four sides, and with only `border-l-2` giving a width the other three
 * would fall back to the browser's `medium` (~3px), because this build imports
 * no preflight. A rule meant for one edge would draw a box, and no gate
 * catches it.
 *
 * `lay-ring-inward` rather than the `focus-visible:outline-offset-[-2px]`
 * utility, which is inert: `tokens.css`'s global `:focus-visible` is unlayered
 * and beats anything in `@layer utilities` whatever its specificity. The class
 * is in `layout.css` and carries that measurement.
 *
 * `[font:inherit]` because the `font` shorthand has no utility and a `<button>`
 * that does not inherit it renders in the user agent's 13.33px sans. */
const ROW = [
  'flex w-full cursor-pointer items-baseline justify-between gap-2',
  'border-0 border-l-2 border-solid border-l-transparent rounded-md',
  'bg-transparent px-[8px] py-[5px] text-left text-sm text-inherit [font:inherit]',
  'hover:bg-bg-hover hover:border-l-accent',
  'focus-visible:bg-bg-hover focus-visible:border-l-accent',
  'aria-[current=true]:border-l-accent aria-[current=true]:bg-bg-hover',
  'lay-ring-inward',
].join(' ')

/** The project's entities under their types, foldable.
 *
 * Presentational: it holds no open-set of its own and fetches nothing, so
 * every state it can be in is one render away in a test. The pane above it
 * owns openness, because a fold that reset itself whenever extraction landed
 * would be unusable during the one activity that changes this list.
 *
 * **Not `role="tree"`.** ARIA's tree pattern obliges arrow-key navigation,
 * typeahead and a roving tabindex; claiming the role without them tells a
 * screen reader the keyboard does something it does not. Nested lists with
 * disclosure buttons promise only what they deliver.
 *
 * The swatch is `colorForType` against the same `KIND_TOKENS` palette the
 * canvas and the legend use, so a reader who has learnt the graph's colours is
 * not learning a second scheme for the same types.
 */
export const EntityTree = ({
  groups,
  open,
  selected,
  onToggle,
  onSelect,
}: {
  groups: readonly EntityGroup[]
  open: ReadonlySet<string>
  selected: string | null
  onToggle: (entityType: string) => void
  onSelect: (id: string) => void
}) => (
  <ul className="m-0 flex list-none flex-col gap-[2px] p-[4px]">
    {groups.map((group) => (
      <li key={group.entityType}>
        <Disclosure
          open={open.has(group.entityType)}
          onToggle={() => onToggle(group.entityType)}
          label={
            <>
              <span
                aria-hidden="true"
                className="size-[8px] shrink-0 rounded-full"
                style={{ background: `var(${colorForType(group.entityType, KIND_TOKENS)})` }}
              />
              <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                {group.entityType}
              </span>
              {/* The count is what makes a closed group informative. Without
                  it a collapsed tree says only which types exist, which the
                  legend already says. */}
              <span className="ml-auto shrink-0 text-fg-dim">{group.entities.length}</span>
            </>
          }
        >
          <ul className="m-0 flex list-none flex-col gap-[1px] p-0 pl-[14px]">
            {group.entities.map((entity) => (
              <li key={entity.id}>
                <button
                  type="button"
                  className={ROW}
                  aria-current={entity.id === selected}
                  onClick={() => onSelect(entity.id)}
                >
                  <span className="min-w-0 overflow-hidden text-ellipsis whitespace-nowrap">
                    {entity.name}
                  </span>
                  {entity.temporal ? (
                    <span className="shrink-0 font-mono text-xs text-fg-dim">
                      {entity.temporal}
                    </span>
                  ) : null}
                </button>
              </li>
            ))}
          </ul>
        </Disclosure>
      </li>
    ))}
  </ul>
)
```

If `aria-current={entity.id === selected}` renders `aria-current="false"` in a way the test's `toHaveAttribute('aria-current', 'true')` cannot see, keep the boolean — React renders `aria-*` booleans as the strings `"true"`/`"false"`, which is exactly what the test asserts. Do not switch to `aria-current="page"`; this is not navigation.

- [ ] **Step 4: Run the test and watch it pass**

```bash
cd frontend && npx vitest run src/presentation/research/EntityTree.test.tsx
```

Expected: PASS, 6 tests.

- [ ] **Step 5: Check the swatch is not a lie**

`colorForType` returns a token *name* (e.g. `--k-session`), not a colour. Confirm against `GraphLegend.tsx` whether callers wrap it in `var(...)` themselves or whether the function already does. Fix the `style` above to match the established call site; a swatch painted `background: --k-session` is invalid CSS and renders transparent, and jsdom will not tell you.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/presentation/research/EntityTree.tsx frontend/src/presentation/research/EntityTree.test.tsx
git commit -m "$(cat <<'EOF'
Draw the entity groups, folding, with nothing of their own to remember

Presentational: no open-set, no fetch, so every state is one render
away in a test. Openness belongs to the pane above, because a fold that
reset itself when extraction landed would break during the one activity
that changes this list.

`Disclosure` from `primitives.tsx` rather than a second one. It is
already a button over an `aria-controls` region, chosen over `<details>`
precisely so the open state survives a re-render driven from elsewhere
-- which is the property this pane needs.

Not `role="tree"`: the pattern obliges arrow keys, typeahead and a
roving tabindex, and a role without them tells a screen reader the
keyboard does something it does not. Rejected `@radix-ui/react-accordion`
for the same work, which would put a package in the `ui` bucket to
replace a primitive already here.

The swatch reuses `colorForType` against `KIND_TOKENS`, so the types
carry the colours the canvas and legend already taught.
EOF
)"
```

---

### Task 3: The pane

**Files:**
- Create: `frontend/src/presentation/research/EntityTreePane.tsx`
- Test: `frontend/src/presentation/research/EntityTreePane.test.tsx`

**Interfaces:**
- Consumes: `groupByType` (Task 1), `EntityTree` (Task 2), `createGraphStore` from `@application/research/graph-store.ts`, `useContainer`, `useFrameRefresh`, `GraphDetail`, `projectHref`, `EmptyState`/`Loading`.
- Produces:
  ```ts
  export const EntityTreePane: (props: {
    projectId: ProjectId
    entity: string | null
    onEntity: (id: string | null) => void
  }) => JSX.Element
  ```
  and, exported for testing without a fake repository, `EntityTreeBrowser` taking `{ projectId, groups, open, selected, loading, error, partial, filtered, onToggle, onSelect, onClose, view }`.

**Read `TimelinePane.tsx` first.** This pane is structurally that file: same store-per-project `useMemo`, same `loadAll`-on-mount effect, same `useFrameRefresh` predicate, same `GraphDetail` arrangement with `showInGraphHref` and no `onRemove`. Copy the shape; do not invent a second one.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/presentation/research/EntityTreePane.test.tsx`. Model the container/fake-repository setup on `GraphPane.test.tsx` — read it and reuse its fake `GraphRepository` shape rather than writing a new one.

```tsx
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { EntityGroup } from '@domain/knowledge/entity-tree.ts'
import { emptyGraph } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { EntityTreeBrowser } from './EntityTreePane.tsx'

const projectId = ProjectId('11111111-1111-1111-1111-111111111111')

const groups: readonly EntityGroup[] = [
  { entityType: 'person', entities: [{ id: 'p1', name: 'Hinton', entityType: 'person' }] },
]

const props = {
  projectId,
  view: emptyGraph,
  groups,
  open: new Set(['person']),
  selected: null,
  loading: false,
  error: null as string | null,
  partial: false,
  filtered: false,
  onToggle: () => {},
  onSelect: () => {},
  onClose: () => {},
}

describe('EntityTreeBrowser', () => {
  it('lists the entities it was given', () => {
    render(<EntityTreeBrowser {...props} />)

    expect(screen.getByText('Hinton')).toBeInTheDocument()
  })

  /** The three empty states must stay three. A fetch that failed saying "this
   *  project has no entities" is the defect `GraphPane`'s own empty state was
   *  written to correct. */
  it('says the entities could not be read, rather than that there are none', () => {
    render(<EntityTreeBrowser {...props} groups={[]} error="network down" />)

    expect(screen.getByText(/could not be read/i)).toBeInTheDocument()
    expect(screen.queryByText(/nothing has been extracted/i)).not.toBeInTheDocument()
  })

  it('blames the filter when a filter is what emptied the list', () => {
    render(<EntityTreeBrowser {...props} groups={[]} filtered />)

    expect(screen.getByText(/nothing matched/i)).toBeInTheDocument()
    expect(screen.queryByText(/nothing has been extracted/i)).not.toBeInTheDocument()
  })

  it('says the project is empty only when it is', () => {
    render(<EntityTreeBrowser {...props} groups={[]} />)

    expect(screen.getByText(/nothing has been extracted/i)).toBeInTheDocument()
  })

  /** A truncated list reads as an inventory and is not one. Fails if the
   *  notice is dropped, which looks identical to a complete graph on screen. */
  it('admits when the server capped what it sent', () => {
    render(<EntityTreeBrowser {...props} partial />)

    expect(screen.getByText(/part of a larger graph/i)).toBeInTheDocument()
  })

  it('does not claim a cap that did not happen', () => {
    render(<EntityTreeBrowser {...props} />)

    expect(screen.queryByText(/part of a larger graph/i)).not.toBeInTheDocument()
  })
})
```

Then add, in the same file, a `describe('EntityTreePane')` block that mounts the real pane against the fake container from `GraphPane.test.tsx` and asserts:

```tsx
  it('draws the project’s entities without being asked to search first', async () => {
    // fake graphs.whole() resolves one `person` entity named `Hinton`
    // mount <EntityTreePane projectId={projectId} entity={null} onEntity={vi.fn()} />
    expect(await screen.findByRole('button', { name: /person/ })).toBeInTheDocument()
  })

  it('opens every group on a small graph, so the tab enumerates something', async () => {
    // same fixture: with 1 entity, `person` is open and `Hinton` is on screen
    expect(await screen.findByText('Hinton')).toBeInTheDocument()
  })
```

Use whatever method name `GraphRepository` actually exposes for the whole-graph read — read `frontend/src/application/ports/repositories.ts` and `graph-store.ts`'s `loadAll` to get it exactly; do not guess `whole()`.

- [ ] **Step 2: Run the test and watch it fail**

```bash
cd frontend && npx vitest run src/presentation/research/EntityTreePane.test.tsx
```

Expected: FAIL — cannot resolve `./EntityTreePane.tsx`.

- [ ] **Step 3: Write the pane**

Create `frontend/src/presentation/research/EntityTreePane.tsx`. The required behaviour, each point of which a test above pins:

1. `const store = useMemo(() => createGraphStore({ graphs, projectId }), [graphs, projectId])` — per project, for the reason `GraphPane` gives: a shared store shows one project's entities on another's page.
2. `useEffect(() => { void store.getState().loadAll() }, [store])`.
3. `useFrameRefresh(true, (frame) => frame.kind === 'graph' && frame.projectId === projectId, () => void store.getState().loadAll())`.
4. A `term` in local state, and `const groups = useMemo(() => groupByType(view.nodes, term), [view.nodes, term])`.
5. An open-set in local state. Default openness is a rule:

```tsx
/** Small graphs open; big ones do not.
 *
 * The tab exists to enumerate, and a screen of closed headings enumerates
 * nothing -- but every group open on a nine-hundred-entity graph is the
 * canvas's hairball set in a different font. 200 is **chosen, not measured**:
 * it is roughly the point at which the list stops being one scroll.
 *
 * Applied once per project rather than on every load, and that is the part
 * with a defect behind it: `loadAll` runs again on every `graph` frame, so
 * recomputing here would silently undo a reader's collapses during the one
 * activity that makes this list change.
 */
const OPEN_ALL_BELOW = 200
```

Track it with a ref holding the project the default was applied for, so a project change re-applies it and a refresh does not.

6. Selection is the route's: `entity` in, `onEntity` out. No local copy.
7. Render `EntityTreeBrowser` with `filtered={term.trim() !== ''}` and `partial` from the store.
8. `EntityTreeBrowser` renders, in order: a filter `<input type="search" aria-label="Filter entities">`; the cap notice when `partial`, using `GraphPane`'s `NOTICE` rule verbatim and the same sentence; the three empty states; `<EntityTree …/>` inside a `min-h-0 flex-1 overflow-auto` scroller; and `GraphDetail` when something is selected, with `projectId`, `view`, `showInGraphHref={projectHref(projectId, { facet: 'entity', id: selected })}`, no `onRemove`, and `onClose`.

The outer element is `flex min-h-0 flex-1` with the tree column and the detail panel beside it, exactly as `TimelineBrowser` arranges the same two.

- [ ] **Step 4: Run the test and watch it pass**

```bash
cd frontend && npx vitest run src/presentation/research/EntityTreePane.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/presentation/research/EntityTreePane.tsx frontend/src/presentation/research/EntityTreePane.test.tsx
git commit -m "$(cat <<'EOF'
Subscribe the tree to the graph the project already has

Structurally `TimelinePane`, deliberately: a store per project, a load
on mount, a reload on every `graph` frame, and `GraphDetail` reached
with `showInGraphHref` and no `onRemove` -- there is no drawing here to
prune, so offering Remove would be a button that either does nothing or
silently changes another tab.

Openness lives here rather than in the drawing, and is applied once per
project rather than per load. `loadAll` runs again on every graph frame;
recomputing the default there would undo a reader's collapses during
the one activity that makes this list change.

Every group opens below 200 entities and none above. The number is
chosen, not measured, and says so in the comment -- a screen of closed
headings enumerates nothing, and nine hundred open rows is the canvas's
hairball in a different font.

The cap notice is `GraphPane`'s, word for word. A truncated tree looks
exactly like a complete one and reads as an inventory, which makes the
silence worse here than on the canvas.
EOF
)"
```

---

### Task 4: Wiring

**Files:**
- Modify: `frontend/src/presentation/routing/routes.ts`
- Modify: `frontend/src/presentation/routing/routes.test.ts`
- Modify: `frontend/src/presentation/project/ProjectView.tsx`

**Interfaces:**
- Consumes: `EntityTreePane` (Task 3).
- Produces: the facet string `'tree'` in `FACETS`, and `MaterialFacet` gaining `'tree'`.

- [ ] **Step 1: Add the facet and watch the type checker do the work**

In `routes.ts`, add `'tree'` to `FACETS`, directly after `'timeline'`, with a comment saying it is the graph's third reading — the same material as a list rather than a drawing.

```bash
cd frontend && npx tsc --noEmit -p tsconfig.json
```

Expected: FAIL in `ProjectView.tsx` — `regionOf` is not total over `Facet` any more. That failure is the design working; do not silence it with a `default` arm.

- [ ] **Step 2: Add the `routes.test.ts` case**

`routes.test.ts:129` asserts its `cases` table covers `FACETS` exactly. Add a `tree` row alongside the existing `entity`/`timeline` rows, following whatever shape those use.

```bash
cd frontend && npx vitest run src/presentation/routing/routes.test.ts
```

Expected: PASS.

- [ ] **Step 3: Wire the tab**

In `ProjectView.tsx`:
- add `'tree'` to `MaterialFacet`;
- add `{ id: 'tree', label: 'Tree' }` to `MATERIAL_TABS` **directly after `entity`**, with a comment: it is the graph's material read as a list, so it sits beside the graph, and Timeline stays last for the bundle reason already recorded there;
- add `case 'tree':` to `regionOf`'s `material` arm;
- add the panel, mirroring `entity`'s exactly:

```tsx
          <TabPanel value="tree" className="flex min-h-0 flex-1 flex-col">
            <EntityTreePane
              projectId={projectId}
              entity={selection?.facet === 'tree' ? (selection.id ?? null) : null}
              onEntity={(entity) => select({ facet: 'tree', id: entity })}
            />
          </TabPanel>
```

- [ ] **Step 4: Run the project view's tests**

```bash
cd frontend && npx vitest run src/presentation/project src/presentation/routing
```

Expected: PASS, except possibly a test asserting the number of tabs — if one exists, update its expected count; that is the assertion doing its job.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/presentation/routing/routes.ts frontend/src/presentation/routing/routes.test.ts frontend/src/presentation/project/ProjectView.tsx
git commit -m "$(cat <<'EOF'
Give the tree a tab and a place in the hash grammar

`tree` joins `FACETS` as a plain facet, so `Selection` and `projectHref`
need no change -- the grammar is uniform by construction, and
`routes.test.ts` asserts its own coverage against `FACETS`, which is why
a case row arrives in the same commit.

`regionOf` refused to compile until `tree` was mapped, which is what
that switch's totality is for and the reason it has no `default` arm.

The tab sits directly after Graph rather than at the end: the list is
the graph's own material read a second way, so the two belong adjacent.
Timeline stays last, and the default stays Artifacts -- both for the
bundle reason already recorded above `MATERIAL_TABS`, which this change
does not disturb, since nothing in the tree is lazy and nothing in it
pulls a canvas.
EOF
)"
```

---

### Task 5: The floor, the budget, and the gates

**Files:**
- Modify: `frontend/src/presentation/project/use-project-panes.ts`
- Modify (only if its own comment demands it): `frontend/src/presentation/project/project-tracks.browser.test.tsx`
- Modify (only if a bucket trips): `frontend/scripts/check-size.mjs`

- [ ] **Step 1: Run the browser suite and watch the floor fail**

```bash
cd frontend && npm run test:browser
```

Expected: FAIL in `project-tracks.browser.test.tsx` — the MATERIAL region's tab strip now overflows at 422px, because a seventh tab was added. This is the gate working.

If it passes, stop and say so rather than moving on: the file's own docstring says the strip neither wraps nor scrolls and that the floor moved the last time a tab arrived, so a green result means either the strip changed or the test stopped measuring. Both are worth knowing before anything else is edited.

- [ ] **Step 2: Re-measure, do not guess**

Read the docstring at the top of `project-tracks.browser.test.tsx` — it defines a floor mechanically (an element whose `scrollWidth` exceeds its `clientWidth` with no scroller and no ellipsis) and records the method used for the existing three numbers.

Take the measurement the same way: narrow the viewport until the tab strip overflows, find the narrowest width at which it does not, and set MATERIAL's floor a pixel or two above it, matching the slack the other rows carry.

**Do not** relax the assertion, exclude the tab strip from the check, or pick a round number that looks plausible. The existing table records 422 as measured on 2026-08-14 after a sixth tab; the new row records the same for the seventh.

- [ ] **Step 3: Write the number down with its reason**

In `use-project-panes.ts`, update MATERIAL's `min` and add a row to the table in the docstring, in the established style: the measured-clean width, what set it, and the date. Add a sentence naming the Tree tab as what moved it — the file already has a paragraph doing exactly this for the Timeline tab, and it is the paragraph that made this failure predictable.

- [ ] **Step 4: Confirm the browser suite is green**

```bash
cd frontend && npm run test:browser
```

Expected: PASS. Run it alone — never concurrently with another vitest process.

- [ ] **Step 5: Run the frontend gate**

```bash
cd frontend && npm run verify
```

If the bundle check trips, raise the bucket it names in `scripts/check-size.mjs` — do not shave the feature. Record the measured size and what the raise bought, in the style of the notes already in that file. The owner's standing instruction is that exploration outranks bundle size at this stage, and this feature was authorised with that cost accepted.

- [ ] **Step 6: Run the other three gates**

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

All three, even though no Python changed: they run over the whole repository and are a separate CI job. This is the step that gets skipped and then fails in CI.

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "$(cat <<'EOF'
Re-measure MATERIAL's floor for the tab it just grew

The seventh tab widened a strip that neither wraps nor scrolls, so the
region's floor moved with it -- the same failure the sixth tab caused,
predicted in the same docstring, and caught by the same browser test.
Measured in Chromium the way that file defines a floor, not reasoned:
the number is the narrowest width at which the strip stops painting past
the pane's edge, plus the pixel of slack the other two rows carry.

The assertion was not relaxed and the strip was not excluded from the
check. Either would have turned the one test that catches this into a
test that cannot.
EOF
)"
```

---

### Task 6: Documentation and the branch

- [ ] **Step 1: Check whether `README.md` describes the project page's tabs**

```bash
grep -n "Timeline\|Graph tab\|Documents" README.md
```

If the tabs are enumerated there, add Tree in the same place and the same voice. If they are not, change nothing — this repository's README is for people using the project, and a tab list it never had is not owed one now.

- [ ] **Step 2: Check `BACKLOG.md` for anything this closes or opens**

Two things are deliberately deferred and are worth filing if no entry covers them: virtualizing the tree if the node cap is ever raised, and the ARIA tree pattern (arrow keys, typeahead, roving tabindex) if a reader ever wants to drive this from the keyboard alone. File them with enough detail to pick up, in the style of the entries already there.

- [ ] **Step 3: Final full-suite run, all four gates, in one pass**

```bash
uv run ruff check . && uv run ruff format --check . && uv run pytest
cd frontend && npm run verify && npm run test:browser
```

Expected: all green. If a frontend test fails, re-run it alone before investigating — and a failure under load is not evidence until it reproduces alone, twice.

- [ ] **Step 4: Push and open the PR**

```bash
git push -u origin worktree-entity-definitions
gh pr create --title "Entities as a tree, beside the graph" --body "$(cat <<'EOF'
A seventh MATERIAL tab listing the project's entities under collapsible
entity-type headings — the same material the Graph tab draws, read as an
inventory rather than as a drawing.

The graph answers "what is this connected to" well and "what is in this
project" badly: a force simulation of nine hundred nodes is a hairball,
and enumerating it means reading dots. This is the third reading of the
same material, after the timeline, and it follows that precedent exactly
— its own facet, its own tab, no backend change, no new data.

**Design:** `docs/superpowers/specs/2026-08-15-entity-tree-view-design.md`
**Plan:** `docs/superpowers/plans/2026-08-15-entity-tree-view.md`

## What is here

- A pure fold grouping the graph's nodes by type, filtering before
  grouping so a filter never leaves an empty heading behind.
- A presentational tree over the existing `Disclosure` primitive. Not
  `role="tree"`: the ARIA pattern obliges arrow keys and a roving
  tabindex, and the role without them lies to a screen reader.
- A pane modelled on `TimelinePane` — store per project, reload on every
  `graph` frame, `GraphDetail` with `showInGraphHref` and no Remove.
- The facet, the tab, and the route case.

## Costs, taken deliberately

- **MATERIAL's track floor moved**, because the tab strip neither wraps
  nor scrolls. Re-measured in Chromium the way `project-tracks.browser.test.tsx`
  defines a floor; the assertion was not relaxed.
- **The bundle budget moved** rather than the feature shrinking, on the
  owner's standing instruction that exploration outranks bundle size at
  this stage.

## Deliberately left undone

Virtualization (the server's node cap bounds the row count), nesting by
relationship (type is a partition; `contains` is not), and any editing.
EOF
)"
```

---

## Self-Review

**Spec coverage.** Fold → Task 1. Drawing → Task 2. Pane, default openness, cap notice, three empty states → Task 3. Routing and tab wiring → Task 4. Track floor and bundle budget → Task 5. Testing strategy → distributed across 1–3, with the one browser measurement in Task 5. Docs and out-of-scope items → Task 6.

One spec claim is intentionally softened here: the spec proposed extending `graph-dressing.browser.test.tsx` for the row's inward ring. Task 5 does not require it, because `ROW` is copied verbatim from `GraphDetail`'s already-measured constant — a second measurement of the same string would assert the copy, not the geometry. If the executor changes any part of `ROW`, the browser assertion becomes required and belongs in that file.

**Placeholders.** None. Every code step carries the code; the two places that say "read the established call site first" (`colorForType`'s wrapping, `GraphRepository`'s whole-graph method name) are checks against real files, not deferred decisions — and both are named exactly.

**Type consistency.** `EntityGroup`/`groupByType` (Task 1) are consumed under those names in Tasks 2 and 3. `EntityTree`'s five props match Task 3's call. `EntityTreeBrowser`'s prop list in Task 3's interface block matches its test's `props` object.

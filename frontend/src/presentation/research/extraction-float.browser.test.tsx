import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { commands } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it, vi } from 'vitest'
import type { ReactNode } from 'react'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { UsagesRepository } from '@application/ports/repositories.ts'
import type { Extraction } from '@domain/knowledge/extraction.ts'
import type { GraphNode, GraphView } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { ExtractionView } from './ExtractionPane.tsx'
import { GraphBrowser } from './GraphPane.tsx'

// `commands` is typed through `BrowserCommands`, an interface with no members
// of its own -- every project's custom commands widen it by augmentation, and
// without this the call below is an index into an empty interface and lints
// as an unsafe call on an unresolvable type. `vite.config.ts` is where the
// command itself is implemented; this is only its shape.
declare module 'vitest/internal/browser' {
  interface BrowserCommands {
    setReducedMotion: (reduced: boolean) => Promise<void>
  }
}

/** The three measurements the extraction float's move onto the graph canvas
 *  needs and no jsdom test can make: whether the float clears the search bar
 *  it sits above, whether it clears the detail column that appears whenever
 *  an entity is selected, and whether the stage in flight actually computes a
 *  different colour from its neighbours.
 *
 * jsdom lays nothing out and applies no stylesheet, so `getBoundingClientRect`
 * returns a zero rect on every element and `getComputedStyle` returns only
 * what an inline style said. A float that overlaps the search bar and one
 * that clears it look identical there, and so do a `.extraction-seg-now`
 * whose colour rule fired and one whose colour rule was silently orphaned by
 * a class-name typo -- which is the exact shape this repository has already
 * shipped once (`shell-reached-dressing.browser.test.tsx`'s docstring records
 * the Tooltip/RadioGroup instance).
 */

// `GraphCanvas` is `React.lazy` over `react-force-graph-2d`; mounting the real
// canvas would make every case here wait on a d3 tick for geometry none of
// them read off it.
vi.mock('./GraphCanvas.tsx', () => ({
  GraphCanvas: () => <div data-fake-canvas className="absolute inset-0" />,
}))

const node = (id: string): GraphNode => ({ id, name: `Entity ${id}`, entityType: 'Person' })

const view: GraphView = {
  nodes: [node('e1'), node('e2')],
  links: [{ source: 'e1', target: 'e2', relationshipType: 'advised' }],
  expanded: new Set(['e1']),
}

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

// `GraphDetail` reads usages through a query hook; this only has to resolve
// without throwing, since nothing here asserts on what it returns.
const usages: UsagesRepository = { usages: vi.fn().mockResolvedValue([]) }
const container = { usages } as unknown as AppContainer
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })

/** A run mid-flight, with more than one stage reached -- `others.length` in
 *  the colour test depends on there being a neighbour to compare against, and
 *  a run one stage in has none. */
const running: Extraction = {
  sourceId: 'syllabus.pdf',
  stage: 'consolidating',
  stages: [
    { stage: 'storing', detail: 'stored syllabus.pdf' },
    { stage: 'extracting', detail: 'chunk 24 of 24' },
    { stage: 'consolidating', detail: 'batch 2 of 3' },
  ],
  entities: 31,
  relationships: 12,
  domain: 'education',
  domainConfidence: 0.82,
  index: 2,
  total: 3,
  modelCalls: 24,
  merges: [],
  failed: false,
}

/** Everything `GraphBrowser` needs from its caller, per its own docstring --
 *  it takes every fact as a prop precisely so a test can render it against a
 *  partial container rather than a live store. */
const props = {
  projectId: PROJECT,
  view,
  results: [],
  knownTypes: ['Person'],
  minDegree: 0,
  onMinDegree: () => {},
  truncated: false,
  searching: false,
  error: null,
  partial: false,
  edgesPartial: false,
  loading: false,
  entity: null as string | null,
  term: '',
  entityType: '',
  onTerm: () => {},
  onEntityType: () => {},
  onEntity: () => {},
  onPick: () => {},
  onReset: () => {},
  onRemove: () => {},
  graphUrl: () => '/api/projects/p/export/graph',
}

/** Boxed to a real size, the way `graph-dressing.browser.test.tsx` does: the
 *  stage is `flex-1 min-h-0`, and an unsized parent would make every float
 *  measure as a zero rect that satisfies any containment assertion for free. */
const Mounted = (extra: Partial<typeof props> & { extracting: boolean; extraction: ReactNode }) => (
  <QueryClientProvider client={queryClient}>
    <ContainerProvider container={container}>
      <div style={{ width: '900px', height: '420px', display: 'flex' }}>
        <GraphBrowser {...props} {...extra} />
      </div>
    </ContainerProvider>
  </QueryClientProvider>
)

it('the extraction float clears the search bar', async () => {
  const screen = await render(
    <Mounted extracting extraction={<ExtractionView current={running} last={null} />} />,
  )

  const float = screen.container.querySelector('.extraction')!.getBoundingClientRect()
  const search = screen.getByRole('searchbox').element().getBoundingClientRect()

  // The float is the first row of the same `flex-col` column the search bar
  // sits in below it, so this should hold by construction -- and "by
  // construction" is exactly the claim jsdom cannot check, since it applies no
  // stylesheet and would report both boxes at 0x0 regardless of order.
  expect(float.bottom).toBeLessThanOrEqual(search.top)
})

it('the extraction float clears the detail column', async () => {
  const screen = await render(
    <Mounted
      entity="e1"
      extracting
      extraction={<ExtractionView current={running} last={null} />}
    />,
  )

  const float = screen.container.querySelector('.extraction')!.getBoundingClientRect()
  // `GraphDetail`'s outer `<aside>` carries an `aria-label` built from the
  // selected node's name (`About ${node.name}`) rather than a class from
  // `layout.css` -- the brief's own selector, `[class*="inset-y-3"]`, is a
  // Tailwind utility string that breaks the moment that panel's spacing is
  // retuned, which would be a false failure in a suite whose only job is true
  // ones. The accessible name is the stable handle: it is asserted on
  // elsewhere in this tree (`GraphDetail.test.tsx`) precisely because it does
  // not move when the class list does.
  const detail = screen
    .getByRole('complementary', { name: 'About Entity e1' })
    .element()
    .getBoundingClientRect()

  expect(float.right).toBeLessThanOrEqual(detail.left)
})

it('the stage in flight draws in a different colour', async () => {
  await render(<ExtractionView current={running} last={null} />)

  const segments = [...document.querySelectorAll('.extraction-seg')]
  const now = document.querySelector('.extraction-seg-now')!
  const others = segments.filter((seg) => seg !== now)

  // The precondition this test depends on: a run one stage in has no
  // neighbour, and the loop below would vacuously pass over an empty list.
  expect(others.length).toBeGreaterThan(0)
  for (const other of others) {
    expect(getComputedStyle(now).color).not.toBe(getComputedStyle(other).color)
  }
})

it('suppresses both extraction animations under prefers-reduced-motion', async () => {
  // Vitest's `page` proxy forwards no `emulateMedia` -- `a11y.browser.test.tsx`
  // already records that gap ("the sweep's browser reports no such
  // preference"). The custom command in `vite.config.ts` reaches the real
  // Playwright `Page` the provider hands a command's context, which is the
  // only channel between this file and that API.
  await commands.setReducedMotion(true)
  try {
    await render(<ExtractionView current={running} last={null} />)

    const dot = document.querySelector('.extraction-dot')!
    const now = document.querySelector('.extraction-seg-now')!

    // `course.css`'s `@media (prefers-reduced-motion: reduce)` block sets
    // `animation: none` on both selectors; asserted as the computed
    // `animationName` rather than reasoned from the source, for the same
    // reason the colour test measures rather than reads the stylesheet: a
    // rule that never matched the running element would look identical to one
    // that fired, right up until this line.
    expect(getComputedStyle(dot).animationName).toBe('none')
    expect(getComputedStyle(now).animationName).toBe('none')
  } finally {
    // Global to the browser session, the way the viewport is
    // (`src/test/browser-viewport.ts` records the same shape for width) --
    // left set, it would leave every later file in the run reduced-motion
    // without a line anywhere saying so.
    await commands.setReducedMotion(false)
  }
})

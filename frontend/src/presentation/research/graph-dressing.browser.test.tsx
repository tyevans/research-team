import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from 'vitest-browser-react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { UsagesRepository } from '@application/ports/repositories.ts'
import type { GraphNode, GraphView } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { GraphBrowser } from './GraphPane.tsx'

/** The three things the graph's rewrite off `research.css` moved into utilities
 *  that no jsdom test can judge: two focus rings inside two scrollers, the
 *  legend's single-side border, and the stacking of the three panels that float
 *  over the canvas.
 *
 * jsdom lays nothing out and applies no stylesheet, so every rect here would be
 * `0x0`, every `borderTopWidth` the initial value whatever the class attribute
 * says, and `z-index` `auto` on all three floats — which is exactly the reading
 * a broken rewrite would produce. That is why this file exists rather than four
 * more cases in `GraphPane.test.tsx`.
 *
 * **The two ring cases were proved red**, against the
 * `focus-visible:outline-offset-[-2px]` utility they were first written with:
 * `outlineOffset` measured `1px`, because `tokens.css`'s global
 * `:focus-visible` is unlayered and beats `@layer utilities`. `lay-ring-inward`
 * is the fix and `layout.css` carries the argument. Note which assertion did
 * the work: 4px of scroller padding against a 3px outward reach means the
 * *clip* assertions pass by 1px even when the ring is wrong, so
 * `expect(ring.offset).toBe(-2)` is the load-bearing one and the clip
 * assertions are what make it mean something.
 *
 * **The other two were not proved red, and here is what would make each red**,
 * which is the substitute this repository accepts when the state being
 * reproduced no longer exists in the tree:
 * - the legend border: dropping `border-0` from `NOTE` in `GraphLegend.tsx`,
 *   which takes the three unwanted sides from 0 to the browser's `medium`
 *   (~3px); or dropping `border-solid`, which takes the wanted top edge from
 *   1px to 0.
 * - the stacking case: deleting `.lay-region-float` from `layout.css`, or
 *   removing the class from any of the three panels, both of which leave the
 *   float at `z-index: auto`.
 */

// The canvas is `React.lazy` over `react-force-graph-2d`; a real WebGL-adjacent
// force simulation is not what any assertion below is about, and letting it
// mount would make the whole file wait on a d3 tick.
vi.mock('./GraphCanvas.tsx', () => ({
  GraphCanvas: () => <div data-fake-canvas className="absolute inset-0" />,
}))

const node = (id: string): GraphNode => ({
  id,
  name: `Entity ${id}`,
  entityType: 'Person',
})

/** Enough nodes and enough edges that both scrollers really scroll. An
 *  unclipped list measures nothing — there is no clip for a ring to fall
 *  outside of. */
const NODES = Array.from({ length: 24 }, (_, index) => node(`n${String(index)}`))

const view: GraphView = {
  nodes: NODES,
  links: NODES.slice(1).map((other) => ({
    source: 'n0',
    target: other.id,
    relationshipType: 'advised',
  })),
  expanded: new Set(['n0']),
}

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

// `GraphDetail`'s new usages section reads through a query hook, which is why
// this file gained a container and a `QueryClient` it did not need before --
// see `GraphDetail.test.tsx` for the behaviour this repository fakes; here it
// only has to not throw on mount, since every assertion below is geometry.
const usages: UsagesRepository = { usages: vi.fn().mockResolvedValue([]) }
const container = { usages } as unknown as AppContainer
const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })

/** Boxed to a real size: `GraphBrowser` is `flex-1 min-h-0`, so rendered into
 *  an unsized parent it would be zero-height and every float would measure as a
 *  zero rect that satisfies any containment assertion vacuously. */
const Mounted = () => (
  <QueryClientProvider client={queryClient}>
    <ContainerProvider container={container}>
      <div style={{ width: '900px', height: '420px', display: 'flex' }}>
        <GraphBrowser
          projectId={PROJECT}
          view={view}
          results={NODES}
          knownTypes={['Person']}
          truncated={false}
          searching={false}
          error={null}
          partial={false}
          edgesPartial={false}
          loading={false}
          entity="n0"
          term="e"
          entityType=""
          onTerm={() => {}}
          onEntityType={() => {}}
          onEntity={() => {}}
          onPick={() => {}}
          onReset={() => {}}
          onRemove={() => {}}
        />
      </div>
    </ContainerProvider>
  </QueryClientProvider>
)

/** The outermost edge an element's outline reaches, in viewport coordinates.
 *  An outline sits `outline-offset` beyond the border box and is
 *  `outline-width` thick, so a negative offset pulls it inside. Copied from
 *  `DocumentBrowser.browser.test.tsx` rather than shared: a helper imported
 *  across two measurement files becomes a thing to keep in step, and it is
 *  eight lines. */
const ringBox = (element: HTMLElement) => {
  const style = getComputedStyle(element)
  const reach = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset)
  const box = element.getBoundingClientRect()
  return {
    drawn: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0,
    offset: parseFloat(style.outlineOffset),
    top: box.top - reach,
    left: box.left - reach,
    right: box.right + reach,
    bottom: box.bottom + reach,
  }
}

/** What `overflow` actually clips: the padding box, not the border box. */
const clipBox = (element: HTMLElement) => {
  const box = element.getBoundingClientRect()
  return {
    top: box.top + element.clientTop,
    left: box.left + element.clientLeft,
    right: box.left + element.clientLeft + element.clientWidth,
    bottom: box.top + element.clientTop + element.clientHeight,
  }
}

/** Asserted rather than assumed. `:focus-visible` after a programmatic
 *  `focus()` is a heuristic; if this engine declined to match it, every rule
 *  under test would be inert while the geometry assertions still passed. */
const focus = (element: HTMLElement) => {
  element.focus()
  expect(element.matches(':focus-visible')).toBe(true)
}

const mount = async () => {
  const screen = await render(<Mounted />)
  // `GraphCanvas` is `React.lazy` even when mocked, so the stage renders its
  // `Suspense` fallback first and the canvas arrives a microtask later.
  // `render` awaits React's commit and not that chunk, so querying straight
  // afterwards finds `null` -- intermittently, because by the second test in a
  // file the module is already resolved. Caught by exactly that: green alone,
  // red in the full suite. Everything below is scoped to this container rather
  // than to `document` for the neighbouring reason, that a leaked render from
  // another file would otherwise be counted.
  const root = screen.container
  await vi.waitFor(() => expect(root.querySelector('[data-fake-canvas]')).not.toBeNull())

  const results = root.querySelector<HTMLElement>('[data-result-scroll]')!
  // `[data-edge-scroll]` is the drawer's body, not the edge `<ul>`. The list
  // used to own the only scroller in the panel, which left every section above
  // it -- definition, mentions -- overflowing the drawer with nowhere to scroll
  // to; the scrolling moved out to the body and this hook moved with it, so
  // these measurements stay pointed at whatever actually clips the rows.
  const edges = root.querySelector<HTMLElement>('[data-edge-scroll]')!
  // The precondition, asserted rather than assumed: with no overflow there is
  // no clip, and both ring assertions below would pass against the defect.
  expect(results.scrollHeight).toBeGreaterThan(results.clientHeight)
  expect(edges.scrollHeight).toBeGreaterThan(edges.clientHeight)
  return { results, edges, root }
}

it('keeps a search result row inside the results panel it is clipped by', async () => {
  const { results, root } = await mount()
  // Not the first row: the first is clipped on three sides at once and would
  // pass a test that only looked at the vertical pair. This one isolates the
  // sides that are wrong for every row wherever the list is scrolled to.
  const row = root.querySelectorAll<HTMLElement>('[data-result-row]')[3]!
  focus(row)

  const ring = ringBox(row)
  const clip = clipBox(results)
  expect(ring.drawn).toBe(true)
  // The assertion the clip ones cannot make on their own: 4px of scroller
  // padding leaves an outward ring passing by 1px, which is slack rather than
  // clearance. Inward is the fix; this is what says so.
  expect(ring.offset).toBe(-2)
  expect(ring.left).toBeGreaterThanOrEqual(clip.left)
  expect(ring.right).toBeLessThanOrEqual(clip.right)
})

it('keeps an entity-detail edge row inside the drawer body it is clipped by', async () => {
  const { edges, root } = await mount()
  const row = root.querySelectorAll<HTMLElement>('[data-edge-row]')[3]!
  focus(row)

  const ring = ringBox(row)
  const clip = clipBox(edges)
  expect(ring.drawn).toBe(true)
  expect(ring.offset).toBe(-2)
  expect(ring.left).toBeGreaterThanOrEqual(clip.left)
  expect(ring.right).toBeLessThanOrEqual(clip.right)
})

it('draws the legend note a top edge and no other', async () => {
  const { root } = await mount()
  // The hollow-node note: `expanded` holds only `n0`, so 23 nodes have more to
  // pull in and the note renders.
  const note = root.querySelector<HTMLElement>('[aria-label="What the canvas colours mean"] p')!
  const style = getComputedStyle(note)

  expect(style.borderTopWidth).toBe('1px')
  expect(style.borderTopStyle).toBe('solid')
  // The half of the house border rule that is easy to forget. Without
  // `border-0` these are the browser's `medium`, and a rule meant for one edge
  // draws a box.
  expect(style.borderBottomWidth).toBe('0px')
  expect(style.borderLeftWidth).toBe('0px')
  expect(style.borderRightWidth).toBe('0px')
})

it('keeps all three floating panels above the canvas, on the one sticky token', async () => {
  const { root } = await mount()
  const sticky = getComputedStyle(document.documentElement).getPropertyValue('--z-sticky').trim()
  // The token has to exist for this test to mean anything: an undeclared custom
  // property makes the browser drop the declaration, and the element silently
  // takes its parent's stacking order — a failure that looks exactly like the
  // rule being obeyed. `scripts/stacking.test.ts` makes the same point.
  expect(sticky).not.toBe('')

  const floats = Array.from(root.querySelectorAll<HTMLElement>('.lay-region-float'))
  // Command bar, detail panel, legend — the inventory `tokens.css` names.
  expect(floats).toHaveLength(3)
  for (const float of floats) {
    const style = getComputedStyle(float)
    expect(style.zIndex).toBe(sticky)
    // A `z-index` on a statically positioned element does nothing at all, which
    // is the way this rewrite could have quietly lost the stacking while
    // keeping the class.
    expect(style.position).toBe('absolute')
  }

  // And that they are in fact above the canvas rather than merely numbered:
  // the canvas is a positioned sibling at `auto`, so any positive integer wins,
  // but only if it is on the same painting root.
  const canvas = root.querySelector<HTMLElement>('[data-fake-canvas]')!
  expect(getComputedStyle(canvas).zIndex).toBe('auto')
  expect(floats[0]!.compareDocumentPosition(canvas) & Node.DOCUMENT_POSITION_PRECEDING).toBe(
    Node.DOCUMENT_POSITION_PRECEDING,
  )
})

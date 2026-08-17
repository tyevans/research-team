/** That the graph widget has a height inside a markdown flow.
 *
 * The assertion this file exists for, and the one no jsdom test can make:
 * jsdom lays nothing out and applies no stylesheet, so
 * `getBoundingClientRect` is `0x0` there whatever `.cmp-graph-box` says.
 * `GraphCanvas` measures its container with a `ResizeObserver` and draws into
 * whatever it measures, so a box with no height is a canvas that draws nothing
 * -- with nothing raised, nothing logged, and a block that simply is not
 * there.
 *
 * **Proved red** by deleting `aspect-ratio` and `min-height` from
 * `.cmp-graph-box` in `components.css`: the box measures 0 high and the height
 * assertion fails. Re-take that measurement if the rule is edited.
 *
 * The wrapper is a real `.md.doc` flow rather than a bare div, because that is
 * the context the widget actually lands in and the height it gets is a
 * property of that context, not of the element alone.
 */
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { ProjectId } from '@domain/shared/identifier.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { GraphWidget } from './GraphWidget.tsx'

vi.mock('../research/GraphCanvas.tsx', () => ({
  // Fills its container, which is the point: what is measured is the *box*,
  // and a canvas that did not stretch would measure the mock rather than the
  // rule under test. The real one carries the same `absolute inset-0`.
  GraphCanvas: () => <div data-fake-canvas className="absolute inset-0" />,
}))

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

/** The provider pair and the resolved fixture, kept identical to
 *  `GraphWidget.test.tsx` on purpose: two files disagreeing about what a
 *  resolved reference looks like would make one of them measure a state the
 *  other never reaches. */
const Harness = ({ children }: { children: ReactNode }) => {
  const container = {
    graphs: {
      search: vi.fn().mockResolvedValue({
        entities: [{ id: 'e1', name: 'Constantine', entityType: 'Person' }],
        truncated: false,
      }),
      neighborhood: vi.fn().mockResolvedValue({
        root: { id: 'e1', name: 'Constantine', entityType: 'Person' },
        entities: [{ id: 'e2', name: 'Nicaea', entityType: 'Place' }],
        relationships: [{ source: 'e1', target: 'e2', relationshipType: 'convened' }],
      }),
    },
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return (
    <ContainerProvider container={container}>
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    </ContainerProvider>
  )
}

it('gives the canvas a box with a real height inside a document flow', async () => {
  const screen = await render(
    <Harness>
      <div className="md doc" style={{ width: '640px' }}>
        <p>Prose before the widget.</p>
        <GraphWidget
          block={componentBlock({
            type: 'graph',
            id: 'constantine-around',
            data: { entity: 'Constantine', depth: 1 },
          })}
          attempts={{} as unknown as AttemptsApi}
          projectId={PROJECT}
        />
        <p>Prose after it.</p>
      </div>
    </Harness>,
  )

  // Polls until the name search and the neighbourhood have both settled --
  // until then the widget is drawing prose, and querying for the box would
  // find nothing rather than find a box measuring zero. The two are worth
  // telling apart: a null here is a test that never reached its subject.
  //
  // Waits on the canvas rather than the box, because the box appears as soon
  // as the queries settle while `GraphCanvas` is behind `React.lazy` and
  // arrives a microtask later -- waiting on the box alone reaches the
  // `getBoundingClientRect` below with the `Suspense` fallback still up.
  await vi.waitFor(() => {
    expect(screen.container.querySelector('[data-fake-canvas]')).not.toBeNull()
  })
  const measured = screen.container.querySelector('[data-graph-widget]') as HTMLElement
  const rect = measured.getBoundingClientRect()

  expect(rect.width).toBeGreaterThan(300)
  expect(rect.height).toBeGreaterThan(200)
  // The canvas fills the box rather than collapsing inside it -- the failure a
  // `position: relative` box with an absolutely-positioned child has when the
  // box itself is fine and the child is not. This is what pins `position:
  // relative` on `.cmp-graph-box`: without it the canvas positions against
  // some ancestor further up and measures that instead.
  const canvas = measured.querySelector('[data-fake-canvas]') as HTMLElement
  expect(canvas.getBoundingClientRect().height).toBeCloseTo(rect.height, 0)

  // An undefined custom property sets no background at all and resolves to a
  // transparent computed value, which is how `--bg-raised` (not a token this
  // build defines) would have shipped looking like a rule that worked.
  expect(getComputedStyle(measured).backgroundColor).not.toBe('rgba(0, 0, 0, 0)')
})

/** `.cmp-passage`'s border geometry, which arrived with the `evidence` widget
 *  and had no measurement.
 *
 * Here rather than in a file of its own because it is one assertion and this
 * is already the browser project; CLAUDE.md is explicit that no gate catches
 * this and that jsdom cannot see it. The rule pairs `border: 0` with
 * `border-left: 2px`, and the failure it guards against is the `border-solid`
 * trap: a directional width beside an all-sides style leaves the other three
 * at the browser's `medium` (~3px), so a rule meant for one edge draws a box.
 *
 * **Proved red** by deleting the `border: 0` line from `.cmp-passage` and
 * adding `border-style: solid`: `borderTopWidth` comes back as `3px`.
 */
it('draws the passage rule on one edge only', async () => {
  const screen = await render(
    <div className="md doc">
      <figure className="cmp-passage">
        <blockquote>cunctos populos</blockquote>
      </figure>
    </div>,
  )

  const passage = screen.container.querySelector('.cmp-passage') as HTMLElement
  const style = getComputedStyle(passage)

  expect(style.borderLeftWidth).toBe('2px')
  expect(style.borderTopWidth).toBe('0px')
  expect(style.borderRightWidth).toBe('0px')
  expect(style.borderBottomWidth).toBe('0px')
})

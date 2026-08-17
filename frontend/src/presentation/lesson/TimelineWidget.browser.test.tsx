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
 * wrong reason. The bands below carry real ISO bounds for that reason, and
 * they come from the shared harness so the two suites cannot drift apart on
 * what a drawable timeline is.
 *
 * The wrapper is a real `.md.doc` flow rather than a bare div, because that is
 * the context the widget lands in and the height it gets is a property of that
 * context.
 */
import { expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { TimelineWidget } from './TimelineWidget.tsx'

it('gives the axis a box with a real height inside a document flow', async () => {
  const timeline = vi.fn().mockResolvedValue({
    // Two bands with distinct bounds: one instant is a zero-width span the
    // canvas special-cases, and a test on that path would be measuring the
    // special case rather than the ordinary drawing.
    bands: [band('b1', '0300-01-01', '0330-01-01'), band('b2', '0350-01-01', '0400-01-01')],
    undatedCount: 412,
    truncated: false,
  })
  const Harness = harness(timeline)
  const screen = await render(
    <Harness>
      <div className="md doc" style={{ width: '640px' }}>
        <p>Prose before the widget.</p>
        <TimelineWidget
          block={componentBlock({
            type: 'timeline',
            id: 'fourth-century-people',
            data: { entity_type: 'Person', from: '0300-01-01', to: '0400-01-01' },
          })}
          attempts={{} as unknown as AttemptsApi}
          projectId={PROJECT}
        />
        <p>Prose after it.</p>
      </div>
    </Harness>,
  )

  // Polls on the canvas's own `svg`, not on the box: the box appears as soon
  // as the query settles while `TimelineCanvas` is behind `React.lazy` and
  // arrives a microtask later. Waiting on the box alone reaches the
  // measurement with the `Suspense` fallback still up -- and, worse, would
  // pass even if the canvas rendered `null` for want of a usable span.
  await vi.waitFor(() => {
    expect(screen.container.querySelector('[data-timeline-widget] svg')).not.toBeNull()
  })

  const measured = screen.container.querySelector('[data-timeline-widget]') as HTMLElement
  const rect = measured.getBoundingClientRect()

  expect(rect.width).toBeGreaterThan(300)
  expect(rect.height).toBeGreaterThan(150)

  // An undefined custom property sets no background at all and resolves to a
  // transparent computed value, which is how `--bg-raised` (not a token this
  // build defines) would have shipped looking like a rule that worked.
  expect(getComputedStyle(measured).backgroundColor).not.toBe('rgba(0, 0, 0, 0)')

  // The counts are the point of rendering them at all, and `--fg-muted` is
  // the other undefined token a brief handed this feature: naming it would
  // leave the line in the body colour, which looks fine and stops reading as
  // an aside. Compared against the surrounding prose rather than to a literal,
  // so a token value change does not fail this.
  const counts = screen.container.querySelector('.cmp-timeline-counts') as HTMLElement
  const prose = screen.container.querySelector('.md.doc > p') as HTMLElement
  expect(counts.textContent).toContain('412')
  expect(getComputedStyle(counts).color).not.toBe(getComputedStyle(prose).color)
})

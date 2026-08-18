/** That the explorer has a height, and that its control row does not eat it.
 *
 * `TimelineCanvas` is pure SVG sized by its container, and a markdown flow
 * gives it none. jsdom reports `0x0` here whatever `.cmp-timeline-box` says, so
 * this is the suite that can judge it -- the same assertion `graph` and
 * `timeline` both needed, for the same reason.
 *
 * **Proved red**, on 2026-08-17 and measured rather than reasoned: with
 * `min-height` commented out of `.cmp-timeline-box` the box measures 0 high and
 * `rect.height` fails here *and* in `TimelineWidget.browser.test.tsx`, which is
 * also the check that the two suites are measuring one rule rather than two
 * that happen to agree. With `.cmp-explorer-controls` removed, the control row
 * loses its background and its height and the two assertions on it fail.
 * Re-take both if either rule is edited.
 *
 * The canvas is *not* mocked, unlike the jsdom suites: `TimelineCanvas` returns
 * `null` when `spanOf(bands)` is null (`TimelineCanvas.tsx:120`), so a fixture
 * with no usable dates would measure an empty box and pass for the wrong
 * reason. The bands come from the shared harness for that reason.
 *
 * The wrapper is a real `.md.doc` flow rather than a bare div, because that is
 * the context the widget lands in and the height it gets is a property of that
 * context. The viewport is set in `vite.config.ts`, not by this wrapper's width
 * -- if a media query ever governs this row, that is the file to read.
 */
import { expect, it, vi } from 'vitest'
import { render } from 'vitest-browser-react'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { band, harness, PROJECT } from './timeline-widget-harness.tsx'
import { ExplorerWidget } from './ExplorerWidget.tsx'

it('gives the axis a box with a real height below its controls', async () => {
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
        <ExplorerWidget
          block={componentBlock({
            type: 'explorer',
            id: 'fourth-century-explorer',
            data: {
              over: 'timeline',
              prompt: 'Pull the window back.',
              vary: ['entity_type', 'window'],
              from: '0300-01-01',
              to: '0400-01-01',
            },
          })}
          attempts={{} as unknown as AttemptsApi}
          projectId={PROJECT}
        />
        <p>Prose after it.</p>
      </div>
    </Harness>,
  )

  // Polls on the canvas's own `svg`, not on the box: the box appears as soon as
  // the query settles while `TimelineCanvas` is behind `React.lazy` and arrives
  // a microtask later. Waiting on the box alone reaches the measurement with
  // the `Suspense` fallback still up -- and would pass even if the canvas
  // rendered `null` for want of a usable span.
  await vi.waitFor(() => {
    expect(screen.container.querySelector('[data-explorer-widget] svg')).not.toBeNull()
  })

  const measured = screen.container.querySelector('[data-explorer-widget]') as HTMLElement
  const rect = measured.getBoundingClientRect()

  expect(rect.width).toBeGreaterThan(300)
  expect(rect.height).toBeGreaterThan(150)

  // The background is read off `.cmp-timeline-box` and not off the marked
  // wrapper, which differs from `TimelineWidget.browser.test.tsx` because the
  // DOM differs: there the marker is *on* the box, here it is on a wrapper that
  // survives an empty result and carries no rule of its own. Asserting on the
  // wrapper would fail against correct CSS.
  //
  // An undefined custom property sets no background at all and resolves to a
  // transparent computed value, which is how `--bg-raised` (not a token this
  // build defines) would have shipped looking like a rule that worked.
  const box = screen.container.querySelector('.cmp-timeline-box') as HTMLElement
  expect(getComputedStyle(box).backgroundColor).not.toBe('rgba(0, 0, 0, 0)')

  // The controls are above the drawing rather than over it. `.cmp-timeline-box`
  // sets `position: relative` so the canvas's absolutely positioned children
  // resolve against it; a control row that ended up inside that containing
  // block would draw across the axis while every other assertion here still
  // passed.
  const controls = screen.container.querySelector('.cmp-explorer-controls') as HTMLElement
  const controlRect = controls.getBoundingClientRect()
  expect(controlRect.height).toBeGreaterThan(20)
  expect(controlRect.bottom).toBeLessThanOrEqual(rect.top)

  // The one assertion that fails if `.cmp-explorer-controls` itself is missing
  // rather than if some rule it reuses is: a `<fieldset>` with no rule of ours
  // is transparent, and the row would read as loose controls in the prose.
  expect(getComputedStyle(controls).backgroundColor).not.toBe('rgba(0, 0, 0, 0)')

  // The prompt is the author's invitation and the note is an aside about the
  // widget, so they must not be the same colour. Compared to each other rather
  // than to literals, so a token value change does not fail this -- and
  // `--fg-muted`, an undefined token two briefs on this branch already named,
  // would leave the note in body colour and collapse the difference.
  const prompt = screen.container.querySelector('.cmp-explorer-prompt') as HTMLElement
  const note = screen.container.querySelector('.cmp-explorer-note') as HTMLElement
  expect(getComputedStyle(note).color).not.toBe(getComputedStyle(prompt).color)

  // `flex-basis: 100%` is the only load-bearing *layout* declaration in this
  // stylesheet, and the colour assertion above passes without it.
  //
  // The ordering assertion is NOT what proves it, and that is measured rather
  // than reasoned (2026-08-17): with `flex-basis` deleted the note's top is
  // 187.94 against a last-field bottom of 175.94 -- byte-identical to the
  // styled run. At this suite's width the note's own text (395.09px of it) plus
  // the three fields already overflows the row's 564px of content box, so it
  // wraps to its own line whichever way the rule goes. The ordering is kept as
  // the statement of intent, and would catch a future rule that pulled the note
  // up, but it cannot catch this one going missing.
  //
  // The width is what discriminates: 564 (the row's whole content box) with the
  // declaration, 395.09 (shrink-to-fit around the sentence) without it. A note
  // narrower than the row is one a shorter sentence would let a control sit
  // beside -- the defect the rule exists to prevent, at a width or a wording
  // this test does not have.
  const fields = screen.container.querySelectorAll('.cmp-explorer-field')
  const lastField = fields[fields.length - 1] as HTMLElement
  expect(note.getBoundingClientRect().top).toBeGreaterThanOrEqual(
    lastField.getBoundingClientRect().bottom,
  )
  // 0.75rem of padding each side, from `.cmp-explorer-controls`.
  const content = controlRect.width - 24
  expect(note.getBoundingClientRect().width).toBeCloseTo(content, 0)

  // The counts read as an aside. Compared against the surrounding prose rather
  // than to a literal, for the reason above.
  const counts = screen.container.querySelector('.cmp-timeline-counts') as HTMLElement
  const prose = screen.container.querySelector('.md.doc > p') as HTMLElement
  expect(counts.textContent).toContain('412')
  expect(getComputedStyle(counts).color).not.toBe(getComputedStyle(prose).color)
})

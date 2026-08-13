import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import { Pane } from './Pane.tsx'
import { Shell } from './Shell.tsx'
import { Split } from './Split.tsx'
import type { Track } from './split-tracks.ts'

/** The two layout findings whose real assertion has been a comment until now.
 *
 * Both were fixed on measurements taken by hand in Storybook and shipped with
 * the numbers written into a comment, because jsdom reports `scrollHeight` 0 on
 * every element and returns nothing a stylesheet contributed. These are those
 * measurements, executable.
 *
 * The numbers here are ranges and relations rather than the exact pixels the
 * commits recorded -- `1333/735` is a fact about one viewport with one font,
 * and a test asserting it would fail on a machine that renders text a pixel
 * differently while the layout it is about is perfectly correct. What is
 * asserted is the thing that was actually wrong: which element scrolls, and
 * which way the text runs.
 */

const TRACKS: readonly Track[] = [
  { id: 'rail', min: 280, weight: 1 },
  { id: 'stage', min: 320, weight: 2 },
]

const Long = ({ what }: { what: string }) => (
  <div>
    {Array.from({ length: 60 }, (_, index) => (
      <p key={index}>
        {what} {index + 1}
      </p>
    ))}
  </div>
)

const scrolls = (element: Element) => element.scrollHeight > element.clientHeight + 1

it('scrolls the surface in page mode and the regions in viewport mode', async () => {
  await render(
    <div style={{ height: '600px' }}>
      <Shell scroll="page">
        <Pane id="stack" label="Everything">
          <Long what="row" />
        </Pane>
      </Shell>
    </div>,
  )
  await expect.element(page.getByText('row 1', { exact: true })).toBeVisible()

  const surface = document.querySelector('.lay-surface')!
  const body = document.querySelector('.lay-pane-body')!

  // The finding: `scroll="page"` set `overflow: auto` on the surface and
  // released nothing below it, so the innermost scroller absorbed the content
  // and the surface had nothing to scroll. Both stories rendered the same page.
  expect(scrolls(surface)).toBe(true)
  expect(scrolls(body)).toBe(false)
  // Not merely "the body is short" — it holds all sixty rows, and the surface
  // is the box that overflows.
  expect(body.scrollHeight).toBeGreaterThan(surface.clientHeight)
})

it('leaves the scrolling to the regions in viewport mode', async () => {
  await render(
    <div style={{ height: '600px' }}>
      <Shell scroll="viewport">
        <Pane id="stack" label="Everything">
          <Long what="row" />
        </Pane>
      </Shell>
    </div>,
  )
  await expect.element(page.getByText('row 1', { exact: true })).toBeVisible()

  // The other half of the pair, and the reason the first test means anything:
  // before the fix these two assertions were both true of both modes.
  expect(scrolls(document.querySelector('.lay-surface')!)).toBe(false)
  expect(scrolls(document.querySelector('.lay-pane-body')!)).toBe(true)
})

it('turns a collapsed pane’s title on its side while the split is columns', async () => {
  await render(
    <div style={{ width: '1200px', height: '600px' }}>
      <Split
        id="research"
        label="Research"
        tracks={TRACKS}
        collapsed={new Set(['rail'])}
        onCollapsedChange={() => {}}
      >
        <Pane id="rail" label="Topics">
          topics
        </Pane>
        <Pane id="stage" label="Graph">
          graph
        </Pane>
      </Split>
    </div>,
  )

  await expect.element(page.getByRole('heading', { name: 'Graph' })).toBeVisible()

  const collapsed = document.querySelector('[data-pane="rail"]')!
  const title = collapsed.querySelector('.lay-pane-title')!

  // The finding: the pane got `RAIL_TRACK`'s 34px from `splitTemplate` while
  // its title stayed horizontal, because rotation lived under
  // `[data-collapse-to='rail']` and the pane had been told `strip`. The reader
  // got "▸ C". Two independent decisions about one pane.
  expect(getComputedStyle(title).writingMode).toBe('vertical-rl')
  // Taller than it is wide, which is the whole claim in one number and does not
  // depend on the font: a horizontal title in a 34px column is the defect.
  const box = title.getBoundingClientRect()
  expect(box.height).toBeGreaterThan(box.width)
  expect(collapsed.getBoundingClientRect().width).toBeLessThan(60)
})

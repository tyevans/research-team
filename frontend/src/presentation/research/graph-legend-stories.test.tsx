import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './GraphLegend.stories.tsx'

/** The legend names the types that are drawn, commonest first.
 *
 * Both halves are assertable without a browser -- they are text and order --
 * and both are rules a reader cannot verify by looking at one legend. Only a
 * fixture where alphabetical and by-count disagree can tell the two sorts
 * apart, which is why `ManyTypes` is built that way and why this file exists
 * rather than the story alone.
 *
 * What is deliberately not asserted: the colours. `colorForType` hashes, so
 * pinning a swatch to a literal would pin the hash, and the hash is free to
 * change as long as it stays stable within a session. The legend's *claim* is
 * that the swatch matches the canvas, and nothing here draws a canvas -- that
 * comparison would need `GraphCanvas`, which is lazy and pulls ~60 kB.
 * `graph-legend.browser.test.tsx` owns the geometry.
 *
 * **Proved red** by sorting `types` alphabetically in `GraphLegend.tsx`:
 * the order assertion fails with `artefact` first.
 */
const { TwoTypes, ManyTypes, NothingDrawn } = composeStories(stories)

const labels = () =>
  [...document.body.querySelectorAll('li')].map((each) => each.textContent?.trim() ?? '')

it('names every type that is drawn', () => {
  render(<TwoTypes />)
  const shown = labels().join(' ')
  expect(shown).toContain('concept')
  expect(shown).toContain('fact')
})

/** The rule a single legend cannot show. `person` is commonest and
 *  `artefact` is alphabetically first; a legend that opens with `artefact`
 *  has been sorted the wrong way. */
it('orders types by how many are drawn, not alphabetically', () => {
  render(<ManyTypes />)
  const shown = labels()
  expect(shown[0]).toContain('person')
  expect(shown[shown.length - 1]).toContain('hypothesis')
  expect(shown[0]).not.toContain('artefact')
})

/** A key to a picture that does not exist reads as a control that failed to
 *  load, so the component returns `null` rather than an empty panel. */
it('draws nothing at all when nothing is on the canvas', () => {
  render(<NothingDrawn />)
  expect(labels()).toHaveLength(0)
  expect(screen.queryByText(/concept|person|fact/)).not.toBeInTheDocument()
})

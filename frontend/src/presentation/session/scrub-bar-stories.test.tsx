import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './ScrubBar.stories.tsx'

/** The two scrub modes are told apart, which is the whole job of this bar.
 *
 * A transcript pinned to event 3 renders the same components in the same
 * places as one following the head; only the messages are older. If this bar
 * does not distinguish them, every other surface on the page is quietly
 * lying about how current it is, and a reader can act on a stale file tree
 * without being told.
 *
 * So the assertions are *differences*, not presences. "The historical bar says
 * time travel" would pass on a build where the live bar said it too, and that
 * build is the defect. Each test below checks the marker is present in one
 * mode and absent in the other.
 *
 * jsdom rather than the browser suite, because everything here is text and
 * class membership. The one claim that would need a browser — that the accent
 * dot is actually accent-coloured — is deliberately not made here; it is an
 * inline `style` on that element, which is the single thing jsdom does report
 * faithfully, and asserting it would be asserting the story's own literal
 * rather than the stylesheet's.
 *
 * **Proved red** by rendering `Live` and asserting it *does* carry the
 * historical marker: fails, so the absence assertions are load-bearing rather
 * than passing against a bar that says nothing at all.
 */
const { Live, Historical, BeforeTheProjectionArrives } = composeStories(stories)

const bar = () => document.body.querySelector('.scrub-bar')

it('marks a historical point as time travel', () => {
  render(<Historical />)
  expect(screen.getByText(/time travel/i)).toBeInTheDocument()
})

/** The other half, and the half that matters. */
it('does not say time travel while following the head', () => {
  render(<Live />)
  expect(screen.queryByText(/time travel/i)).not.toBeInTheDocument()
})

/** The class the stylesheet keys the whole mode off.
 *
 *  Asserted in both directions in one test, because the pair is the claim: a
 *  build where `historical` is always on and one where it is never on both
 *  fail exactly one half of this. */
it('carries the historical class only when scrubbed', () => {
  const { unmount } = render(<Historical />)
  expect(bar()?.className).toContain('historical')
  unmount()

  render(<Live />)
  expect(bar()?.className).not.toContain('historical')
})

/** A first paint has no projection, and must still draw a bar.
 *
 *  `head` is null until the query resolves. A bar that renders nothing at all
 *  in that window is the layout jump `Skeletons.tsx` argues about, on the one
 *  row that is always on screen. */
it('draws a bar before the projection arrives', () => {
  render(<BeforeTheProjectionArrives />)
  expect(bar()).not.toBeNull()
  expect(bar()?.textContent?.trim()).not.toBe('')
})

import { expect, it } from 'vitest'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'

import { ResolvedFrame } from './ResolvedFrame.tsx'

/** That `.cmp-ref-quiet` is a rule in the bundle and not merely a word in the
 *  class attribute.
 *
 * The class earned this file by being caught without one. `loading` and
 * `unavailable` carry no note -- neither may make a claim about the corpus --
 * so the dimmer name is the *only* thing distinguishing an unconfirmed
 * reference from a confirmed one, and a selector that matches no rule looks
 * exactly like one that does. CLAUDE.md names this shape twice (the unlayered
 * `tokens.css` entry, the `border-solid` entry) and both times the tell was
 * that no gate reported it.
 *
 * jsdom cannot make this assertion: `getComputedStyle` there returns only what
 * an inline style said, so `color` would read as the initial value whatever
 * `components.css` holds. That is the whole reason this file is in the browser
 * project rather than beside `ResolvedFrame.test.tsx`.
 *
 * **Proved red**, by deleting the `.cmp-ref-quiet .cmp-ref-name` rule from
 * `components.css` and re-running: the two colours come back equal.
 */
const colourOf = (element: Element) => getComputedStyle(element).color

it('draws an unconfirmed reference dimmer than a missing one', async () => {
  await render(
    <div>
      <ResolvedFrame reference={{ state: 'unavailable' }} name="Quiet">
        {() => <p>never</p>}
      </ResolvedFrame>
      <ResolvedFrame reference={{ state: 'missing' }} name="Missing">
        {() => <p>never</p>}
      </ResolvedFrame>
    </div>,
  )

  const quiet = page.getByText('Quiet').element()
  const missing = page.getByText('Missing').element()

  // Against each other rather than against a literal: pinning the rgb() would
  // fail on a token change that is not a defect, and what the rule exists to
  // say is a *difference*.
  expect(colourOf(quiet)).not.toBe(colourOf(missing))
  // And the difference is in the direction the rule intends -- an equality
  // check alone would pass on a rule that made the quiet state louder.
  expect(getComputedStyle(quiet).fontWeight).toBe('500')
  expect(getComputedStyle(missing).fontWeight).toBe('600')
})

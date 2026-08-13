import { page } from 'vitest/browser'
import { useState } from 'react'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import { Choices } from './Choices.tsx'
import { TabList, TabPanel, Tabs } from './Tabs.tsx'

/** The chosen control has to look chosen, which no jsdom test can see.
 *
 * This is the first browser test in the repository and it exists because the
 * defect it catches shipped: `.tab` keyed its selected look off Radix's
 * `data-state`, and `Choices` puts a `Tooltip` trigger `asChild` over its
 * `RadioGroup.Item`, so the tooltip's `data-state="closed"` overwrote the
 * radio's `"checked"` on exactly the two options carrying an explanation. The
 * chosen one drew in the unchosen colour. Every unit test passed, because jsdom
 * applies no stylesheet and a selector that matches nothing looks the same as
 * one that matches.
 *
 * **Proved red** by putting the `[data-state=…]` selector back in
 * `workspace.css`: `author` reports `rgb(92, 102, 115)`, the dim colour, and
 * this fails. So the test measures a real stylesheet rather than passing by
 * luck.
 *
 * The second red proof attempted -- commenting out `index.css` in
 * `vitest.setup.browser.ts`, expecting an unstyled page -- stayed green, which
 * is worth recording because it was informative rather than reassuring: the
 * stylesheet also arrives through `.storybook/preview.tsx`. That is argued
 * where it now cannot quietly change.
 */

/** The accent a chosen control draws in, and the dim it does not.
 *
 * Written as literals rather than read back from the custom property, which
 * would let a token that changed to the wrong value agree with itself. These
 * are `--accent` and `--fg-faint` as measured; if the palette moves on purpose
 * this test says so and gets updated. */
const ACCENT = 'rgb(226, 164, 87)'
const DIM = 'rgb(92, 102, 115)'

const colourOf = (element: Element) => getComputedStyle(element).color

/** Both controls hold real state, which a fixture for this suite has to.
 *
 *  Written first with `value="author"` and a no-op handler, which is harmless
 *  in a colour assertion and silently makes a keyboard one unfalsifiable: a
 *  controlled component whose value never changes cannot move, so the arrow-key
 *  test failed against a component that was working. */
const Header = () => {
  const [audience, setAudience] = useState<'author' | 'learner'>('author')
  const [tab, setTab] = useState('content')
  return (
    <Tabs value={tab} onValueChange={setTab}>
      <div className="file-view-head">
        <Choices
          label="Whose view of this document"
          options={[
            { id: 'author', label: 'author', explanation: 'Everything the file contains.' },
            { id: 'learner', label: 'learner', explanation: 'What a learner is sent.' },
          ]}
          value={audience}
          onValueChange={setAudience}
        />
        <TabList
          label="File view"
          options={[
            { id: 'content', label: 'contents' },
            { id: 'history', label: 'history' },
          ]}
        />
      </div>
      <TabPanel value="content">the file</TabPanel>
      <TabPanel value="history">every revision</TabPanel>
    </Tabs>
  )
}

it('draws the chosen control in the accent, tooltip or no tooltip', async () => {
  await render(<Header />)

  // `author` is the one that regressed: it carries an explanation, so a second
  // Radix component writes to the element the stylesheet was reading.
  const author = page.getByRole('radio', { name: 'author' })
  await expect.element(author).toBeVisible()
  expect(colourOf(author.element())).toBe(ACCENT)
  expect(colourOf(page.getByRole('radio', { name: 'learner' }).element())).toBe(DIM)

  // The tab list has no tooltip on it and drew correctly throughout. Here to
  // hold the other half of the selector, `[aria-selected]`, which nothing has
  // broken yet.
  expect(colourOf(page.getByRole('tab', { name: 'contents' }).element())).toBe(ACCENT)
  expect(colourOf(page.getByRole('tab', { name: 'history' }).element())).toBe(DIM)
})

/** **The arrow-key assertion is deliberately not here, and that is a finding.**
 *
 * `Choices.test.tsx` says the claim it wants -- one ArrowRight in the group
 * selects the next option -- cannot be written under jsdom, and points at this
 * suite. It cannot be written here either, yet.
 *
 * What happens: `page.getByRole(…).click()` then `userEvent.keyboard('{ArrowRight}')`
 * passes occasionally and times out most of the time, waiting for an
 * `aria-checked` that never moves. Characterised rather than guessed at -- eight
 * runs of the same body in one file, four over a group with tooltips and four
 * without, failed seven times, and the one that passed was a tooltip-free group.
 * So it is not the `Tooltip` wrapper, and it is not the component: the identical
 * interaction driven straight through Playwright against Storybook works every
 * time, which is how the behaviour was confirmed when `Choices` was written
 * (Tab in, one ArrowRight, `source` checked and the panel switched).
 *
 * The gap is in how this harness delivers a key to a freshly-clicked element.
 * Left unwritten rather than committed flaky: a suite whose first keyboard test
 * fails seven times in eight teaches everyone to re-run it, and a suite people
 * re-run is a suite people ignore. The claim stays verified by hand until the
 * delivery is understood.
 */

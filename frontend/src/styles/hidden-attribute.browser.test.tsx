import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

import { TabList, TabPanel, Tabs } from '@presentation/common/Tabs.tsx'

/** That `hidden` actually hides, even on an element carrying a display utility.
 *
 * **The defect this holds the line on shipped, and was found by eye.** The
 * project page's MATERIAL region drew two tab panels at once: the document list
 * in the top half and the knowledge graph in the bottom. Measured in the running
 * app at 1440x900 — the `doc` panel with `hidden=true` and a computed
 * `display: flex`, the `entity` panel active, both `flex: 1` in a 790px column,
 * so each got 395px. It read as a graph that would not fill its pane, which is
 * why it was reported as one.
 *
 * The cause is not in either component. Radix hides an inactive `Tabs.Content`
 * with the `hidden` attribute and nothing else, and `hidden` is only the *user
 * agent's* `display: none`. This build imports no Tailwind preflight, so nothing
 * author-level restores it — and `[hidden]` and `.flex` have equal specificity,
 * with utilities emitted after `base.css`. The two panels that hid correctly
 * were the two that happened not to need a display utility.
 *
 * **Why this cannot be a jsdom test.** Same reason as `spacing-zero`: jsdom
 * applies no stylesheet and implements no user-agent one, so a hidden panel and
 * a drawn one are the same object there. The jsdom suite asserts what Radix
 * *marks* — `hidden`, `data-state` — and every one of those assertions was green
 * throughout, because every one of them was true. The attribute was set. It just
 * did not do anything.
 *
 * **Proved red** by removing the rule from `base.css`: the first case fails at
 * `expected 'flex' to be 'none'`, the second at `expected [ <div …(8)></div>,
 * …(2) ] to have a length of 1 but got 3` — three rather than two, because three
 * of the five panels below carry `flex`, and the count is exactly the number of
 * panels a reader would have found stacked in the pane.
 */

/** The four panel classNames are `ProjectView.tsx`'s, verbatim and in order.
 *  The mix is the point — two carry `flex` and two do not, which is exactly the
 *  arrangement in which the bug hides half the time. */
const PANELS = [
  { id: 'artifact', label: 'Artifacts', className: 'min-h-0 flex-1 overflow-auto' },
  { id: 'file', label: 'Workspace', className: 'flex min-h-0 flex-1 flex-col' },
  { id: 'finding', label: 'Findings', className: 'min-h-0 flex-1 overflow-auto' },
  { id: 'doc', label: 'Documents', className: 'flex min-h-0 flex-1 flex-col' },
  { id: 'entity', label: 'Graph', className: 'flex min-h-0 flex-1 flex-col' },
]

it('hides an element that is both hidden and a flex container', () => {
  const { container } = render(
    <>
      <div data-testid="both" hidden className="flex flex-col" />
      {/* The control, and it is what makes the first assertion mean anything:
          if `.flex` had stopped being emitted, `both` would read `none` for the
          wrong reason and this file would pass while guarding nothing. */}
      <div data-testid="shown" className="flex flex-col" />
      {/* `until-found` is exempt by design — its whole purpose is to be
          revealed by in-page search — so it must *not* be forced off.

          Set through a ref rather than as a prop, and that is a finding rather
          than a style choice: React's `hidden` prop is boolean, so
          `hidden="until-found"` in JSX reaches the DOM as `hidden=""` and this
          case would have asserted React's serialisation while reporting the
          selector's. Probed, because the first version of this test failed at
          `expected 'none' to be 'flex'` and the selector was not the reason. */}
      <div
        data-testid="until-found"
        ref={(el) => el?.setAttribute('hidden', 'until-found')}
        className="flex flex-col"
      />
    </>,
  )

  const at = (id: string) => container.querySelector(`[data-testid="${id}"]`)!

  expect(getComputedStyle(at('both')).display).toBe('none')
  expect(getComputedStyle(at('shown')).display).toBe('flex')
  expect(getComputedStyle(at('until-found')).display).toBe('flex')
})

it('draws one tab panel at a time, whatever its layout classes are', () => {
  const { container } = render(
    // A real height, because "the open panel gets the whole column" is the half
    // of this that a reader saw and a zero-height box cannot express.
    <div style={{ height: '600px', display: 'flex', flexDirection: 'column' }}>
      <Tabs value="entity" onValueChange={() => {}} className="flex min-h-0 flex-1 flex-col">
        <TabList label="Material" options={PANELS} />
        {PANELS.map((panel) => (
          <TabPanel key={panel.id} value={panel.id} className={panel.className}>
            <div style={{ flex: 1 }}>{panel.label}</div>
          </TabPanel>
        ))}
      </Tabs>
    </div>,
  )

  const drawn = [...container.querySelectorAll('[role="tabpanel"]')].filter(
    (panel) => getComputedStyle(panel).display !== 'none',
  )

  expect(drawn).toHaveLength(1)
  expect(drawn[0]!.getAttribute('data-state')).toBe('active')

  // And it gets the column, rather than a share of it. This is the assertion in
  // the reader's terms: the number that was wrong on screen was 395 of 790.
  const list = container.querySelector('[role="tablist"]')!.getBoundingClientRect()
  expect(drawn[0]!.getBoundingClientRect().height).toBeCloseTo(600 - list.height, 0)
})

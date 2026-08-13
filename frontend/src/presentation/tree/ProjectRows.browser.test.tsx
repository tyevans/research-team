import { useRef, useState } from 'react'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { ProjectRollup } from '@domain/project/landing.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { itemKey, ProjectRows, type Item } from './ProjectRows.tsx'

/** The 122px hole, asserted for the first time.
 *
 * `itemKey`'s docstring has recorded this incident since it shipped — a project
 * row's measured 155px left against a 33px heading, and 122px of nothing in the
 * middle of the list — and nothing has ever tested it. That is not an oversight
 * anyone could have fixed in `ProjectList.test.tsx`: **jsdom cannot produce this
 * bug at all.** It lays nothing out, so every row's
 * `getBoundingClientRect().height` is 0 and `VirtualList.tsx`'s `|| estimate`
 * fallback fires for every row. With every height coming from the estimate, the
 * measurement cache never holds a *measured* height, and a stale measurement is
 * the whole defect. A jsdom test of this passes against the broken keying.
 *
 * **What it takes to see it.** Rows of two different real heights, and a list
 * whose contents shift position between renders. Both are here: the stub row is
 * 155px and the heading is whatever `.rows-heading` draws, and the test renders
 * the flat list first and then the same projects with headings inserted — which
 * is exactly what the landing page does when the projects query answers.
 *
 * **Proved red.** Changing `getKey={(row) => itemKey(row)}` to
 * `getKey={(_row, index) => String(index)}` in `ProjectRows.tsx` fails the
 * second assertion at `expected 155 to be less than or equal to 1` — a 154px
 * discontinuity between the first heading and the row under it, of the same
 * kind and nearly the same size as the incident `itemKey` describes. The exact
 * number differs from 122 because that one was measured against the row height
 * of the day; the mechanism is identical.
 *
 * Note what does *not* go red: the first assertion, over the flat list, passes
 * under index keying too. Nothing is wrong until the list shifts, which is why
 * a test that rendered one arrangement and stopped would have been reassurance.
 *
 * **The stub row is deliberate.** `ProjectRows` takes `renderProject` rather
 * than a row component, so this file mounts no query client and no container —
 * the defect is in the keying and the measurement, and a real `ProjectListRow`
 * would add nine ports of setup while making the row's height depend on data
 * this test does not care about. A fixed 155px says what the assertion needs.
 *
 * The viewport is `vite.config.ts`'s 1440x900, not the wrapper's width, and the
 * jsdom setup's pinned `offsetWidth`/`offsetHeight` are absent here — both traps
 * CLAUDE.md records against this suite.
 */

const rollup = (index: number): ProjectRollup =>
  ({
    project: {
      id: ProjectId(`0000000${String(index)}-1111-1111-1111-111111111111`),
      name: `project-${String(index)}`,
      activeSessionId: SessionId('3f2a0000-0000-0000-0000-000000000000'),
    },
    sessions: [],
    lastActivity: 0,
  }) as unknown as ProjectRollup

const PROJECTS = Array.from({ length: 8 }, (_, index) => rollup(index))

/** The two arrangements, built here rather than through `withHeadings`.
 *
 * `withHeadings` derives bands from a clock, and a test that had to arrange for
 * "today" and "this week" would be testing the recency rule instead of the
 * measurement. What matters is only that every row shifts down by one position,
 * which is what a heading appearing above the list does. */
const FLAT: readonly Item[] = PROJECTS.map((r) => ({ kind: 'project', rollup: r }))
const GROUPED: readonly Item[] = [
  { kind: 'heading', recency: 'today', count: 4 },
  ...PROJECTS.slice(0, 4).map((r) => ({ kind: 'project' as const, rollup: r })),
  { kind: 'heading', recency: 'week', count: 4 },
  ...PROJECTS.slice(4).map((r) => ({ kind: 'project' as const, rollup: r })),
]

const Rows = () => {
  const scrollRef = useRef<HTMLDivElement | null>(null)
  const [items, setItems] = useState<readonly Item[]>(FLAT)

  return (
    <div>
      <button onClick={() => setItems(GROUPED)}>insert headings</button>
      {/* Short enough that eight 155px rows overflow it: a list with room to
          spare never scrolls, and a virtualizer that renders everything at once
          measures nothing worth checking. */}
      <div ref={scrollRef} style={{ height: '400px', overflow: 'auto' }}>
        <ProjectRows
          items={items}
          scrollRef={scrollRef}
          renderProject={(r) => (
            <div style={{ height: '155px' }} data-project={r.project.name}>
              {r.project.name}
            </div>
          )}
        />
      </div>
    </div>
  )
}

/** Every rendered row's top edge sits on the previous row's bottom edge.
 *
 * Read off the live rects rather than off the virtualizer's numbers, because
 * the bug is precisely that the two disagree — the virtualizer positions a row
 * using a height the row does not have. Sorted by `top` because the DOM order
 * of a virtualized list is not its visual order. */
const gaps = () => {
  const rects = [...document.querySelectorAll('.rows-item')]
    .map((el) => el.getBoundingClientRect())
    .sort((a, b) => a.top - b.top)
  return rects.slice(1).map((rect, index) => Math.abs(rect.top - rects[index]!.bottom))
}

it('leaves no gap between rows when headings shift the list down', async () => {
  await render(<Rows />)
  await expect.element(page.getByText('project-0')).toBeVisible()

  // The flat list, which is fine under any keying — stated so the second
  // assertion's failure is unambiguous when it comes.
  expect(Math.max(...gaps())).toBeLessThanOrEqual(1)

  await page.getByRole('button', { name: 'insert headings' }).click()
  await expect.element(page.getByText('Today')).toBeVisible()

  // Every row has moved down one position. Under index keying the heading now
  // at position 0 inherits a project row's measurement and the virtualizer lays
  // the next row out 155px down from a 33px element.
  expect(Math.max(...gaps())).toBeLessThanOrEqual(1)
})

/** The keys themselves, which is the invariant the gap test only observes.
 *
 * Cheap, and it fails for a reason a reader can act on: a duplicate key names
 * the collision directly, where the gap assertion reports a symptom in pixels.
 * The `h-` prefix is what this is really about — without it a band named like
 * a `ProjectId` shares a measurement cell with a project row. */
it('gives every row in the flattened list a distinct key', () => {
  const keys = GROUPED.map(itemKey)
  expect(new Set(keys).size).toBe(keys.length)
  expect(keys.filter((key) => key.startsWith('h-'))).toEqual(['h-today', 'h-week'])
})

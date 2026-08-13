import { useRef, useState } from 'react'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import type { ProjectRollup } from '@domain/project/landing.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { itemKey, ProjectRows, type Item } from './ProjectRows.tsx'

/** The landing list's geometry, and the 122px hole that could not be brought
 *  back.
 *
 * `itemKey`'s docstring records an incident: a project row's measured 155px
 * left standing against a 33px heading when the projects query answered and
 * every row shifted down one position, leaving 122px of nothing in the middle
 * of the list. This file was written to assert that, since jsdom provably
 * cannot — it lays nothing out, every row's `getBoundingClientRect().height` is
 * 0, `VirtualList.tsx`'s `|| estimate` fallback fires for every row, and a
 * measurement cache that never holds a measured height cannot hold a stale one.
 *
 * **It does not reproduce, and that is the finding.** Inverting the fix —
 * `getKey={(_row, index) => String(index)}` in `ProjectRows.tsx`, which is
 * exactly the default keying the docstring blames — and measuring the gaps
 * between consecutive rows *synchronously, in the same statement as the click
 * that inserts the headings*, gives `[0,0,0,0,0,0,0]`. Not a smaller gap, not a
 * gap that closes a frame later: no gap at any point that can be observed. The
 * virtualizer re-measures through the `ResizeObserver` that `measureElement`
 * installs, and the correction lands before anything can see the stale value.
 *
 * So a gap assertion here would be green against broken keying, which makes it
 * worse than no test — it would read as coverage of the incident and would be
 * coverage of nothing. It was written, run red-first as the convention asks,
 * failed to go red, and was deleted rather than kept as reassurance.
 *
 * **What that leaves.** The keying is still right and the reasons in `itemKey`
 * still hold — identity keys are what make a measurement follow its row, and
 * nothing here argues for going back to index keys. What is now uncertain is
 * whether the *observable* failure is still reachable in the virtualizer this
 * repository ships. Two honest possibilities, neither established: the library
 * gained the ResizeObserver correction after the incident, or the incident had
 * a contributing cause this harness does not reproduce (a scroll that leaves
 * rows unrendered and therefore unmeasured is the obvious candidate, and the
 * one worth trying next). `BACKLOG.md` is where that belongs, not a test
 * pretending to hold the line.
 *
 * The test below is what survives: the invariant itself, asserted directly
 * rather than through pixels. It is cheap and it fails for a reason a reader
 * can act on — a duplicate key names the collision, where a gap assertion
 * reports a symptom in pixels and, as it turns out, does not report it at all.
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
 * `withHeadings` derives bands from a clock, and arranging for "today" and
 * "this week" would test the recency rule instead of the keying. What matters
 * is only that a heading opens each band exactly once, which is the precondition
 * `itemKey`'s uniqueness rests on. */
const GROUPED: readonly Item[] = [
  { kind: 'heading', recency: 'today', count: 4 },
  ...PROJECTS.slice(0, 4).map((r) => ({ kind: 'project' as const, rollup: r })),
  { kind: 'heading', recency: 'week', count: 4 },
  ...PROJECTS.slice(4).map((r) => ({ kind: 'project' as const, rollup: r })),
]

/** Every row in the flattened list has a distinct key.
 *
 * Both halves of `itemKey`'s contract, in one assertion each: no two rows share
 * a key across the *whole* list rather than within a band, and headings live in
 * their own `h-` namespace so a band can never collide with a `ProjectId`.
 *
 * **Proved red** both ways: dropping the `h-` prefix and naming a band with a
 * project's id makes the first fail; emitting `today` twice (which is what an
 * unsorted input would do) makes it fail with a duplicate the second assertion
 * then names.
 *
 * This does not need a browser and says so plainly — it is here rather than in
 * `ProjectList.test.tsx` because it is the surviving half of a browser test,
 * and separating it from the docstring above would strip the record of why the
 * measurement half is missing. */
it('gives every row in the flattened list a distinct key', () => {
  const keys = GROUPED.map(itemKey)

  expect(new Set(keys).size).toBe(keys.length)
  expect(keys.filter((key) => key.startsWith('h-'))).toEqual(['h-today', 'h-week'])
})

/** The list renders and positions its rows contiguously.
 *
 * Not a regression test for the incident — see above, that could not be made to
 * fail. What it does hold is that `ProjectRows` lays out at all in a real
 * engine: rows in order, no overlap, no gap, headings among them. Every one of
 * those is invisible to jsdom, where each rect is 0x0, so this is the only place
 * the component is known to draw.
 *
 * The stub row is deliberate. `ProjectRows` takes `renderProject` rather than a
 * row component, so nothing here needs a query client or a container; a real
 * `ProjectListRow` would add nine ports of setup and make the row's height
 * depend on data this has no opinion about. */
it('lays its rows out in order, with nothing between them', async () => {
  const Rows = () => {
    const scrollRef = useRef<HTMLDivElement | null>(null)
    const [items] = useState<readonly Item[]>(GROUPED)

    return (
      // Short enough that eight 155px rows overflow it: a list with room to
      // spare never scrolls, and a virtualizer that renders everything at once
      // is not the arrangement that ships.
      <div ref={scrollRef} style={{ height: '400px', overflow: 'auto' }}>
        <ProjectRows
          items={items}
          scrollRef={scrollRef}
          renderProject={(r) => <div style={{ height: '155px' }}>{r.project.name}</div>}
        />
      </div>
    )
  }

  await render(<Rows />)
  await expect.element(page.getByText('project-0')).toBeVisible()

  // Read off the live rects rather than the virtualizer's own numbers, since
  // the whole class of defect here is the two disagreeing. Sorted by `top`
  // because the DOM order of a virtualized list is not its visual order.
  const rects = [...document.querySelectorAll('.rows-item')]
    .map((el) => el.getBoundingClientRect())
    .sort((a, b) => a.top - b.top)

  expect(rects.length).toBeGreaterThan(1)
  for (const [index, rect] of rects.slice(1).entries()) {
    expect(Math.abs(rect.top - rects[index]!.bottom)).toBeLessThanOrEqual(1)
  }
})

import { render } from 'vitest-browser-react'
import { expect, it } from 'vitest'

import { ArtifactList } from './ArtifactList.tsx'
import { artifact, course } from './course-fixtures.ts'
import { Findings } from './Findings.tsx'

/** That the two shelves slice 3 rewrote draw the one edge they mean to draw.
 *
 * **This is the assertion `CLAUDE.md` says no gate makes.** Both shelves went
 * from a stylesheet's `border-bottom: 1px solid …` / `border-left: 2px solid …`
 * to Tailwind utilities, and a single-side border in utilities fails in two
 * opposite directions, neither visible to lint, jsdom or the type checker:
 *
 * - `border-b` with no `border-solid` draws **nothing**, because this build
 *   imports no preflight and nothing in `src/styles/` sets `border-style`, so
 *   every side is still `none`.
 * - `border-solid` with no `border-0` draws **three unwanted sides**, because
 *   the shorthand styles all four and the three with no explicit width fall
 *   back to the browser's `medium` (~3px).
 *
 * jsdom cannot see either: `getComputedStyle` there returns what an inline
 * style said and nothing a stylesheet or a utility said, so all four widths
 * read as the initial value whatever the class attribute holds. That is the
 * whole reason this file is in the browser project.
 *
 * **Not proved red.** A benchmark had this machine while slice 3 was written,
 * so neither this file nor any gate was run locally — CI is the first thing to
 * execute it. What would make it red is stated rather than measured: dropping
 * `border-0` from `Artifacts.tsx`'s row makes `borderTopWidth` ~3px instead of
 * 0, and dropping `border-solid` makes `borderBottomWidth` 0 instead of 1px;
 * the same pair, on the left edge, for `Findings`'s `ROW`. `BACKLOG.md` B54 is
 * the precedent for recording an unverified claim in the words "unverified"
 * rather than in the words of a claim that was checked.
 */

const px = (element: Element, side: 'Top' | 'Right' | 'Bottom' | 'Left') =>
  parseFloat(getComputedStyle(element)[`border${side}Width` as 'borderTopWidth'])

it('draws an artifact row a bottom edge and no other', async () => {
  // Two artifacts, because `last:border-b-0` means the last row is the one case
  // where a missing bottom edge is correct — a test that rendered one row would
  // pass with `border-b` deleted.
  const data = course({
    stages: [
      {
        index: 1,
        id: 'step0.intake',
        name: 'Intake',
        kind: 'author',
        spine: 0,
        scopeLevel: 'course',
        status: 'done',
        outputs: [artifact({ path: 'a/one.md' }), artifact({ path: 'a/two.md' })],
        gateDecisions: [],
        reviewerRole: null,
        findingsReport: null,
      },
    ],
  })
  await render(<ArtifactList course={data} />)

  const rows = document.querySelectorAll('li')
  expect(rows.length).toBe(2)

  const first = rows[0]!
  expect(px(first, 'Bottom')).toBeCloseTo(1, 1)
  expect(px(first, 'Top')).toBe(0)
  expect(px(first, 'Left')).toBe(0)
  expect(px(first, 'Right')).toBe(0)

  // The last row's bottom edge is deliberately absent: the list's own container
  // ends there and a trailing hairline reads as a row that failed to load.
  expect(px(rows[1]!, 'Bottom')).toBe(0)
})

it('draws a finding row a left edge in its severity colour and no other', async () => {
  const data = course({
    findings: [
      {
        check: 'objectives.count',
        severity: 'invariant',
        message: 'An invariant does not hold.',
        suggestedEdit: null,
        cites: [],
      },
    ],
  })
  await render(<Findings course={data} />)

  const row = document.querySelector('li[data-severity="invariant"]')!
  expect(px(row, 'Left')).toBeCloseTo(2, 1)
  expect(px(row, 'Top')).toBe(0)
  expect(px(row, 'Right')).toBe(0)
  expect(px(row, 'Bottom')).toBe(0)

  // The colour is the other half of `SEVERITY_EDGE`, and a row that drew a 2px
  // edge in the default grey would satisfy every width assertion above. Read as
  // the resolved colour rather than as a class name, which is the one thing
  // this suite can do and the jsdom one cannot.
  const declared = getComputedStyle(document.documentElement)
    .getPropertyValue('--color-k-failure')
    .trim()
  expect(declared).not.toBe('')
  expect(getComputedStyle(row).borderLeftColor).toBe(toRgb(declared))
})

/** `getComputedStyle` answers colours in `rgb()`, and the token is a hex. */
const toRgb = (hex: string) => {
  const probe = document.createElement('span')
  probe.style.color = hex
  document.body.append(probe)
  const value = getComputedStyle(probe).color
  probe.remove()
  return value
}

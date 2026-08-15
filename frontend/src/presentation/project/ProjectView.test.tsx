import { expect, it } from 'vitest'

import { FACETS } from '../routing/routes.ts'
import { regionOf, type Region } from './ProjectView.tsx'

/** The region map, held where a JSX tree cannot be.
 *
 * The rendered page is exercised in `App.test.tsx`, through the route, because
 * which region a facet reaches is a routing fact and the harness that can see
 * it is the one that renders the application. What is left here is the part
 * that has an answer for facets nothing yet navigates to -- and that is the
 * whole point of this slice, since `file`, `artifact` and `finding` parsed and
 * were linkable for three months while no view read any of them.
 */

it('sends every facet the grammar declares to a region', () => {
  // Against `FACETS` itself rather than a copy: a copy is a second list to
  // forget, and the failure this catches is precisely somebody adding a ninth
  // facet and no renderer for it. `regionOf` is total over `Facet`, so this
  // cannot fail at runtime without also failing to compile -- which is the
  // point. It fails loudly if the type is ever widened to `string`.
  for (const facet of FACETS) {
    expect(regionOf(facet)).toMatch(/^(queue|material)$/)
  }
})

/** Reverted, this test fails: before the merge there were two whole-page
 *  components and no regions at all, so there was no function to import. It is
 *  not reassurance. */
it('puts the three facets that reached no view in a region each', () => {
  // All three in MATERIAL, and `file` is the one that moved: slice 1 put it in
  // HOLDER on the argument that a project file is a file in a session's
  // workspace. That is true about where the bytes live and not about what the
  // reader is asking, and MATERIAL is the region for "what has this project
  // produced" — the workspace tree is the live half of the same shelf the
  // artifacts sit on. `ProjectView.tsx` carries the full argument.
  expect(regionOf('file')).toBe<Region>('material')
  expect(regionOf('artifact')).toBe<Region>('material')
  expect(regionOf('finding')).toBe<Region>('material')
})

/** HOLDER is gone, and `session` is a tab in MATERIAL rather than a region of
 *  its own.
 *
 * **The regions are still named for questions, and this one is a genuine
 * reinterpretation rather than a tidy-up.** HOLDER answered "who is working on
 * this right now", which is a different question from "what has this project
 * produced" — the argument the three-region split was built on. What overrode
 * it is that a permanent middle column spends a third of the page on a
 * transcript a reader consults rather than reads, and the page is a sidebar
 * over one content area. The cost is real and is written down here rather than
 * argued away: the holding session is now one tab-click from invisible, and a
 * reader watching a worker while reading its output can no longer see both.
 *
 * Reverted, this is red twice over: `holder` is not assignable to `Region`, and
 * `regionOf('session')` answers `'holder'`. */
it('puts the holding session in MATERIAL, where its tab is', () => {
  expect(regionOf('session')).toBe<Region>('material')
  expect(FACETS.filter((facet) => regionOf(facet) === 'material')).toContain('session')
})

/** The split that used to be a route boundary. `stage` came from the course
 *  page and `topic` from the research page, and a reader following one thread
 *  crossed between them; they are the same kind of thing and now sit in the
 *  same region. */
it('puts a stage and a topic in the same region, which the old routes did not', () => {
  expect(regionOf('stage')).toBe(regionOf('topic'))
  expect(regionOf('stage')).toBe<Region>('queue')
})

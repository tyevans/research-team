import { expect, it } from 'vitest'

import { FACETS } from '../routing/routes.ts'
import {
  DEFAULT_MATERIAL,
  MATERIAL_TABS,
  regionOf,
  visibleMaterialTabs,
  type Region,
} from './ProjectView.tsx'

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
 *  not reassurance.
 *
 * It covered `artifact` and `finding` beside `file` until those two facets were
 * deleted with the workflow system. `file` is the one that moved and the one
 * worth pinning: slice 1 put it in HOLDER on the argument that a project file
 * is a file in a session's workspace. That is true about where the bytes live
 * and not about what the reader is asking, and MATERIAL is the region for "what
 * has this project produced". */
it('puts the workspace in MATERIAL rather than beside the session it belongs to', () => {
  expect(regionOf('file')).toBe<Region>('material')
})

/** HOLDER is gone, and `session` no longer has a tab of its own either.
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
it('puts the session facet in MATERIAL, and gives it no tab of its own', () => {
  expect(regionOf('session')).toBe<Region>('material')
  expect(FACETS.filter((facet) => regionOf(facet) === 'material')).toContain('session')
  // The half that is new. `session` survives as a *facet* -- `href` writes it
  // for every scrub and every file open on this page -- and it has no trigger
  // in the strip, so `materialTab` has to map it onto one or a scrub selects
  // nothing. `ProjectView.test.tsx` cannot see `materialTab`; `App.test.tsx`
  // renders the mapping.
  expect(ids(MATERIAL_TABS)).not.toContain('session')
})

/** QUEUE is the questions this project still owes an answer to.
 *
 * It used to be that plus a stage rail, and the test here was that a stage and
 * a topic landed in the same region -- the merge's own argument, since the two
 * arrived from two different pages. The rail is deleted and the topic is the
 * whole of QUEUE, so what is left to pin is that a topic is not in MATERIAL:
 * it is work owed, not material produced, and a facet that defaulted into the
 * wrong region would be silent. */
it('puts a topic in QUEUE and not in MATERIAL', () => {
  expect(regionOf('topic')).toBe<Region>('queue')
})

/** **A tripwire, not a measurement.** Eleven is where the material strip was
 *  measured to stop fitting.
 *
 * `MATERIAL_TABS` says it in the array's own comment: "Eleven tabs is where
 * this strip stops fitting, which is worth knowing before the twelfth is
 * added." That is not a style preference. Two tabs are already collapsed into
 * one because of it -- `area` and `path` share the Curriculum tab and the pane
 * toggles between them -- after the two-tab arrangement measured 837px of tabs
 * against MATERIAL's 646px floor and produced two clipped controls in the
 * narrow band.
 *
 * **The real assertion exists and CI does not reach it.**
 * A browser test summed every tab's width, the column gaps and
 * the strip's padding, and requires MATERIAL's floor to be at least that wide.
 * It is in the `browser` project, which `CLAUDE.md` states is "deliberately
 * outside `verify` and outside CI, so nothing forces you to run it". So a
 * twelfth tab merges green today: every gate passes and the strip overflows for
 * a reader on a narrow window.
 *
 * This line is what makes that a conversation instead of a merge. It runs in
 * the `app` project, which CI does run.
 *
 * **Nine now, and eleven is still the measurement.** Artifacts and Findings
 * came out with the workflow system, which buys back roughly 150px of strip.
 * The number below tracks what is *declared*, not what fits -- raising it to
 * eleven "because eleven was measured" would spend headroom no measurement has
 * been re-taken for at these labels, and adding tabs is deliberately out of
 * scope for the removal.
 *
 * **What it cannot do**, stated so nobody mistakes it for the measurement it
 * stands in for: it cannot tell a new tab from a relabelled one, and a set of
 * shorter labels might genuinely fit more. If this fails, the answer is
 * not to raise the number -- it is to run `npm run test:browser` and let the
 * assertion that measures pixels say whether the strip still fits, then update
 * both this count and the sentence in `MATERIAL_TABS` together.
 *
 * **Measured on 2026-08-23** rather than argued. A twelfth tab was added --
 * `path` split back out of the Curriculum tab, which is the exact change that
 * broke the strip the first time -- and the whole CI-reachable suite was run
 * against it:
 *
 * - `npm run typecheck`: clean. `MaterialFacet` is a union and `path` is
 *   already in it, so the compiler has nothing to say.
 * - `--project app --project build`: **1 failed of 160 files**, and the one is
 *   this file.
 *
 * So without this line a twelfth tab passes every gate CI runs. That is the
 * state it exists to end, and it is why the assertion is a bare number rather
 * than something more clever: the thing being defended is a pixel measurement
 * in another suite, and a cleverer proxy here would invite belief it cannot
 * support. */
it('keeps the material strip at the eight tabs it declares', () => {
  expect(MATERIAL_TABS).toHaveLength(8)
})

const ids = (tabs: readonly { id: string }[]) => tabs.map((tab) => tab.id)

const EVERYTHING = { hasWorkspace: true }

/** The default tab, asserted as a value rather than through a render.
 *
 * **Two claims, and the second is the one that would be missed.** That the
 * default is the catalog is the decision; that the catalog has no tab of its
 * own is the fact that makes the decision cost something -- `MATERIAL_TABS`
 * declares nine ids and `catalog` is not among them, so a default set here
 * and not mapped in `materialTab` selects nothing at all. The rendered proof
 * that the mapping happens is in `App.test.tsx`; this is the half that fails
 * at the declaration.
 *
 * Reverted to `'session'` the first line goes red. */
it('defaults to the catalog, which is a facet with no tab of its own', () => {
  expect(DEFAULT_MATERIAL).toBe('catalog')
  expect(ids(MATERIAL_TABS)).not.toContain('catalog')
  // The tab it must be mapped onto. Named here so a rename of `area` fails
  // beside the default rather than one screen away from it.
  expect(ids(MATERIAL_TABS)).toContain('area')
})

/** What a project with everything is offered: everything.
 *
 * The control for the tests below -- without it, "the Workspace is absent" is
 * satisfied by a filter that drops every tab. */
it('offers the whole declared strip to a project with a workspace', () => {
  expect(visibleMaterialTabs(EVERYTHING, DEFAULT_MATERIAL)).toEqual(MATERIAL_TABS)
})

/** The one surviving condition, and its meaning changed with its data source.
 *
 * It was `hasSession` -- is somebody holding this project -- and the tab was
 * therefore absent for every project between sessions, all of which have
 * files. It is `hasWorkspace` now: does the reading head resolve to a session
 * to fold files out of. The gate was not widened; the cause was removed, and
 * the condition followed its data source rather than leading it.
 *
 * What is left behind it is a project nothing has ever been written in, which
 * genuinely has nothing to show. There were two conditions once, and
 * `hasCourse` -- which hid Artifacts and Findings on the 409 from a project
 * running no workflow -- went with the tabs it gated. */
it('drops the Workspace only when the project has no reading head', () => {
  const shown = ids(visibleMaterialTabs({ hasWorkspace: false }, DEFAULT_MATERIAL))
  expect(shown).not.toContain('file')
  // Everything else is unconditional, which is what makes the one condition
  // worth asserting rather than the absence.
  expect(shown).toEqual(ids(MATERIAL_TABS).filter((id) => id !== 'file'))
})

/** **A tab the route names survives its own condition**, so a link somebody
 *  sent still lands on a selected tab rather than on a strip with nothing
 *  chosen.
 *
 * One hideable tab now rather than three, so this is no longer parametrised --
 * and what the parametrisation bought is worth recording, because it is gone:
 * with three cases, "keeps the open tab" could not be satisfied by a special
 * case for whichever tab happened to be picked. With one it can. What still
 * separates the arm from `hasWorkspace` being ignored altogether is the test
 * above: `file` is absent when the route is open on anything else.
 *
 * Reverted -- that arm deleted -- this goes red. */
it('keeps the Workspace tab when the route is open on it, condition or not', () => {
  const shown = ids(visibleMaterialTabs({ hasWorkspace: false }, 'file'))
  expect(shown).toContain('file')
  expect(shown).toEqual(ids(MATERIAL_TABS))
})

/** The strip keeps its declared order when it is filtered.
 *
 * `TabList` renders whatever array it is handed, and a filter that reordered
 * the tabs would move them under a reader between one project and the next.
 * `filter` preserves order by definition, which is exactly why this is worth
 * one line: it pins the property against a future rewrite that builds the
 * list some other way. */
it('filters the strip without reordering it', () => {
  const shown = ids(visibleMaterialTabs({ hasWorkspace: false }, DEFAULT_MATERIAL))
  expect(shown).toEqual(ids(MATERIAL_TABS).filter((id) => id !== 'file'))
})

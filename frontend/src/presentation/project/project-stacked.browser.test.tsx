import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { afterEach, expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { Shell } from '@presentation/layout/Shell.tsx'
import { StreamProvider } from '@presentation/shell/StreamProvider.tsx'

import { resizeViewport, restoreViewport } from '../../test/browser-viewport.ts'
import { ProjectView } from './ProjectView.tsx'

/** What the project page does *below* 821px, which nothing had ever measured.
 *
 * `project-responsive.browser.test.tsx` is scoped to the 821-1180 band and
 * reaches 821 from inside it; `ProjectView.browser.test.tsx` is scoped above
 * 1180. This is the third band, and before this file the repository's only
 * coverage of it was `breakpoints.test.tsx` resizing to 375 in jsdom, which
 * lays nothing out and asserts attributes.
 *
 * **This file mounts a real `Shell`, and the sibling files do not.** They wrap
 * `ProjectView` in a bare 900px flex column, which is fine for a band whose
 * subject is a grid template. It is not fine here: the whole question below 821
 * is which element scrolls, and `.lay-surface`'s `overflow: auto` is on the
 * shell. Measured on 2026-08-14 — with the bare wrapper, claim 2's defect is
 * invisible, because the wrapper reproduces the pinned height by accident and
 * there is no surface to ask.
 *
 * The fake container is copied from the sibling rather than shared, for that
 * file's stated reason: nine ports of `vi.fn` is a cheaper duplication than a
 * harness two diverging files must agree on.
 */

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const HOLDER = SessionId('3f2a0000-0000-0000-0000-000000000000')

const COURSE = {
  projectId: ATLAS,
  projectName: 'atlas',
  holdingSessionId: HOLDER,
  preset: { id: 'hybrid.default', name: 'Hybrid', version: '1' },
  position: 1,
  stageCount: 1,
  stages: [
    {
      index: 1,
      id: 'step0.intake',
      name: 'Intake',
      kind: 'author',
      spine: 0,
      scopeLevel: 'course',
      status: 'current',
      outputs: [],
      gateDecisions: [],
      reviewerRole: null,
      findingsReport: null,
    },
  ],
  findings: [],
  unimplementedChecks: [],
}

const container = () =>
  ({
    preferences: new InMemoryPreferenceStore(),
    now: () => new Date('2026-08-10T00:00:00Z'),
    stream: { connect: vi.fn(), disconnect: vi.fn() },
    projects: { course: vi.fn().mockResolvedValue(COURSE) },
    sessions: {
      read: vi.fn().mockResolvedValue({
        id: HOLDER,
        projectId: ATLAS,
        startedAt: '2026-08-10T00:00:00Z',
        forkedFrom: null,
        forkedAt: null,
        files: [],
        messages: [],
        compactedThrough: null,
      }),
      log: vi.fn().mockResolvedValue([]),
    },
    turns: {
      current: vi.fn().mockResolvedValue({
        running: false,
        turnIndex: null,
        startedAt: null,
        elapsedSeconds: null,
      }),
      activity: vi.fn().mockResolvedValue(null),
    },
    workers: {
      on: vi.fn().mockResolvedValue({ projectId: ATLAS, workers: [], idleSessionIds: [] }),
    },
    extractions: { on: vi.fn().mockResolvedValue({ current: [], last: [] }) },
    research: { current: vi.fn().mockResolvedValue(null) },
    topics: { queue: vi.fn().mockResolvedValue([]) },
    autonomy: { read: vi.fn().mockResolvedValue(null) },
  }) as unknown as Container

const show = async () => {
  const deps = container()
  const store = createSessionStore({
    sessions: deps.sessions,
    turns: deps.turns,
    now: deps.now,
    notify: () => {},
  })
  await render(
    <ContainerProvider container={deps}>
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <StreamProvider>
          {/* `100vh` rather than a pixel height, so resizing the viewport
              resizes the shell. A fixed `900px` here was the first attempt and
              it silently detached the shell from the viewport the `60vh` cap is
              measured against — the 700x500 probe reported a 300px cap inside
              an 856px shell that had not moved. */}
          <div style={{ height: '100vh' }}>
            <Shell chrome={<span>chrome</span>}>
              <ProjectView projectId={ATLAS} selection={null} store={store} />
            </Shell>
          </div>
        </StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>,
  )
  await expect.element(page.getByRole('region', { name: 'Event log' })).toBeVisible()
  return { preferences: deps.preferences as InMemoryPreferenceStore }
}

const split = () => document.querySelector<HTMLElement>('.lay-split[data-split="project"]')!
const surface = () => document.querySelector<HTMLElement>('.lay-surface')!
const pane = (id: string) => document.querySelector<HTMLElement>(`[data-pane="${id}"]`)!
const body = (id: string) => pane(id).querySelector<HTMLElement>('.lay-pane-body')!
const box = (id: string) => pane(id).getBoundingClientRect()

// This file's `stack()` was the one of the four private helpers that already
// polled an attribute *and* geometry, and `browser-viewport.ts` keeps that
// shape — the shared helper is a superset, adding the two signals that move
// inside a band and across `--bp-wide`, neither of which this file crosses.
afterEach(restoreViewport)

/** Claim 1. Below 821 the split is a flex column and the three panes stack
 *  full-width, each starting where the one above it ended.
 *
 * **This passes against unfixed code and is a record rather than a guard.** It
 * is here because nothing had measured this band at all, so the baseline was
 * unwritten.
 *
 * `columns()` from the sibling file is deliberately not used, and must not be
 * added: below 821 the split is `display: flex`, so `gridTemplateColumns`
 * computes to `none` and `'none'.split(' ')` has length 1 — the same answer a
 * genuine one-column grid gives, which is the defect that file measures. The
 * assertions here are `flexDirection` and stacked geometry instead. */
it('stacks the three panes full-width below 821', async () => {
  await show()
  await resizeViewport(700)

  expect(getComputedStyle(split()).display).toBe('flex')
  expect(getComputedStyle(split()).flexDirection).toBe('column')

  const queue = box('queue')
  const holder = box('holder')
  const material = box('material')

  // One column: a shared left edge, and each pane the full viewport width.
  for (const b of [queue, holder, material]) {
    expect(b.left).toBe(0)
    expect(Math.round(b.width)).toBe(700)
  }

  // In order, each below the last, with no gap and no overlap.
  expect(holder.top).toBeCloseTo(queue.bottom, 0)
  expect(material.top).toBeCloseTo(holder.bottom, 0)
})

/** Claim 2. **The stacked band is page-scrolling, and until this slice it was
 *  not.** The surface has more to scroll than it shows, and every pane keeps
 *  its content's height rather than being squeezed to share one screen.
 *
 * This is the defect the slice found, and it is the same one `layout.css`
 * already records for `page` mode fifty lines above — "everything below the
 * surface is still sized to fit it … so the innermost scroller absorbs the
 * content and the surface never has anything to scroll". `page` mode was given
 * `.lay-split { flex: 0 0 auto }` for it. The `auto` mode's below-narrow half
 * got `overflow: auto` on the surface and nothing else, so it kept the bug the
 * fix above it was written for, under a comment describing behaviour it did
 * not have.
 *
 * **Measured at 700x900 before the fix**: the surface flat at 856/856 with the
 * split pinned to exactly 856; QUEUE's body 400.5px tall around 590px of
 * content, HOLDER 304.6 and MATERIAL 112.3 — three panes each shrunk below what
 * they hold so the set would fit one screen, with the outer scroller holding
 * nothing. After: the surface 1128/856, and the same three panes 578.5 / 401.4
 * / 148.0.
 *
 * **Proved red** with `flex: 0 0 auto` removed from the `.lay-split` rule in
 * the below-821 block, at 700x900:
 *
 *     AssertionError: expected 856 to be greater than 856
 *
 * The pane assertions are the half that says why it matters: a 60vh cap the
 * layout never lets a body reach is not a cap. */
it('lets the surface scroll below 821 rather than squeezing every pane', async () => {
  await show()
  await resizeViewport(700)

  const s = surface()
  expect(s.scrollHeight).toBeGreaterThan(s.clientHeight)

  // The split is taller than the screen it sits in, which is what there is to
  // scroll. Asserted as well as the surface because a surface can overflow
  // horizontally too, and that would be a different bug passing this test.
  expect(split().getBoundingClientRect().height).toBeGreaterThan(s.clientHeight)

  // And the panes are the reason: each at its content height (capped — see
  // claim 3) rather than at a share of 856. The numbers are floors well under
  // what was measured, because the heights themselves are the fixture's.
  expect(box('holder').height).toBeGreaterThan(380)
  expect(box('material').height).toBeGreaterThan(140)
})

/** Claim 3. **The unqualified 60vh cap does not clip the two `regions` panes,
 *  and why it does not is the part worth pinning.**
 *
 * The candidate defect this slice was sent to confirm: `layout.css` caps
 * `.lay-pane-body { max-height: 60vh }` with no qualifier, where the `page`
 * mode rule above it deliberately writes `:not([data-scroll='regions'])`.
 * HOLDER and MATERIAL both pass `scroll="regions"`, whose body is
 * `overflow: hidden` — and a cap on a box that cannot scroll clips content with
 * no way to reach it.
 *
 * **Refuted, by measurement.** Every region inside those bodies is
 * `flex: 1 1 0%; min-height: 0` with a scroller of its own
 * (`[data-holder-scroll='log']` and `.conv-scroll`, both `overflow: auto`), so
 * a body under the cap hands the shortfall to its regions and each scrolls what
 * it cannot show. Measured at 700x900 with HOLDER the only open pane: body
 * 362.9 against a 540 cap, its two sections 110.5 and 109.5, their scrollers
 * 87.8 each holding 88 — nothing clipped, and the composer still on screen at
 * y=388, because it sits outside both scrollers.
 *
 * QUEUE is the pane the cap actually binds on, and it is `scroll='body'`
 * (`overflow: auto`): opened alone at 700x900 its body is exactly 540.0 around
 * 590 of content.
 *
 * So the qualifier is not needed *for the panes that exist today*, and adding
 * one would be a change justified by nothing measured. What would break it is a
 * `regions` pane whose regions do not each shrink and scroll — that is the
 * condition, stated here rather than in a `:not()` because a selector cannot
 * express it.
 *
 * **Proved red** by changing the cap to `max-height: 40vh`, at 700x900:
 *
 *     AssertionError: expected '360px' to be '540px' // Object.is equality
 */
it('caps the scrolling body at 60vh and leaves what it hides reachable', async () => {
  await show()
  await resizeViewport(700)

  // Read off the computed style as well as the geometry, so a cap that changed
  // unit rather than value is visible.
  expect(getComputedStyle(body('queue')).maxHeight).toBe('540px')

  // QUEUE alone, so the cap has something to bind on: with all three open the
  // panes total more than the screen and none of them reaches 540.
  await page.getByRole('button', { name: 'Collapse Holding session' }).click()
  await page.getByRole('button', { name: 'Collapse Material' }).click()
  await expect.poll(() => body('queue').clientHeight).toBeCloseTo(540, 0)

  // Bounded, and what it cannot show is reachable by scrolling it.
  expect(body('queue').scrollHeight).toBeGreaterThan(body('queue').clientHeight)
  expect(getComputedStyle(body('queue')).overflowY).toBe('auto')
})

/** Claim 4. The `regions` panes distribute the cap rather than clipping under
 *  it — the other half of claim 3, asserted on the pane the objection is about.
 *
 * Separate from claim 3 because it goes red for a different reason: claim 3
 * fails if the cap changes, this one fails if a region inside HOLDER loses its
 * `min-height: 0` or its scroller — an edit in `ProjectView.tsx` rather than in
 * a stylesheet, which nothing else would catch.
 *
 * **This passes against unfixed code**: it pins the refutation so the next
 * reader does not re-derive it, and guards no fix. */
it('gives HOLDER’s regions their own scrollers under the cap', async () => {
  await show()
  await resizeViewport(700)

  await page.getByRole('button', { name: 'Collapse Queue' }).click()
  await page.getByRole('button', { name: 'Collapse Material' }).click()
  await expect.poll(() => box('material').height).toBeLessThan(50)

  const holderBody = body('holder')
  expect(getComputedStyle(holderBody).overflowY).toBe('hidden')
  expect(holderBody.clientHeight).toBeLessThanOrEqual(540)

  // Nothing clipped: the body shows all of itself, because its regions took the
  // shortfall.
  expect(holderBody.scrollHeight).toBeLessThanOrEqual(holderBody.clientHeight)

  // And they took it by scrolling rather than by vanishing.
  for (const sel of ['[data-holder-scroll="log"]', '.conv-scroll']) {
    const el = document.querySelector<HTMLElement>(sel)!
    expect(getComputedStyle(el).overflowY).toBe('auto')
    expect(el.clientHeight).toBeGreaterThan(0)
  }
})

/** Claim 5. A pane folded below 821 becomes a strip: a row of natural height
 *  with a level title, its meta kept and its body gone.
 *
 * **No browser test had ever exercised this collapse form.** `layout.css`'s
 * strip rules are three declarations and a comment claiming what they do, in a
 * band that had no rendered test at all — and the rail form beside them shipped
 * a defect for a whole increment on exactly that basis.
 *
 * What the comment claims and this checks: the title stays level (the rail
 * rules rotate it, and `research.css` needed a second class name to avoid
 * inheriting that), the meta is kept where a rail drops it, and the body goes
 * by the `hidden` attribute rather than by CSS.
 *
 * **A folded pane must not still reserve 60vh**, which is the specific thing
 * that would make folding useless here — measured at 38.5px against a 540px
 * cap, i.e. the header and nothing else.
 *
 * **This passes against unfixed code.** Nothing in this slice changed the strip
 * rules; the test exists so the next edit to them has something to fail. */
it('folds a pane to a level strip below 821', async () => {
  await show()
  await resizeViewport(700)

  const open = box('queue').height
  await page.getByRole('button', { name: 'Collapse Queue' }).click()
  await expect.poll(() => box('queue').height).toBeLessThan(open)

  expect(pane('queue').getAttribute('data-collapse-to')).toBe('strip')
  expect(getComputedStyle(pane('queue')).flexGrow).toBe('0')
  expect(getComputedStyle(pane('queue')).flexShrink).toBe('0')

  // The header alone, and nowhere near the 60vh a body would have taken.
  const head = pane('queue').querySelector<HTMLElement>('.lay-pane-head')!
  expect(box('queue').height).toBeCloseTo(head.getBoundingClientRect().height, 0)
  expect(box('queue').height).toBeLessThan(60)

  // Level, not rotated: the difference between this form and the rail.
  expect(getComputedStyle(head).flexDirection).toBe('row')
  const title = pane('queue').querySelector<HTMLElement>('.lay-pane-title')!
  expect(getComputedStyle(title).writingMode).toBe('horizontal-tb')

  // Meta kept — a rail drops it, a strip has room for it.
  const meta = pane('queue').querySelector<HTMLElement>('.lay-pane-meta')!
  expect(getComputedStyle(meta).display).not.toBe('none')

  // The body is gone by attribute, which `:has()` and assistive technology can
  // both see.
  expect(body('queue').hidden).toBe(true)
})

/** Claim 6. Folding all but one leaves a usable page, and the third fold is
 *  refused.
 *
 * `toggleCollapsed` (`split-tracks.ts:98`) refuses only when every pane would
 * close, and nothing had checked that below 821 — where it matters more,
 * because three stacked strips would be a page with no content on it and would
 * still look like a layout.
 *
 * **This passes against unfixed code**: the refusal is in the reducer and is
 * breakpoint-independent. */
it('refuses the fold that would close the last pane', async () => {
  await show()
  await resizeViewport(700)

  await page.getByRole('button', { name: 'Collapse Queue' }).click()
  await page.getByRole('button', { name: 'Collapse Material' }).click()
  await expect.poll(() => body('material').hidden).toBe(true)

  await page.getByRole('button', { name: 'Collapse Holding session' }).click()

  // Still open, and still showing its regions. Polled rather than asserted
  // immediately: an accepted fold would take a frame, and an assertion running
  // before it would pass for the wrong reason.
  await expect.poll(() => body('holder').hidden).toBe(false)
  expect(box('holder').height).toBeGreaterThan(300)
})

/** Claim 7. Nothing paints outside a box that clips it, down to 561px — the
 *  bottom of the band this slice treats as worth supporting.
 *
 * The definition is the previous slice's: an element whose `scrollWidth`
 * exceeds its `clientWidth`, with `overflow-x: visible` so there is no scroller
 * to reach the remainder and no `text-overflow: ellipsis` to say it was cut.
 *
 * **Below 561 there are two, and both are recorded rather than fixed**, per the
 * slice's scoping rule — one user, one machine, and neither width is a window
 * anyone would put a research console in.
 *
 * - **MATERIAL's five-tab strip needs 351px** and `.tabs` has no `flex-wrap`
 *   (`workspace.css:130-133`). It fits exactly at 351 and clips from **350px of
 *   viewport downwards** — measured 351/350 at a 350px viewport. The survey
 *   predicted 351 and was right. Not fixed: `.tabs` is `Choices` and `TabList`
 *   both, used across the console, so `flex-wrap: wrap` there changes every tab
 *   row at every width — cheap to type, not cheap to justify from one
 *   measurement in one view.
 * - **QUEUE's seeding form needs 317px** in a box that is the viewport less
 *   27px of padding, so it clips from **343px downwards** — `PROJECT_TRACKS`'
 *   measured 344 floor showing up again, as a viewport width this time rather
 *   than a track width.
 *
 * **Proved red** by running the same sweep at 350 instead of 561:
 *
 *     AssertionError: at 350px: expected [ Array(2) ] to have a length of +0
 *     but got 2
 *
 * — the two being `.tabs` and the utility-classed column around it, both
 * reporting `scrollWidth` 351 against a `clientWidth` of 350.
 */
it('clips nothing down to 561', async () => {
  await show()

  for (const width of [820, 700, 640, 561]) {
    await resizeViewport(width)

    const clipped = Array.from(document.querySelectorAll<HTMLElement>('.lay-split *'))
      .filter((el) => el.clientWidth > 0 && el.scrollWidth > el.clientWidth)
      .filter((el) => {
        const cs = getComputedStyle(el)
        return cs.overflowX === 'visible' && cs.textOverflow !== 'ellipsis'
      })
      .map((el) => el.className || el.tagName)

    expect(clipped, `at ${String(width)}px`).toHaveLength(0)
  }
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { useEffect, useState } from 'react'
import { expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { OverlayHost } from '@presentation/layout/OverlayHost.tsx'
import { StreamProvider } from '@presentation/shell/StreamProvider.tsx'

import type { SessionStore } from '@application/session/session-store.ts'
import { parseRoute, type Selection } from '@presentation/routing/routes.ts'

import { ProjectView } from './ProjectView.tsx'

/** That HOLDER's stacked column lays out — which is every claim slice 2 makes,
 *  and jsdom can judge none of them.
 *
 * Slice 0 wrote this file to check that a `Split` inside a `Split` laid out.
 * Slice 2 removes that nesting, so the claims changed with it: HOLDER is now a
 * scrub bar, two self-scrolling sections and a pinned composer in one flex
 * column, and "which box owns the overflow" is the entire design. Every one of
 * those is a computed style or a rectangle. `vitest.setup.ts` pins
 * `offsetWidth`/`offsetHeight` to constants and answers `false` to every media
 * query, so the jsdom suite reports the same numbers whatever the markup does.
 *
 * **This mounts the real `ProjectView`, not a harness of `Split` and `Pane`.**
 * `SessionView.test.tsx` records why, and its reasoning transfers exactly: the
 * defects here are one prop on one pane and a handful of utilities on three
 * boxes, and a harness that composed them correctly would assert the harness.
 * The cost is a fake container of nine ports, which is the largest setup in
 * this directory and is the reason the gap existed.
 *
 * The viewport is 1440x900 and is set in `vite.config.ts`, not by anything
 * here: every assertion below is above `--bp-wide`, which is the only band in
 * which a `Split` writes a template at all.
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

/** Only the ports this page and its store reach for. A fake that implemented
 *  the whole container would hide which dependencies the page really has, and
 *  the list below is itself informative: the project page touches nine. */
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

/** `ProjectView` with the one thing the route would otherwise supply: a
 *  `selection` that changes when the page asks it to.
 *
 * This file rendered `selection={null}` fixed until the tab claim below needed
 * one to move, and the difference is not cosmetic — the material tabs are
 * derived from the route rather than held in state, so a static `selection`
 * makes every tab click a no-op that still *looks* like a working page. The
 * first version of claim 7 passed a click to Artifacts and asserted against a
 * panel that had never changed.
 *
 * Reading `navigate` back out of the address bar would be the faithful thing
 * and is not worth it here: the address bar is global to the run, and
 * `App.test.tsx` already covers the route round trip in jsdom. What this needs
 * is only that choosing a tab reaches the component. */
const Routed = ({ store }: { store: SessionStore }) => {
  const [selection, setSelection] = useState<Selection | null>(null)
  useEffect(() => {
    const onHash = () => {
      setSelection(parseRoute(window.location.hash).name === 'project' ? readSelection() : null)
    }
    window.addEventListener('hashchange', onHash)
    return () => {
      window.removeEventListener('hashchange', onHash)
    }
  }, [])
  return <ProjectView projectId={ATLAS} selection={selection} store={store} />
}

/** The project selection the address bar currently names, or null. */
const readSelection = (): Selection | null => {
  const route = parseRoute(window.location.hash)
  return route.name === 'project' ? route.selection : null
}

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
          {/* A real height, because every claim here is about how height
              travels down the nesting and a page that sizes to its content
              would make all of them vacuous. */}
          <OverlayHost>
            <div style={{ height: '900px', display: 'flex', flexDirection: 'column' }}>
              <Routed store={store} />
            </div>
          </OverlayHost>
        </StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>,
  )

  // HOLDER's sections only exist once the course resolves and names a holding
  // session, so every test waits on one of them. `Event log` is now a
  // `<section aria-label>` rather than a `Pane`, and it is the same role and
  // the same name — which is the point of labelling them by hand.
  await expect.element(page.getByRole('region', { name: 'Event log' })).toBeVisible()

  return { preferences: deps.preferences as InMemoryPreferenceStore }
}

const outerSplit = () => document.querySelector<HTMLElement>('.lay-split[data-split="project"]')!

/** The holding session's body, and the three boxes stacked in it.
 *
 * MATERIAL's pane body rather than HOLDER's: the holding session is MATERIAL's
 * first tab now and HOLDER is not a pane. The three boxes inside are the same
 * three, unchanged — which is what makes these claims still worth asserting
 * rather than rewriting. */
const holder = () => {
  const body = document.querySelector<HTMLElement>('[data-pane="material"] .lay-pane-body')!
  return {
    body,
    log: body.querySelector<HTMLElement>('[aria-label="Event log"]')!,
    conversation: body.querySelector<HTMLElement>('[aria-label="Conversation"]')!,
    composer: body.querySelector<HTMLElement>('.composer')!,
  }
}

/** Claim 1. HOLDER is one column of scrollers, and the column itself is not one.
 *
 * The whole shape of the region in one test: the pane body does not scroll, the
 * two sections inside it do, and neither is allowed to be the box that owns the
 * page's overflow. Slice 0's version of this claim was about a nested `Split`
 * taking the height; the boxes changed, the failure mode did not — a page that
 * scrolls in the wrong box.
 *
 * **Proved red**, twice, because the claim has two halves and one inversion
 * only breaks one:
 *
 * - Changing HOLDER's `Pane` from `scroll="regions"` to the default fails at
 *   `expected 'block' to be 'flex'` (`layout.css:234` is what makes the body a
 *   flex column, and a block box is not one, so `flex-1` on the two sections
 *   below means nothing and both run to their content's height).
 * - Dropping `overflow-auto` from the log's scroll box in `ProjectView.tsx`
 *   fails at `expected 'visible' to be 'auto'`. That inversion leaves the first
 *   pair green, which is why they are separate assertions.
 */
it('stacks HOLDER as scrollers inside a column that does not scroll', async () => {
  await show()
  const { body, log, conversation } = holder()

  // The pane body is a flex column and not a scroller. `scroll="regions"` is
  // what makes that true and it is the prop this half guards.
  //
  // **Not** `scrollHeight <= clientHeight`, which is what this asserted first
  // and which stayed green under the inversion. With `regions` dropped, this
  // fixture's empty log and empty transcript do not fill 900px, so the body
  // has nothing to overflow with and a body that *is* a scroller measures
  // identically to one that is not — slice 1 threw away an assertion for
  // exactly this reason and recorded it, and the lesson did not transfer until
  // it happened again here. The declarations are read back from the browser's
  // own cascade instead, which jsdom answers `''` to whatever the markup says.
  const bodyStyle = getComputedStyle(body)
  expect(bodyStyle.display).toBe('flex')
  expect(bodyStyle.overflowY).toBe('hidden')

  // The log's own scroll box — the element `overflow-auto` is on, which is a
  // wrapper rather than `.timeline` itself, because `timeline.css:4` gives
  // `.timeline` no overflow at all and on `#/s/` the pane body scrolls it.
  //
  // Found by `data-holder-scroll` rather than by `.timeline`'s parent, which
  // was the first attempt and threw: this fixture's log is empty, so `Timeline`
  // renders an `EmptyState` and there is no `.timeline` element to walk up
  // from. An attribute that exists whether or not there is anything to scroll
  // is the difference between a test about the arrangement and one about the
  // data.
  const logScroller = log.querySelector<HTMLElement>('[data-holder-scroll="log"]')!
  expect(getComputedStyle(logScroller).overflowY).toBe('auto')
  // The transcript's is `.conv-scroll`, which `Conversation` renders and holds
  // a ref on to stick to the bottom — so this asserts the box it already had
  // still gets a height here rather than that a new one was added.
  const convScroller = conversation.querySelector<HTMLElement>('.conv-scroll')!
  expect(getComputedStyle(convScroller).overflowY).toBe('auto')
  expect(convScroller.getBoundingClientRect().height).toBeGreaterThan(0)
})

/** Claim 2. The two sections share the leftover height, and the composer is
 *  pinned to the bottom of the region.
 *
 * The brief's requirement, measured: the timeline and the conversation split
 * what the scrub bar and the composer leave, and the composer's bottom edge
 * lands on HOLDER's. Sharing is asserted as "within 40px of each other" rather
 * than as equality — both are `flex-1` against the same basis, but they hold
 * different chrome (the log has an activity feed pinned under it) and an exact
 * comparison would be asserting the feed's height.
 *
 * **Proved red**: replacing the conversation section's `flex-1` with `shrink-0`
 * fails the share at `expected 491.140625 to be less than 40` — one section eats
 * the region and the other becomes a caption. The composer half of the claim
 * survives that inversion (it is still last and still pinned), so it is proved
 * red separately: adding a second `Split` inside HOLDER fails it at
 * `expected 637.9375 to be greater than 898`, the nesting this slice removes
 * pushing the composer up off the region's floor.
 *
 * *(Slice 0's claim 2 — two grid templates on two `.lay-split` elements, neither
 * overwriting the other — is **deleted rather than rewritten**. There is one
 * split on this page now, so the claim has no subject: the mechanism it ruled
 * out cannot occur. Claim 4 asserts the count that makes that true. Deleting a
 * test that no longer describes the product is the right move and this note is
 * the record of it; leaving it green against a single split would have been a
 * test that reports on nothing.)*
 */
it('shares HOLDER’s leftover height and pins the composer to its bottom', async () => {
  await show()
  const { body, log, conversation, composer } = holder()

  const logBox = log.getBoundingClientRect()
  const convBox = conversation.getBoundingClientRect()
  const bodyBox = body.getBoundingClientRect()

  expect(logBox.height).toBeGreaterThan(0)
  expect(convBox.height).toBeGreaterThan(0)
  expect(Math.abs(logBox.height - convBox.height)).toBeLessThan(40)

  // Pinned, not floating: the composer's bottom edge is the region's. A
  // composer inside either scroller would leave the screen as the transcript
  // grew, which is the defect `Pane`'s `footer` slot exists for and which this
  // arrangement has to reproduce without a `Pane`.
  const composerBox = composer.getBoundingClientRect()
  expect(composerBox.bottom).toBeGreaterThan(bodyBox.bottom - 2)
  expect(composerBox.bottom).toBeLessThanOrEqual(bodyBox.bottom + 1)
  // And it is below both scrollers rather than between them.
  expect(composerBox.top).toBeGreaterThanOrEqual(convBox.bottom - 1)
})

/** Claim 3. Folding a region still folds one region, and remembers it.
 *
 * Slice 0's version of this was about crosstalk between two splits and two
 * preference groups. There is one split now, so what is left is the half that
 * still has a subject: the fold works, lands in the `project` key, and the
 * `session` key — which survives for the standalone `#/s/` route — is not
 * written by this page at all.
 *
 * **Proved red**: pointing `use-project-panes.ts`'s `GROUP` at `'session'`
 * fails at `expected [] to deeply equal [ 'queue' ]` — the `project` key is the
 * assertion that fires first, and it is empty because both writes went to
 * `session`. That is the
 * assertion worth keeping past the un-nesting: the standalone route's stored
 * layout is still a separate thing, and the project page writing into it would
 * silently reinterpret somebody's session panes as regions.
 */
it('folds a region, remembers it under `project`, and leaves `session` alone', async () => {
  const { preferences } = await show()
  const outer = outerSplit()

  await page.getByRole('button', { name: 'Collapse Queue' }).click()

  expect(outer.querySelector('[data-pane="queue"]')!.className).toContain('is-collapsed')
  expect(outer.querySelector('[data-pane="material"]')!.className).not.toContain('is-collapsed')

  expect(preferences.collapsedPanes('project')).toEqual(['queue'])
  expect(preferences.collapsedPanes('session')).toEqual([])
})

/** Claim 5. One split on the page, which is what "HOLDER is not a screen" means
 *  structurally.
 *
 * The cheapest possible statement of this slice's headline, and the one that
 * fails first if anybody re-mounts `SessionView` inside a region. Counted over
 * the document rather than asserted as "no `[data-split='session']`", because
 * the failure to catch is *a* nested split and not that particular one.
 *
 * **Proved red**: rendering a second `Split` inside the HOLDER pane fails at
 * `expected …(2) to have a length of 1 but got 2`.
 */
it('leaves exactly one split on the project page', async () => {
  await show()
  expect(document.querySelectorAll('.lay-split')).toHaveLength(1)
  expect(document.querySelector('.lay-split')!.getAttribute('data-split')).toBe('project')
})

/** Claim 4. The queue header keeps its height, and the queue scrolls past it.
 *
 * `QueueHeader`'s docstring makes exactly this claim -- "not a scroller", so
 * that the pane body below it stays the one scroller -- and it is the reason
 * slice 0's four loose panels needed re-parenting at all: parked directly in
 * the pane, the run panel scrolled away with the stage list under it. Which box
 * owns the overflow is not something jsdom holds an opinion about, so this is
 * asserted here or it is asserted nowhere.
 *
 * **The obvious assertion does not work, and the failure is worth recording.**
 * This first asserted `header.scrollHeight <= clientHeight` — "nothing is
 * clipped" — and adding `flex-1 overflow-auto` to the header did not fail it.
 * The fixture's one stage and four small panels do not fill 900px, so a header
 * that *is* a scroller has nothing to scroll and measures identically to one
 * that is not. A test that only fires when the data happens to be tall is a
 * test that reports on the fixture.
 *
 * So the claim is asserted as the two declarations that make it true, read back
 * from the browser's own cascade. That is not a restatement of the class list:
 * `overflow-y` and `flex-grow` are computed from Tailwind utilities through
 * `@layer utilities`, and jsdom's `getComputedStyle` returns only what an
 * inline style said — it answers `''` for both, and would pass whatever the
 * header were dressed in.
 *
 * **Proved red**: `flex-1 overflow-auto` on the header fails at
 * `expected "auto" to be "visible"`.
 */
it('keeps the queue header out of the queue pane’s scroller', async () => {
  await show()
  const header = document.querySelector<HTMLElement>('[data-region-header="queue"]')!
  const body = header.closest('.lay-pane-body')!

  expect(header.getBoundingClientRect().height).toBeGreaterThan(0)
  // In QUEUE and not merely somewhere that happens to render: which pane owns
  // these controls is the whole of the re-parenting.
  expect(body.closest('[data-pane]')!.getAttribute('data-pane')).toBe('queue')

  const style = getComputedStyle(header)
  // Not a scroller: the pane body below keeps the overflow.
  expect(style.overflowY).toBe('visible')
  // And it does not take the leftover height, which is the other half of the
  // same claim — a header that grows leaves the queue nothing to scroll in.
  expect(style.flexGrow).toBe('0')
})

/** Claim 7. The holding session survives a trip to another tab: a half-typed
 *  message is still there, and the transcript still has its height.
 *
 * **The defect this closes shipped for one commit.** `Tabs` unmounts the panel
 * that is not shown, which is right for panels that fetch — it is why
 * `activationMode` is manual — and wrong for the one panel that is a *session*.
 * The holding session was a permanent column until it became a tab, so nothing
 * had ever taken its state away; the move made a tab-away discard a draft
 * message and a scrub position, which is a data loss a reader would meet by
 * checking the Artifacts tab mid-sentence.
 *
 * **The second assertion is the one that is not obvious, and it is the reason
 * this is a browser test.** `Pane`'s `unmountWhenCollapsed` documents the trap
 * being walked into deliberately here: a virtualizer inside a hidden-but-mounted
 * box measures a zero-height scroll container and caches that, so the box comes
 * back empty. `forceMount` keeps the panel in the tree with `hidden` on it,
 * which is `display: none` — every measurement inside is zero while it is away.
 * So "the draft survived" is not enough; the transcript has to have laid itself
 * out again on the way back, and jsdom cannot see the difference.
 *
 * **Proved red** by removing `keepMounted` from the session panel: the first
 * assertion fails at `expected '' to be 'half a thought'`, the panel having been
 * unmounted and remounted with a fresh composer.
 */
it('keeps a half-typed message and the transcript across a tab switch', async () => {
  await show()

  const composer = document.querySelector<HTMLTextAreaElement>('.composer textarea')!
  await page.getByRole('textbox', { name: /Send a turn/i }).fill('half a thought')
  expect(composer.value).toBe('half a thought')

  const before = holder().conversation.getBoundingClientRect().height
  expect(before).toBeGreaterThan(0)

  // Asserted on the tab rather than on the panel, deliberately: the panel is
  // absent under the defect and merely hidden under the fix, so a check on it
  // would read differently for two reasons at once and could not say which.
  // What both agree on is that the reader left.
  await page.getByRole('tab', { name: 'Artifacts' }).click()
  await expect
    .poll(() => page.getByRole('tab', { name: 'Artifacts' }).element().ariaSelected)
    .toBe('true')

  await page.getByRole('tab', { name: 'Holding session' }).click()
  await expect
    .poll(() => document.querySelector<HTMLTextAreaElement>('.composer textarea')?.value)
    .toBe('half a thought')

  // Laid out again, not merely present. A cached zero from the hidden pass
  // would satisfy every assertion above this one.
  expect(holder().conversation.getBoundingClientRect().height).toBeCloseTo(before, 0)
})

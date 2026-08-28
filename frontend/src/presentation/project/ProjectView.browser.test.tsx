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

/** That the project page's frame lays out: one split, foldable, remembered.
 *
 * **Four of this file's six claims are deleted rather than rewritten**, and
 * that is the honest move rather than a loss of coverage. Claims 1, 2, 7 and 8
 * measured the holding session's stacked column -- which box owned the
 * overflow, how the two sections shared the leftover height, that a half-typed
 * message survived a tab switch, and that `keepMounted` did not leave a
 * `flex-1` sibling in the layout. That panel is gone: a person does not pick
 * which session to read a project through, and the transcript lives at the
 * session route. A rewritten version of any of them would be a test invented
 * to keep a number in this file, which is what the note under claim 4 already
 * says about claim 4.
 *
 * What survives is what was never about the panel. Both remaining claims are
 * still a computed style or a rectangle, which is why they are here rather
 * than in the jsdom suite: `vitest.setup.ts` pins `offsetWidth`/`offsetHeight`
 * to constants and answers `false` to every media query, so the jsdom suite
 * reports the same numbers whatever the markup does.
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

/** Only the ports this page and its store reach for. A fake that implemented
 *  the whole container would hide which dependencies the page really has, and
 *  the list below is itself informative: the project page touches nine. */
const container = () =>
  ({
    preferences: new InMemoryPreferenceStore(),
    now: () => new Date('2026-08-10T00:00:00Z'),
    stream: { connect: vi.fn(), disconnect: vi.fn() },
    projects: {
      // The page's identity and holder come from here now rather than from the
      // course. Omitting it does not fail the type -- the container is cast --
      // it leaves the header with no holding session and the Workspace tab
      // hidden, which is a layout difference these files measure.
      project: vi.fn().mockResolvedValue({
        id: ATLAS,
        name: 'atlas',
        activeSessionId: HOLDER,
        tipAtEvent: 0,
        // The Workspace tab is gated on this rather than on the holder now.
        // Equal to the holder here, which is what a held project reports.
        readingHeadSessionId: HOLDER,
      }),
    },
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
    topics: { list: vi.fn().mockResolvedValue([]) },
    autonomy: { read: vi.fn().mockResolvedValue(null) },
  }) as unknown as Container

/** `ProjectView` with the one thing the route would otherwise supply: a
 *  `selection` that changes when the page asks it to.
 *
 * This file rendered `selection={null}` fixed until the tab claim below needed
 * one to move, and the difference is not cosmetic — the material tabs are
 * derived from the route rather than held in state, so a static `selection`
 * makes every tab click a no-op that still *looks* like a working page. The
 * first version of claim 7 passed a click to another tab and asserted against a
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

  // The default tab, which is the catalog, and no click at all. This helper
  // used to open "Holding session" explicitly because every claim in the file
  // was about how height travelled through that panel's boxes. Those claims
  // are gone with the panel; what is left is the split and the fold, which are
  // the page's own frame and are drawn on whatever tab is open.
  await expect.element(page.getByRole('tab', { name: 'Curriculum' })).toBeVisible()

  return { preferences: deps.preferences as InMemoryPreferenceStore }
}

const outerSplit = () => document.querySelector<HTMLElement>('.lay-split[data-split="project"]')!

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

/** Claim 4 stood here and is deleted with the thing it measured.
 *
 * It asserted that `[data-region-header="queue"]` was not a scroller and did
 * not grow -- "the queue header keeps its height, and the queue scrolls past
 * it". There is no such element. The four stacked bands it was about are gone:
 * the run panel is deleted, seeding is behind a drawer, and the two ask links
 * are icons on the queue's own search line, which `TopicQueue` draws inside
 * the scroller by design. Nothing in the pane is above the scroller any more,
 * so the claim has no subject rather than a new spelling, and a rewritten
 * version of it would be a test invented to keep a number in this file.
 *
 * `QueueHeader.tsx` and `docs/design/topic-actions-on-the-row.md` §1 carry the
 * argument for the removal; `TopicQueue.browser.test.tsx` is where the
 * toolbar's own geometry is now measured.
 */

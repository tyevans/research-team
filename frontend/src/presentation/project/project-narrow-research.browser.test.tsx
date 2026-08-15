import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { afterEach, expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import { ProjectId, SessionId, SourceId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { Shell } from '@presentation/layout/Shell.tsx'
import type { Selection } from '@presentation/routing/routes.ts'
import { StreamProvider } from '@presentation/shell/StreamProvider.tsx'

import { resizeViewport, restoreViewport } from '../../test/browser-viewport.ts'
import { ProjectView } from './ProjectView.tsx'

/** The two questions `BACKLOG.md` B62 and B63 left open, both of which are a
 *  measurement in a real browser and nothing else.
 *
 * **B62 — which width wins on the drawer below 820.** `Drawer.tsx:164` sets the
 * panel three ways in Tailwind utilities (`w-[42vw] max-w-[640px]
 * min-w-[360px]`) while `responsive.css:256-260` sets
 * `.drawer { width: 100%; max-width: none; min-width: 0 }` below 820px. Both
 * selectors are 0-1-0, so specificity does not decide it and neither does
 * source order — `theme.css:85` imports Tailwind's utilities as
 * `layer(utilities)` and `responsive.css` carries no `@layer`, which makes the
 * comparison unlayered-against-layered. B62 *reasoned* from that that the
 * stylesheet wins. Claim 1 measures it, because this project has shipped a
 * defect off exactly that substitution once (`CLAUDE.md`, the inward focus
 * ring) and the losing outcome is the ugly one: a 360px strip pinned to the
 * right of an 819px screen, a narrower panel on a narrower viewport.
 *
 * **B63 — what MATERIAL does below 821 with *research* content in it.** B63's
 * premise was that the research view is a third view mounting a `Split`,
 * unmeasured below 821. It is not: `<Split` appears in exactly two view files
 * (`ProjectView.tsx:277` and `SessionView.tsx:122`; the other matches are the
 * primitive itself, stories and unit tests), because the route merge folded
 * research into MATERIAL's `doc` and `entity` tabs. So the shared
 * `.lay-split { flex: 0 0 auto }` fix that slice landed reaches this content
 * through the project split that `project-stacked.browser.test.tsx` already
 * measures. What was *genuinely* unmeasured is narrower and is claim 2: whether
 * MATERIAL holding a virtualized document list behaves like MATERIAL holding
 * the artifact list the stacked fixture leaves selected. A virtualizer owns its
 * own scroll container, which is the one thing in this pane that could plausibly
 * absorb the page scroll the below-821 rule exists to create.
 *
 * **The fixture is `project-stacked`'s, deliberately copied rather than
 * shared** — a real `Shell` inside `height: 100vh`, for that file's stated
 * reason: below 821 the question is which element scrolls, `.lay-surface`'s
 * `overflow: auto` is on the shell, and a fixed pixel height detaches the shell
 * from the viewport `60vh` is measured against. The container is the ninth-port
 * `vi.fn` block that file argues is a cheaper duplication than a harness two
 * diverging files must agree on, plus `documents`, which is this file's subject.
 */

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const HOLDER = SessionId('3f2a0000-0000-0000-0000-000000000000')
const SOURCE = SourceId('9c0e0000-0000-0000-0000-000000000000')

const COURSE = {
  projectId: ATLAS,
  projectName: 'atlas',
  holdingSessionId: HOLDER,
  preset: { id: 'hybrid.default', name: 'Hybrid', version: '1' },
  position: 1,
  stageCount: 1,
  stages: [],
  findings: [],
  unimplementedChecks: [],
}

/** Enough rows that the list is taller than the pane can show, so the
 *  virtualizer is actually virtualizing rather than rendering a short list into
 *  a box with room to spare. A list that fits proves nothing about a scroller
 *  competing with the page. */
const DOCUMENTS = Array.from({ length: 40 }, (_, index) => ({
  sourceId: SourceId(`0000${String(index).padStart(4, '0')}-0000-0000-0000-000000000000`),
  charCount: 4000,
  sha256: 'a'.repeat(64),
  uri: `https://example.invalid/${String(index)}`,
  title: `Source ${String(index)}`,
  publishedAt: null,
  note: null,
  droppedReason: null,
}))

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
    documents: {
      list: vi.fn().mockResolvedValue([
        {
          sourceId: SOURCE,
          charCount: 12000,
          sha256: 'b'.repeat(64),
          uri: 'https://example.invalid/opened',
          title: 'The opened source',
          publishedAt: null,
          note: null,
          droppedReason: null,
        },
        ...DOCUMENTS,
      ]),
      read: vi.fn().mockResolvedValue({
        sourceId: SOURCE,
        charCount: 12000,
        sha256: 'b'.repeat(64),
        uri: 'https://example.invalid/opened',
        title: 'The opened source',
        publishedAt: null,
        note: null,
        droppedReason: null,
        // Long enough that the reader has something to scroll; the drawer's
        // *width* is the subject and its content only has to be real.
        text: 'A paragraph of the source. '.repeat(400),
        start: 0,
        end: 12000,
      }),
    },
  }) as unknown as Container

const show = async (selection: Selection | null) => {
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
          <div style={{ height: '100vh' }}>
            <Shell chrome={<span>chrome</span>}>
              <ProjectView projectId={ATLAS} selection={selection} store={store} />
            </Shell>
          </div>
        </StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>,
  )
  // What "mounted" means differs between the two claims, and not for a
  // cosmetic reason. With the reader open the whole page behind it is `inert`,
  // so the tab strip — the sibling files' readiness signal — is never *visible*
  // to a locator and the wait times out against a page that rendered
  // correctly. The drawer is the readiness signal in that case.
  await expect
    .element(
      selection?.facet === 'doc' && selection.id !== null
        ? page.getByRole('dialog', { name: /^Reading /u })
        : page.getByRole('tablist', { name: 'Material' }),
    )
    .toBeVisible()
}

const surface = () => document.querySelector<HTMLElement>('.lay-surface')!
const split = () => document.querySelector<HTMLElement>('.lay-split[data-split="project"]')!
const pane = (id: string) => document.querySelector<HTMLElement>(`[data-pane="${id}"]`)!
const box = (id: string) => pane(id).getBoundingClientRect()
const drawer = () => document.querySelector<HTMLElement>('aside.drawer')!

afterEach(restoreViewport)

/** Claim 1 — **B62, measured.** Below 820 the drawer is the full viewport
 *  width, and the three Tailwind width utilities on the same element lose.
 *
 * **The prediction held.** Measured in Chromium on 2026-08-14 at 800x900, with
 * the document reader open on the project page:
 *
 *     drawer left 0, right 800, width 800   (viewport 800)
 *     computed width 800px, max-width none, min-width 0px
 *
 * The losing outcome is not hypothetical and was reproduced (see the red proof
 * below): with the stylesheet's rule out of the way the panel is **360px** —
 * `min-w-[360px]` beating `w-[42vw]`'s 336 — pinned to the right of an 800px
 * screen. It is not what ships, because `responsive.css` is unlayered and
 * Tailwind's utilities are in `@layer utilities`, and an unlayered normal
 * declaration beats a layered one regardless of specificity.
 *
 * **This claim would pass against unfixed code, and it is still worth having.**
 * There is no fix here — the entry was a question, and this is its answer. What
 * the claim guards is the *next* edit: the three computed longhands are asserted
 * alongside the box, so moving `.drawer` into a `@layer`, deleting it from
 * `responsive.css`, or adding a `!` to the utilities each turns one of these
 * lines red with the actual number. **Proved red** by renaming `.drawer` to
 * `.drawer-DISABLED` in `responsive.css`'s below-820 block, which is the
 * cheapest way to ask "what if the stylesheet lost":
 *
 *     AssertionError: expected 360 to be 800
 *
 * — B62's second outcome, reproduced on demand, and the number this claim
 * exists to keep from coming back.
 *
 * Read at 800 rather than at 819 because 800x900 is what B62 names and because
 * the boundary itself (`max-width: 820px`) is a different claim than this one;
 * a test at 819 would be measuring the media query's edge rather than which
 * rule wins inside it.
 */
it('gives the drawer the whole viewport below 820, so the utilities lose', async () => {
  await show({ facet: 'doc', id: SOURCE })
  await resizeViewport(800)

  const panel = drawer()
  const geometry = panel.getBoundingClientRect()
  expect(Math.round(geometry.width)).toBe(800)
  expect(Math.round(geometry.left)).toBe(0)
  expect(Math.round(geometry.right)).toBe(800)

  // The longhands, because the box alone cannot say *why* it is 800: a
  // `max-w-[640px]` that had won would also be invisible at some widths, and
  // `min-w-[360px]` is the one that produces the inverted panel.
  const style = getComputedStyle(panel)
  expect(style.width).toBe('800px')
  expect(style.maxWidth).toBe('none')
  expect(style.minWidth).toBe('0px')
})

/** Claim 2 — **B63, restated as what was actually open.** MATERIAL holding the
 *  research corpus below 821 stacks and page-scrolls exactly as MATERIAL
 *  holding the artifact list does.
 *
 * The premise B63 was filed on is wrong and the correction is in `BACKLOG.md`:
 * there is no third `Split`. What survived the correction is that
 * `project-stacked.browser.test.tsx` measures this band with `selection={null}`,
 * which leaves MATERIAL on the `artifact` tab — a plain `overflow-auto` panel.
 * The `doc` tab is not: `DocumentList` renders a **virtualizer**, which owns a
 * scroll container of its own, and `ProjectView.tsx:499` deliberately gives that
 * panel no `overflow-auto` for that reason. An inner scroller that takes the
 * height it is offered is precisely how a page-scrolling layout loses its scroll
 * — it is the same shape as the defect the below-821 rule was written for, one
 * level further in.
 *
 * **Measured on 2026-08-14 at 700x900, and it does not happen.** With the
 * corpus in MATERIAL the surface is **1558** against a client height of 856,
 * the split 1558.36, and the panes 578.5 / 401.4 / 578.5 full width in one
 * column.
 *
 * **Note which numbers match the sibling and which do not, because the
 * difference is the finding.** `project-stacked` claim 2 records 1128/856 with
 * QUEUE 578.5 / HOLDER 401.4 / MATERIAL 148.0. QUEUE and HOLDER are identical
 * here — same fixture, same content — and MATERIAL is 578.5 rather than 148,
 * which is the corpus taking its content's height where the empty artifact list
 * took its head's. The 430px difference is the whole of the 1558-vs-1128 gap.
 * So the *behaviour* is the same and the *number* is not, and a claim asserting
 * 1128 here would have been asserting the sibling's fixture rather than this
 * one's.
 *
 * **This claim passes against today's code and would have passed before the
 * below-821 fix only if that fix were reverted for both tabs at once**, which
 * is what makes it worth keeping rather than a duplicate of its sibling: it
 * pins the *equality*. Proved red with `flex: 0 0 auto` removed from the
 * `.lay-split` rule in `layout.css`'s below-821 block, at 700x900:
 *
 *     AssertionError: expected 856 to be greater than 856
 *
 * — byte-identical to the sibling file's recorded failure, which is the point:
 * research content is not a separate surface with a separate answer.
 */
it('page-scrolls below 821 with the research corpus in MATERIAL, as with artifacts', async () => {
  await show({ facet: 'doc', id: null })
  await resizeViewport(700)

  await expect.element(page.getByRole('tab', { name: 'Documents', selected: true })).toBeVisible()

  const s = surface()
  expect(s.scrollHeight).toBeGreaterThan(s.clientHeight)
  expect(split().getBoundingClientRect().height).toBeGreaterThan(s.clientHeight)

  // One column, full width, in order — the same shape the artifact tab has.
  const queue = box('queue')
  const material = box('material')
  for (const b of [queue, material]) {
    expect(b.left).toBe(0)
    expect(Math.round(b.width)).toBe(700)
  }
  expect(material.top).toBeCloseTo(queue.bottom, 0)

  // And MATERIAL is not flattened to its head: the virtualizer's scroller has
  // room. A zero-height list inside a stacked pane is what "the inner scroller
  // absorbed it" would look like, and it would satisfy every line above. The
  // floor is well under the measured 578.5 because the height is the fixture's
  // forty rows; what is being claimed is that it is not the sibling's 148.
  expect(material.height).toBeGreaterThan(400)
})

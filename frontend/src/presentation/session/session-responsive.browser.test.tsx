import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import { afterEach, expect, it, vi } from 'vitest'

import { createSessionStore } from '@application/session/session-store.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Container } from '@app/container.ts'
import type { Message } from '@domain/conversation/message.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionId } from '@domain/shared/identifier.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'
import { OverlayHost } from '@presentation/layout/OverlayHost.tsx'
import { Shell } from '@presentation/layout/Shell.tsx'
import { StreamProvider } from '@presentation/shell/StreamProvider.tsx'

import { SessionView } from './SessionView.tsx'

/** What the session page does below `--bp-wide`, in both of the two bands under
 *  it, neither of which anything had ever rendered.
 *
 * `SessionView.test.tsx` mounts the same view in jsdom and says in its own
 * docstring that it constrains nothing about layout — the media stub answers
 * `false` to everything, so the split renders in its below-the-breakpoint state
 * and no geometry exists. This is the browser half, and it is the first file to
 * put the session view in front of a layout engine at any width.
 *
 * It covers two bands and says which is which at every claim, because the
 * rules that apply are disjoint: 821-1180 is `responsive.css`'s
 * `[data-split='session']` block (a grid, two columns, the conversation
 * wrapped), and below 821 is `layout.css`'s flex column, where none of those
 * rules apply at all.
 *
 * **The fixture mounts a real `Shell` and gives the session real messages**,
 * and both are load-bearing rather than incidental. The `.lay-surface`
 * `overflow: auto` that claim 3 is about lives on the shell, so a bare wrapper
 * has nothing to ask; and a session with an empty transcript is shorter than
 * the screen at every width, which makes "the surface scrolls" unmeasurable in
 * the direction that matters. Measured on 2026-08-14 with the empty fixture:
 * surface 856/856 at 700px — flat, and flat for the boring reason.
 *
 * The container is the sibling files' shape: only the ports this view reaches
 * for, faked, rather than a shared harness two diverging files must agree on.
 */

const SESSION = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee' as SessionId

/** Enough transcript to be taller than any viewport this file uses. The count
 *  is arbitrary above the point where the conversation exceeds 900px; 40 is
 *  well past it and cheap. */
const MESSAGES: Message[] = Array.from({ length: 40 }, (_, i) => ({
  role: i % 2 === 0 ? 'user' : 'assistant',
  content: `turn ${String(i)} — a line of transcript long enough to occupy a row on its own`,
  toolCalls: [],
  isError: false,
}))

const container = () =>
  ({
    preferences: new InMemoryPreferenceStore(),
    now: () => new Date('2026-08-10T00:00:00Z'),
    stream: { connect: vi.fn(), disconnect: vi.fn() },
    sessions: {
      read: vi.fn().mockResolvedValue({
        id: SESSION,
        projectId: null,
        startedAt: '2026-08-10T00:00:00Z',
        forkedFrom: null,
        forkedAt: null,
        files: [],
        messages: MESSAGES,
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
          {/* `OverlayHost` because the end-session confirmation is a `Drawer`,
              exactly as `SessionView.test.tsx` explains; `100vh` rather than a
              pixel height so that resizing the viewport resizes the shell,
              which is what `60vh` is measured against. */}
          <OverlayHost>
            <div style={{ height: '100vh' }}>
              <Shell chrome={<span>chrome</span>}>
                <SessionView store={store} sessionId={SESSION} at={ScrubPoint.head()} path={null} />
              </Shell>
            </div>
          </OverlayHost>
        </StreamProvider>
      </QueryClientProvider>
    </ContainerProvider>,
  )
  await expect.element(page.getByRole('region', { name: 'Event log' })).toBeVisible()
}

const split = () => document.querySelector<HTMLElement>('.lay-split[data-split="session"]')!
const surface = () => document.querySelector<HTMLElement>('.lay-surface')!
const pane = (id: string) => document.querySelector<HTMLElement>(`[data-pane="${id}"]`)!
const body = (id: string) => pane(id).querySelector<HTMLElement>('.lay-pane-body')!
const box = (id: string) => pane(id).getBoundingClientRect()

/** Everything inside the split that paints outside a box which clips it: more
 *  `scrollWidth` than `clientWidth`, with no scroller to reach the remainder
 *  and no ellipsis to say it was cut. The previous slice's definition,
 *  unchanged, so the two views' numbers are comparable. */
const clipped = () =>
  Array.from(document.querySelectorAll<HTMLElement>('.lay-split *'))
    .filter((el) => el.clientWidth > 0 && el.scrollWidth > el.clientWidth)
    .filter((el) => {
      const style = getComputedStyle(el)
      return style.overflowX === 'visible' && style.textOverflow !== 'ellipsis'
    })
    .map(
      (el) => `${el.className || el.tagName} ${String(el.scrollWidth)}/${String(el.clientWidth)}`,
    )

/** Resize, and wait for both React and the browser to be on the other side of
 *  it.
 *
 * **Neither half of this poll is optional, and the first version of this helper
 * had only the first — which made it a no-op.** `data-collapse-to` is `'rail'`
 * at 1440 and `'rail'` at 821, so a 1440 → 821 resize satisfied it on the first
 * tick and the probe read the *1440* layout: a template of
 * `280px 320px 280px`, `Split`'s inline three-track template still on the
 * element, and a conversation 880px wide in an 821px viewport. This is the
 * same shape of failure the plan warns about in `widen()`, reached from the
 * other side.
 *
 * So the attribute proves React re-rendered where that boundary moves
 * (`Pane.tsx:126` flips it at 821), and the computed geometry proves the
 * browser re-laid-out where it does not — two columns in the band, a flex
 * column below it. The template is deliberately *not* used as the below-821
 * signal: the split is `display: flex` there, so `grid-template-columns`
 * computes to `none` and `'none'.split(' ')` has length 1, which is
 * indistinguishable from a genuine single-column defect.
 *
 * It is read through `getPropertyValue` rather than through the camel-cased
 * property, because `check-deleted.mjs` forbids that identifier anywhere under
 * the session view — phase A deleted a hand-built session grid and the rule is
 * what stops one coming back. Reading the browser's own answer is not that, but
 * the rule cannot tell, and a rule loosened for a test is worth less than one
 * spelling. */
const at = async (width: number, height = 900) => {
  await page.viewport(width, height)
  await expect
    .poll(() => pane('timeline').getAttribute('data-collapse-to'))
    .toBe(width < 821 ? 'strip' : 'rail')
  await expect
    .poll(() =>
      width < 821
        ? getComputedStyle(split()).flexDirection
        : String(
            getComputedStyle(split()).getPropertyValue('grid-template-columns').split(' ').length,
          ),
    )
    .toBe(width < 821 ? 'column' : '2')
}

// Nothing else resets it: the viewport is global to the whole browser run
// (`vite.config.ts` sets 1440x900 once) and a file that resized without
// restoring would leak into every sibling that ran after it, in file order.
afterEach(async () => {
  await page.viewport(1440, 900)
})

/** Claim 1. **B60.** Folding *both* session flanks rails both of them.
 *
 * The bug this closes: `responsive.css`'s two `:has()` rules for the session
 * block have identical specificity and each write the whole
 * `grid-template-columns`, so when both match the later one — `workspace`'s —
 * simply wins and `timeline` keeps a full-width track. `Pane.tsx:126` keys the
 * rail *form* on `stacked` rather than on the grid having granted a rail, so
 * what a reader gets is a 34px affordance with a rotated title stretched across
 * two thirds of the viewport.
 *
 * **Reachable in two clicks**: `toggleCollapsed` (`split-tracks.ts:98`) refuses
 * only when *every* pane would close, and the session split has three tracks.
 *
 * The rails are asserted rather than the template string, for the reason the
 * project view's equivalent claim gives: the template is the thing that was
 * wrong, so reading it back would have agreed with whichever rule won. The
 * first pane's width is re-read *after* the second fold, because the whole
 * defect is the second collapse silently undoing the first pane's track.
 *
 * **Proved red** against the block as it shipped, before the combined rule was
 * added, at 1000x900:
 *
 *     AssertionError: expected 966 to be close to 34, received difference is
 *     932, but expected 0.5
 */
it('rails both session flanks when both are folded', async () => {
  await show()
  await at(1000)

  await page.getByRole('button', { name: 'Collapse Event log' }).click()
  await expect.poll(() => box('timeline').width).toBeCloseTo(34, 0)
  await page.getByRole('button', { name: 'Collapse Workspace' }).click()
  await expect.poll(() => box('workspace').width).toBeCloseTo(34, 0)

  expect(box('timeline').width).toBeCloseTo(34, 0)
  expect(box('workspace').width).toBeCloseTo(34, 0)

  // Still the same arrangement: the two flanks share the top row and the
  // conversation still spans it. Folding two panes is not a way to reach a
  // different layout.
  expect(box('workspace').top).toBe(box('timeline').top)
  expect(box('conversation').top).toBeGreaterThanOrEqual(box('timeline').bottom - 1)
})

/** Claim 2. At the band's own bottom edge the session's two columns are
 *  342.078 and 478.906, both above the floors they declare, and nothing paints
 *  outside a box that clips it.
 *
 * 821 is the narrowest viewport at which this arrangement applies at all, so it
 * is the only width where a floor can bind. Nothing had measured it.
 *
 * **What the measurement settles, and it is a negative result worth writing
 * down.** `responsive.css` writes `minmax(300px, 1.4fr)` for `workspace` while
 * `SESSION_TRACKS` declares its floor as **320** (`use-session-panes.ts:23`) —
 * a CSS floor *below* the declared one, which is the shape of a real defect and
 * is why the plan asked for this. It is not one: `workspace` carries the 1.4
 * weight, so its share at 821 is 821 x (1.4 / 2.4) = **478.9**, and the band
 * only gets wider from there. The floor cannot bind at any width in the band,
 * so raising 300 to 320 would change no pixel anywhere — the same argument, and
 * deliberately the same resolution, as HOLDER's unreachable 320 in the project
 * block two rules below.
 *
 * `timeline`'s 280 matches its declared floor and is also unreachable: its
 * share is 342.078, and 342 is where it stays.
 *
 * **The floors are asserted against the numbers `SESSION_TRACKS` declares
 * rather than against the shares**, so that a future reweighting which made
 * either floor reachable fails here rather than silently clipping — which is
 * exactly how the project view's 344 was found, from underneath, in a 5px-wide
 * range nobody would have looked at.
 *
 * **The clip sweep is the part that is measured rather than argued.** Unlike
 * the project view, neither session floor was ever derived from a measurement —
 * `use-session-panes.ts` records that `panes.css`'s numbers never took effect at
 * all — so "342 clears 280" only says the arrangement obeys itself. What says
 * 342 is *wide enough* is that nothing in the pane overflows at it, in all
 * three collapse states the band can reach.
 *
 * **This claim passes against unfixed code and guards no fix in this slice.**
 * It is the bottom edge's first record, so it was proved to fail on a mutation
 * instead — and the mutation that works is the argument for keeping the claim.
 * `minmax(400px, 1fr)` on `timeline` does **not** fail it, which was the first
 * guess: 400 + 421 still sums to 821 and both floors still clear. What fails is
 * a floor large enough to squeeze the other column onto *its* floor —
 * `minmax(600px, 1fr)`, at 821x900:
 *
 *     AssertionError: expected 300 to be greater than or equal to 320
 *
 * That is the exact defect the 300/320 mismatch would become if the
 * arrangement ever changed: the CSS hands out 300 where the view declares 320,
 * and the only reason it is harmless today is that the number is unreachable.
 */
it('clears both declared floors at the bottom of the band, and clips nothing', async () => {
  await show()
  await at(821)

  expect(box('timeline').width).toBeGreaterThanOrEqual(280)
  expect(box('workspace').width).toBeGreaterThanOrEqual(320)

  // The two fill the row exactly: a floor that bound would move the boundary
  // between them, not add a gap or overflow the viewport.
  expect(Math.round(box('timeline').width + box('workspace').width)).toBe(821)

  // The conversation is the wrapped row and spans both.
  expect(Math.round(box('conversation').width)).toBe(821)

  expect(clipped(), 'both open at 821').toHaveLength(0)

  // And in the two states a reader can reach from here by clicking, where one
  // column takes the other's width. Only the flanks are checked because the
  // conversation's width does not change with either fold.
  await page.getByRole('button', { name: 'Collapse Event log' }).click()
  await expect.poll(() => box('timeline').width).toBeCloseTo(34, 0)
  expect(clipped(), 'timeline railed at 821').toHaveLength(0)

  await page.getByRole('button', { name: 'Expand Event log' }).click()
  await page.getByRole('button', { name: 'Collapse Workspace' }).click()
  await expect.poll(() => box('workspace').width).toBeCloseTo(34, 0)
  expect(clipped(), 'workspace railed at 821').toHaveLength(0)
})

/** Claim 3. Below 821 the session view stacks into a scrolling page, rather
 *  than three panes squeezed to share one screen.
 *
 * **Why this file has this claim at all.** Task A's fix for the project view
 * added `flex: 0 0 auto` to `.lay-split` inside `layout.css`'s below-821 block,
 * and `.lay-split` is the shared primitive — so the change reaches the session
 * and research views too, and no test in the suite renders either of those
 * below 821. A flagged it as unmeasured there rather than measured and fine.
 * This is the session half of that, and it is a check on somebody else's fix
 * rather than a guard on anything in this file's own scope.
 *
 * Measured at 700x900 with the 40-message fixture, after A's change: surface
 * **1063 / 856** — it scrolls — with the panes at 126.3 / 215.1 / 683.3, each
 * at its content's height under the cap, and both `regions` bodies showing all
 * of themselves. Nothing regressed here.
 *
 * **This passes against unfixed code in `responsive.css`**, which owns nothing
 * below 821; it would go red against `layout.css`, which this task must not
 * touch. Proved red by removing A's `flex: 0 0 auto` from the below-821
 * `.lay-split` rule, at 700x900:
 *
 *     AssertionError: expected 856 to be greater than 856
 *
 * — i.e. the defect A fixed is reproducible in this view too, which is the
 * answer to "does the fix reach here": it does, and it was needed here.
 */
it('stacks into a scrolling page below 821', async () => {
  await show()
  await at(700)

  const timeline = box('timeline')
  const workspace = box('workspace')
  const conversation = box('conversation')

  // One column, full width, in order, with no gap and no overlap.
  for (const b of [timeline, workspace, conversation]) {
    expect(b.left).toBe(0)
    expect(Math.round(b.width)).toBe(700)
  }
  expect(workspace.top).toBeCloseTo(timeline.bottom, 0)
  expect(conversation.top).toBeCloseTo(workspace.bottom, 0)

  // The page scrolls, and the split is what there is to scroll.
  const s = surface()
  expect(s.scrollHeight).toBeGreaterThan(s.clientHeight)
  expect(split().getBoundingClientRect().height).toBeGreaterThan(s.clientHeight)

  // Both `regions` panes show all of themselves rather than clipping under the
  // 60vh cap: their inner scrollers take the shortfall. This is the assertion
  // that would have caught A's fix breaking this view.
  for (const id of ['workspace', 'conversation']) {
    expect(getComputedStyle(body(id)).overflowY, id).toBe('hidden')
    expect(body(id).scrollHeight, id).toBeLessThanOrEqual(body(id).clientHeight)
  }

  expect(clipped(), 'stacked at 700').toHaveLength(0)
})

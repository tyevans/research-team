import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { page, userEvent } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { EventStreamListener } from '@application/ports/event-stream.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import type { Roster, Worker } from '@domain/worker/worker.ts'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { AgentWidget } from './AgentWidget.tsx'

/** Whether the agents popover's focus ring is on screen, which is a
 *  measurement and so cannot be asked in `AgentWidget.test.tsx`.
 *
 * The shape `FileList.browser.test.tsx` was written for, found again by
 * sweeping the console for it. `.agents-row` is a `<button>` at `width: 100%`
 * and `.agents-rows` has no padding, so a row's border box *is* the scroller's
 * padding box horizontally — while the global `:focus-visible` in `tokens.css`
 * draws 2px at `outline-offset: 1px`, three pixels outside it. `overflow`
 * clips at the padding box, so both vertical edges of the ring land on the far
 * side of the clip at once, and `.agents-panel`'s own `overflow: hidden` is a
 * second clip behind the first.
 *
 * **Proved red.** At the 1440x900 viewport `vite.config.ts` sets, with twelve
 * agents and the scroller's clip (padding box) at `1..527 x 0..216`:
 *
 * | Focused | Ring | Verdict |
 * |---|---|---|
 * | first row | `-2..530 x -3..34` | left, right and top outside the clip |
 * | a middle row | `-2..530 x 90..127` | left and right outside the clip |
 * | the scroller itself | `-2..530 x -3..219` | outside its own border box on all four sides |
 *
 * Worse than the table reads, and the reason this one was fixed rather than
 * noted: with a *single* agent running — which is the ordinary case, not the
 * edge — the scroller is exactly one row tall, its clip is `1..527 x 0..30`,
 * and the row's ring at `-2..530 x -3..33` is outside it on all four sides.
 * Zero pixels, the `FileList` finding exactly.
 *
 * jsdom reports all of this as a rule that applied perfectly: it lays nothing
 * out, so every rect is 0x0 and `getComputedStyle` returns the initial
 * `outline: none` whatever matched.
 *
 * What breaks these again: removing `.agents-row:focus-visible` or
 * `.agents-rows:focus-visible` from `agents.css`, or turning either one's
 * `outline-offset` back to a positive value.
 */

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

const worker = (over: Partial<Worker> = {}): Worker => ({
  kind: 'turn',
  ref: SESSION,
  detail: 'turn 12',
  sessionId: SESSION,
  parent: null,
  startedAt: null,
  ...over,
})

/** The real widget, real popover, real portal. A hand-written `.agents-panel`
 *  would measure markup nobody renders, and the panel's geometry is Radix's as
 *  much as it is the stylesheet's. */
const open = async (count: number) => {
  const container = {
    preferences: new InMemoryPreferenceStore(),
    projects: { list: vi.fn().mockResolvedValue([{ id: PROJECT, name: 'atlas' }]) },
    stream: { connect: (_l: EventStreamListener) => {}, disconnect: () => {} },
    workers: {
      on: vi.fn(),
      everywhere: vi.fn().mockResolvedValue([
        {
          projectId: PROJECT,
          workers: Array.from({ length: count }, (_, index) =>
            worker({ ref: `worker-${String(index)}`, detail: `turn ${String(index)}` }),
          ),
          idleSessionIds: [],
        } satisfies Roster,
      ]),
    },
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>
          <OverlayHost>{children}</OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  await render(<AgentWidget />, { wrapper })

  // Opened from the keyboard rather than with `.click()`, and that is a
  // precondition rather than a flourish. Chromium's `:focus-visible` heuristic
  // tracks the last interaction: after a pointer event a later programmatic
  // `focus()` does *not* match `:focus-visible`, so every rule under test goes
  // inert and the `focus()` helper below fails on its own assertion — which is
  // exactly how this file first came up red for the wrong reason. It is also
  // the more faithful route: a clipped focus ring is a keyboard reader's bug.
  const toggle = page.getByRole('button', { name: /Show what is running/i })
  // Awaited before it is touched: the count in the trigger's accessible name
  // arrives with the roster, so the locator resolves to nothing on first paint.
  await expect.element(toggle).toBeInTheDocument()
  ;(toggle.element() as HTMLElement).focus()
  await userEvent.keyboard('{Enter}')
  await expect
    .element(page.getByRole('dialog', { name: /Agents running now/i }))
    .toBeInTheDocument()

  const scroller = document.querySelector('.agents-rows') as HTMLElement
  const rows = Array.from(document.querySelectorAll<HTMLElement>('.agents-row'))
  expect(rows).toHaveLength(count)
  return { scroller, rows }
}

/** The outermost edge an element's outline reaches, in viewport coordinates.
 *  An outline sits `outline-offset` beyond the border box and is
 *  `outline-width` thick, so a negative offset pulls it inside. */
const ringBox = (element: HTMLElement) => {
  const style = getComputedStyle(element)
  const reach = parseFloat(style.outlineWidth) + parseFloat(style.outlineOffset)
  const box = element.getBoundingClientRect()
  return {
    drawn: style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0,
    top: box.top - reach,
    left: box.left - reach,
    right: box.right + reach,
    bottom: box.bottom + reach,
  }
}

/** What `overflow` actually clips: the padding box, not the border box. */
const clipBox = (element: HTMLElement) => {
  const box = element.getBoundingClientRect()
  return {
    top: box.top + element.clientTop,
    left: box.left + element.clientLeft,
    right: box.left + element.clientLeft + element.clientWidth,
    bottom: box.top + element.clientTop + element.clientHeight,
  }
}

/** Asserted rather than assumed. `:focus-visible` after a programmatic
 *  `focus()` is a heuristic; if this engine declined to match it, every rule
 *  under test would be inert while the geometry assertions still passed. */
const focus = (element: HTMLElement) => {
  element.focus()
  expect(element.matches(':focus-visible')).toBe(true)
}

it('keeps a single running agent from having no focus ring at all', async () => {
  // One agent is the ordinary case and the worst one: the scroller is exactly
  // as tall as the row, so the ring is outside the clip on all four sides
  // rather than three. This is `FileList`'s "not one pixel" measured again in
  // a different widget.
  const { scroller, rows } = await open(1)
  const row = rows[0]!
  focus(row)

  const ring = ringBox(row)
  const clip = clipBox(scroller)
  expect(ring.drawn).toBe(true)
  expect(ring.left).toBeGreaterThanOrEqual(clip.left)
  expect(ring.right).toBeLessThanOrEqual(clip.right)
  expect(ring.top).toBeGreaterThanOrEqual(clip.top)
  expect(ring.bottom).toBeLessThanOrEqual(clip.bottom)
})

it('keeps a row in a scrolling list from losing its sides', async () => {
  const { scroller, rows } = await open(12)
  // Deliberately not the first row. The first is clipped vertically too, so a
  // test using it would pass on a fix that only addressed the top edge; this
  // one isolates the pair that is wrong for every row in the list.
  const row = rows[3]!
  focus(row)

  const ring = ringBox(row)
  const clip = clipBox(scroller)
  expect(ring.left).toBeGreaterThanOrEqual(clip.left)
  expect(ring.right).toBeLessThanOrEqual(clip.right)
})

it('gives the row list itself a ring it can keep, because it can be focused', async () => {
  // The trap `FileList.browser.test.tsx` documents, met again: `.agents-rows`
  // has no `tabIndex` and reads as an inert wrapper, and Chromium focuses a
  // scroll container anyway. Past eight agents it is a real tab stop sitting
  // inside `.agents-panel`, which is `overflow: hidden` and would take an
  // outward ring away entirely.
  const { scroller } = await open(12)
  expect(scroller.scrollHeight).toBeGreaterThan(scroller.clientHeight)
  focus(scroller)
  expect(document.activeElement).toBe(scroller)

  const ring = ringBox(scroller)
  const box = scroller.getBoundingClientRect()
  expect(ring.drawn).toBe(true)
  expect(ring.top).toBeGreaterThanOrEqual(box.top)
  expect(ring.left).toBeGreaterThanOrEqual(box.left)
  expect(ring.right).toBeLessThanOrEqual(box.right)
  expect(ring.bottom).toBeLessThanOrEqual(box.bottom)
})

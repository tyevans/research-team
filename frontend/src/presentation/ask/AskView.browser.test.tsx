/** The ask page's layout, which is a measurement and so cannot be asked in
 *  `AskView.test.tsx`.
 *
 * This page had a stylesheet until the stylesheet freeze in
 * `scripts/check-deleted.mjs` made a 23rd one a build failure, and its rules
 * are Tailwind utilities on the markup now. That port is exactly the change a
 * green jsdom suite cannot see: jsdom applies no stylesheet, so a `className`
 * that generates *no rule at all* reads identically to one that lays the page
 * out correctly.
 *
 * **Proved red, and it caught a real one.** While this page was being written
 * `m-0` and `p-0` emitted nothing -- `@theme` declared `--spacing-1` upward
 * and no base step, so the `0` step had no value to compute from -- and the
 * second test failed with the user agent's `16px` margin still on the lists
 * while every other gate passed, `npm run build` included. `--spacing-0` and
 * `check-tailwind.mjs` landed on main independently and fix the class of
 * defect at the source. This stays anyway: that check proves the utility
 * *compiles*, and this proves it lands on the element a reader is looking at,
 * which is the half no build-output grep can see.
 *
 * The first test fails against a view that scrolls as a whole -- drop
 * `overflow-hidden` from the section or `overflow-y-auto` from the thread and
 * the composer leaves the bottom edge on a long conversation, which is
 * precisely when somebody wants to type the next question.
 */
import { expect, it, vi } from 'vitest'
import { page, userEvent } from 'vitest/browser'
import { render } from 'vitest-browser-react'
import type { ReactNode } from 'react'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AskEvent } from '@domain/ask/conversation.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { AskView } from './AskView.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

/** A transcript long enough that the thread really overflows. A page measured
 *  with room to spare measures nothing -- see `mount`'s precondition. */
const TURNS = 12

/** Answers immediately, with a citation so `CitationList`'s own list is on
 *  screen for the zeroing assertion. */
const answering = vi.fn(
  async (
    _p: ProjectId,
    _c: string,
    _q: string,
    onEvent: (event: AskEvent) => void,
  ): Promise<void> => {
    onEvent({
      type: 'answer',
      text: 'A paragraph of answer, long enough to take a line of its own on the page.',
      blocks: [],
      position: 0,
      citations: [{ kind: 'source', id: 's1' }],
    })
  },
)

/** The height is the point: the surface this view sits in does not grow, so
 *  the page has to fit a viewport it does not choose. `AskView` is normally
 *  inside `.lay-surface`, and this is that constraint without the shell. */
const Page = () => {
  const container = {
    ask: { ask: answering, forget: vi.fn() },
  } as unknown as AppContainer
  const wrapper = (children: ReactNode) => (
    <ContainerProvider container={container}>{children}</ContainerProvider>
  )
  return (
    <div style={{ height: '520px', width: '900px', display: 'flex', flexDirection: 'column' }}>
      {wrapper(<AskView projectId={PROJECT} />)}
    </div>
  )
}

const mount = async () => {
  await render(<Page />)

  // One real question first, because an empty transcript is not this layout:
  // `AskThread` renders an `EmptyState` instead of the scrolling box, so there
  // is nothing to measure until a turn exists. It also puts a `CitationList`
  // on screen, which the zeroing test needs.
  await userEvent.type(page.getByRole('textbox'), 'what did we find?')
  await userEvent.click(page.getByRole('button', { name: /^ask$/i }))
  await expect.element(page.getByRole('link', { name: /s1/ })).toBeInTheDocument()

  const view = document.querySelector('section.ask') as HTMLElement
  const thread = view.querySelector('.ask-thread') as HTMLElement
  const composer = view.querySelector('form.ask-composer') as HTMLElement

  // Enough turns to overflow, written straight into the thread rather than
  // typed: this test is about the box, and twelve round trips through the
  // composer would make it a test of the store instead.
  for (let index = 0; index < TURNS; index += 1) {
    const turn = document.createElement('article')
    turn.textContent = `A question and its answer, number ${String(index)}, taking a line or two.`
    turn.style.minHeight = '80px'
    thread.append(turn)
  }

  return { view, thread, composer }
}

it('scrolls the thread and not the page, so the composer keeps the bottom edge', async () => {
  const { view, thread, composer } = await mount()

  // The precondition, asserted rather than assumed. With nothing overflowing
  // every assertion below passes against a page that scrolls as a whole.
  expect(thread.scrollHeight).toBeGreaterThan(thread.clientHeight)

  expect(view.scrollHeight).toBeLessThanOrEqual(view.clientHeight)

  const surface = view.getBoundingClientRect()
  const bar = composer.getBoundingClientRect()
  expect(Math.abs(bar.bottom - surface.bottom)).toBeLessThan(1)
  expect(Math.abs(bar.left - surface.left)).toBeLessThan(1)
  expect(Math.abs(bar.right - surface.right)).toBeLessThan(1)
})

it('caps the prose column below the width of the surface', async () => {
  // The fault this redesign exists for. Before it, these two were equal: the
  // head was capped at 1100px by `.view-head` and overridden to `max-w-none!`
  // to match a thread that had no cap at all, which made the page uniformly
  // too wide rather than uniformly right.
  //
  // Compared against the thread's own available width, not `view.clientWidth`:
  // `.ask-thread` carries its own inline padding, so the column is narrower
  // than the surface *regardless of the cap*. Comparing against `view` passed
  // even with `max-width: 72ch` commented out of `.ask-measure` -- the first
  // draft of this assertion measured the thread's padding, not the cap.
  const { thread } = await mount()
  const column = thread.querySelector('.ask-measure') as HTMLElement

  const threadStyle = getComputedStyle(thread)
  const available =
    thread.clientWidth - parseFloat(threadStyle.paddingLeft) - parseFloat(threadStyle.paddingRight)

  const width = column.getBoundingClientRect().width
  expect(width).toBeLessThan(available)
  expect(width).toBeGreaterThan(0)
})

it('lines the question box up with the prose above it', async () => {
  // The other half of the measure, and the one a stylesheet gets wrong
  // silently: a thread that centres its column and a composer that does not
  // both look fine alone.
  //
  // This passes partly because headless Chromium uses overlay scrollbars.
  // `.ask-thread` is `overflow-y-auto` and really overflows here, so with
  // classic (space-taking) scrollbars its content box would be narrower than
  // the composer's by the scrollbar width, the two centred columns would sit
  // a few pixels apart, and this assertion would go red -- and the columns
  // would genuinely misalign for a reader on a platform with classic
  // scrollbars. `px-5` on `.ask-thread` leaves room for the scrollbar but the
  // composer carries the same `px-5` with no scrollbar to make room for, so
  // it does not actually compensate. This console is Chromium by explicit
  // choice (`vite.config.ts`), so it is not fixed here.
  const { thread, composer } = await mount()
  const prose = (thread.querySelector('.ask-measure') as HTMLElement).getBoundingClientRect()
  const box = (composer.querySelector('.ask-measure') as HTMLElement).getBoundingClientRect()

  expect(Math.abs(box.left - prose.left)).toBeLessThan(1)
  expect(Math.abs(box.right - prose.right)).toBeLessThan(1)
})

it('zeroes the lists the missing preflight would otherwise leave indented', async () => {
  await mount()

  // The citation row, which is on screen already. The activity fold's list is
  // not rendered until it is opened -- `Disclosure` renders `{open ? … }` --
  // so it is not reachable here without driving the fold.
  const list = document.querySelector('section.ask ul') as HTMLElement
  const style = getComputedStyle(list)
  expect(style.marginBlockStart).toBe('0px')
  expect(style.paddingInlineStart).toBe('0px')
  expect(style.listStyleType).toBe('none')
})

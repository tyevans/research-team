/** That a dialogue reads as a conversation with two speakers.
 *
 * jsdom applies no stylesheet, so `getComputedStyle` returns only what an
 * inline style said and every colour assertion below is meaningless there --
 * a `.dlg-question` with its whole rule deleted reports the same empty values
 * as one that painted correctly. This is the suite that can judge them.
 *
 * The elements asserted on carry no user-agent dressing of their own: a `div`
 * and a `p` have no border and no background until this stylesheet gives them
 * one, unlike the `fieldset` an earlier browser test in this repo measured and
 * found still green with its rules renamed away. Deleting `.dlg-question`'s
 * `background` reddens the first test; deleting its `border-left` reddens the
 * third.
 *
 * **That second claim was false until 2026-08-18 and is worth reading as a
 * warning.** The rule is `.dlg-question, .dlg-pending { border: 0; border-left:
 * 2px solid var(--accent-dim) }` with `.dlg-pending` overriding only
 * `border-left-color`. Delete the shared shorthand and the pending question
 * still resolves a colour from its own surviving override while the settled one
 * falls back to `color` -- so `glow !== quiet` still held, and the second
 * assertion compared two elements that had both fallen back to the same
 * fallback. The third test stayed green with the rule it named deleted, which
 * is exactly the defect the `fieldset` above warns about, shipped a second
 * time. What fixes it is asserting the *width*, which `border: 0` zeroes and
 * only the shorthand restores.
 */
import { expect, it } from 'vitest'
import { render } from 'vitest-browser-react'
import type { ComponentProps, ReactNode } from 'react'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'

import { DialoguePage } from './DialoguePage.tsx'
import { exchange, PROJECT } from './dialogue-fixtures.ts'

type Props = ComponentProps<typeof DialoguePage>

/** One exchange under an opening question, which is the smallest transcript
 *  that has both speakers AND an outstanding question below a settled one.
 *
 * `concluded` on the newest turn is one of the two things `DialoguePage` reads
 * to decide the page is over, and it is the one these tests vary: it is the
 * live-dialogue half, which is the case that has a transcript to measure. The
 * store's half is for a resumed dialogue, which has no turns at all and so
 * nothing here to lay out. */
const props = (concluded = false): Props => ({
  projectId: PROJECT,
  transcript: [exchange({ concluded })],
  concluded: false,
  goal: 'understand what the creed settled',
  stoppingCondition: 'the reader separates the settlement from the politics',
  openingBlocks: [{ kind: 'markdown', text: 'Where would you start?' }],
  dialogueId: 'd1',
  progress: {},
  progressUnavailable: false,
  replying: false,
  starting: false,
  error: null,
  onStart: () => undefined,
  onReply: () => undefined,
})

/** The height is the point, as on `AskView.browser.test.tsx`: this page is
 *  `flex-1` inside a surface that does not grow, so a wrapper with no height
 *  would let it size to its content and measure a layout no reader sees. */
const mount = async (concluded = false) => {
  const container = {
    dialogues: { submitDialogueAttempt: () => undefined },
  } as unknown as AppContainer
  const wrapper = (children: ReactNode) => (
    <ContainerProvider container={container}>{children}</ContainerProvider>
  )
  const screen = await render(
    <div style={{ height: '520px', width: '900px', display: 'flex', flexDirection: 'column' }}>
      {wrapper(<DialoguePage {...props(concluded)} />)}
    </div>,
  )
  const questions = [
    ...screen.container.querySelectorAll<HTMLElement>('[data-testid="dlg-question"]'),
  ]
  return {
    screen,
    /** The opening question -- first in the document, and the one belonging to
     *  no turn. */
    opening: questions[0]!,
    /** The newest question, which is the turn's own. */
    newest: questions[questions.length - 1]!,
    answer: screen.container.querySelector<HTMLElement>('[data-testid="dlg-answer"]')!,
    exchange0: screen.container.querySelector<HTMLElement>('[data-testid="dlg-exchange-0"]')!,
  }
}

it('draws the dialogue’s question and the reader’s answer as visibly different things', async () => {
  const { opening, answer } = await mount()

  // Compared against each other rather than to literals, so a token value
  // change does not fail this. If these match, the transcript is a wall of
  // identical paragraphs and a reader cannot tell who is speaking -- which is
  // the failure a jsdom test cannot see at all.
  expect(getComputedStyle(opening).backgroundColor).not.toBe(
    getComputedStyle(answer).backgroundColor,
  )

  // An undefined custom property sets no background and resolves to a
  // transparent computed value, which is how `--bg-raised` would have shipped
  // looking like a rule that worked. `--bg-panel-2` is the name that exists.
  expect(getComputedStyle(opening).backgroundColor).not.toBe('rgba(0, 0, 0, 0)')

  const rect = opening.getBoundingClientRect()
  expect(rect.height).toBeGreaterThan(20)
  expect(rect.width).toBeGreaterThan(200)
})

it('keeps the outstanding question below the exchange it came out of', async () => {
  // Order in the document is asserted in jsdom; this asserts order in the
  // LAYOUT, which a `position: absolute` or a flex `order` could break while
  // the DOM order stayed correct.
  //
  // Not the brief's `pending.top >= exchange0.bottom`, which cannot pass and
  // should not: under the chronological shape Task 4 shipped, the outstanding
  // question is drawn INSIDE its exchange, so it can never be below that
  // exchange's own bottom edge. The real claim is that it sits below the
  // reader's answer and below the question that preceded it -- which is what
  // makes the last thing on the page the thing waiting on the reader.
  const { opening, newest, answer, exchange0 } = await mount()

  expect(newest.getBoundingClientRect().top).toBeGreaterThanOrEqual(
    answer.getBoundingClientRect().bottom,
  )
  expect(newest.getBoundingClientRect().top).toBeGreaterThanOrEqual(
    opening.getBoundingClientRect().bottom,
  )
  // The containment the paragraph above turns on, asserted rather than
  // assumed: if this stops holding, the two comparisons are measuring a
  // different page than the one described.
  expect(exchange0.contains(newest)).toBe(true)
})

it('stops glowing at the last question once the dialogue has concluded', async () => {
  // `.dlg-pending` brightens the left rule to say the reader is being waited
  // on. A concluded dialogue replaces the composer with "This dialogue has
  // reached its goal", so a glowing question beside it invites an answer there
  // is nowhere to type.
  //
  // The two colours are compared against each other rather than to literals,
  // for the first test's reason. Red against Task 4's page, which passed no
  // `concluded` to the thread at all -- and invisible to jsdom, where both
  // read as the empty string.
  const live = await mount(false)
  const over = await mount(true)

  const glow = getComputedStyle(live.newest).borderLeftColor
  const quiet = getComputedStyle(over.newest).borderLeftColor
  expect(glow).not.toBe(quiet)

  // Not merely different -- there has to BE a rule, and the WIDTH is the only
  // thing here that says so. This replaces two assertions that could not fail:
  // an equality between two settled questions (both fall back to `color`, so
  // it passed trivially) and, worse, the file docstring's claim that deleting
  // `border-left` reddened this test. It did not. `.dlg-pending` overrides
  // `border-left-color` alone, so with the shared shorthand gone `glow` still
  // resolved from that override while `quiet` fell back to `color`, and the
  // difference survived.
  //
  // `border: 0` in the same rule zeroes all four sides, so `2px` on the left
  // can only come from the shorthand this test names. Measured in Chromium on
  // 2026-08-18 by deleting that declaration: `2px` became `0px` on both, which
  // is the red the docstring had been promising for a slice.
  expect(getComputedStyle(live.newest).borderLeftWidth).toBe('2px')
  expect(getComputedStyle(over.newest).borderLeftWidth).toBe('2px')
})

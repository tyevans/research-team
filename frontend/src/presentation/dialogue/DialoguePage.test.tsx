/** What jsdom can judge about the dialogue page: the order of the transcript,
 *  who said what, and that the framing is on screen.
 *
 * Height and layout belong in `DialoguePage.browser.test.tsx` (Task 5), for
 * CLAUDE.md's reason: jsdom lays nothing out.
 */
import { render, screen, within } from '@testing-library/react'
import type { ComponentProps, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'

import { ComponentId } from '@domain/shared/identifier.ts'

import { componentBlock } from '../ask/ask-fixtures.ts'
import { DialoguePage } from './DialoguePage.tsx'
import { exchange, PROJECT } from './dialogue-fixtures.ts'

/** Typed against the component rather than `Record<string, unknown>`, which is
 *  how the brief had it: an untyped literal makes `kind: 'markdown'` a
 *  `string` and every call site a typecheck failure, and -- worse -- it would
 *  let a renamed prop through silently. */
type Props = ComponentProps<typeof DialoguePage>

const props = (over: Partial<Props> = {}): Props => ({
  projectId: PROJECT,
  transcript: [],
  goal: 'understand what the creed settled',
  stoppingCondition: 'the reader separates the settlement from the politics',
  openingBlocks: [{ kind: 'markdown', text: 'Where would you start?' }],
  dialogueId: 'd1',
  progress: {},
  replying: false,
  starting: false,
  error: null,
  onStart: vi.fn(),
  onReply: vi.fn(),
  ...over,
})

/** Every render goes through a real provider rather than the exchange guarding
 *  its attempts hook behind `hasComponents`.
 *
 * The guard was the cheaper way to keep these renders working and is the wrong
 * one: it would hide a missing `ContainerProvider` until the first question
 * that happened to carry a widget, which is production rather than this suite.
 * Nothing here submits an attempt, so the container is a stub -- what it buys
 * is that the hook runs on the path every test exercises. */
const draw = (over: Partial<Props> = {}) => {
  const container = { dialogues: { submitDialogueAttempt: vi.fn() } } as unknown as AppContainer
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>{children}</ContainerProvider>
  )
  return render(<DialoguePage {...props(over)} />, { wrapper })
}

it('shows the goal and the stopping condition to the reader', () => {
  // The design's §5, and the one thing that separates this from a quiz: a
  // reader who disagrees with the goal should be able to see that they
  // disagree before spending twenty minutes on it. Red against a page that
  // reads the framing off the store and renders neither.
  draw()

  expect(screen.getByText(/what the creed settled/)).toBeInTheDocument()
  expect(screen.getByText(/separates the settlement from the politics/)).toBeInTheDocument()
})

it('draws the dialogue asking and the reader answering', () => {
  // **The direction trap.** `blocks` is the dialogue's utterance and `reply`
  // is the reader's -- the inverse of an ask. A page that reused `AskTurn`
  // unchanged would render these swapped and it would still read as a
  // conversation, which is why this asserts on which element holds which text
  // rather than on both being present.
  //
  // It cannot catch an ordering swap: with the two testids left where they
  // are, reversing the children leaves this green. That is the next test.
  draw({
    transcript: [
      exchange({
        blocks: [{ kind: 'markdown', text: 'What makes you say settled?' }],
        reply: 'It settled Arianism.',
      }),
    ],
  })

  const drawn = screen.getByTestId('dlg-exchange-0')
  expect(within(drawn).getByTestId('dlg-question')).toHaveTextContent('What makes you say settled?')
  expect(within(drawn).getByTestId('dlg-answer')).toHaveTextContent('It settled Arianism.')
})

it('puts the answer before the question it produced, not merely in the data', () => {
  // **Chronological, and this is the assertion the first draft of this page
  // had backwards.** A turn pairs `(reply, blocks)` where `blocks` is the
  // question the reply PRODUCED -- and `app.py:3117` says the frame's
  // `pending_blocks` is "the question being answered, not the one about to be
  // asked". So a page drawing `blocks` above `reply` puts every question above
  // the answer that caused it: a live two-exchange dialogue reads Q2, A1, Q3,
  // A2, with the outstanding question buried mid-page. Red against exactly
  // that page, which is what the brief specified and what shipped in bbca2b5.
  draw({
    transcript: [
      exchange({
        blocks: [{ kind: 'markdown', text: 'QUESTION SECOND' }],
        reply: 'ANSWER FIRST',
      }),
    ],
  })

  const text = screen.getByTestId('dlg-exchange-0').textContent ?? ''
  expect(text.indexOf('ANSWER FIRST')).toBeLessThan(text.indexOf('QUESTION SECOND'))
})

it('never ends on the reader’s own words, on a dialogue with turns', () => {
  // **The real invariant, and not "an element with class `.dlg-pending`
  // exists".** A page ending on the reader's answer with nothing asking them
  // anything is the failure; under chronological order the cure is structural,
  // because the last thing on the page is the newest question the dialogue
  // asked. Red against the shipped question-above-answer order, where a
  // two-turn dialogue ends on the second reply.
  draw({
    transcript: [
      exchange({ blocks: [{ kind: 'markdown', text: 'EARLIER' }], reply: 'first answer' }),
      exchange({ blocks: [{ kind: 'markdown', text: 'OUTSTANDING' }], reply: 'LAST ANSWER' }),
    ],
  })

  const thread = screen.getByTestId('dlg-thread').textContent ?? ''
  expect(thread.indexOf('LAST ANSWER')).toBeLessThan(thread.indexOf('OUTSTANDING'))
  expect(thread.indexOf('EARLIER')).toBeLessThan(thread.indexOf('OUTSTANDING'))
  const questions = screen.getAllByTestId('dlg-question')
  expect(questions[questions.length - 1]).toHaveTextContent('OUTSTANDING')
})

it('never ends on the reader’s own words, on a dialogue with none', () => {
  // The same invariant in the case the first reader meets: no turns, one
  // opening question, which belongs to the dialogue row and to no turn. Red
  // against a thread that renders the transcript alone -- which draws nothing
  // at all here, and draws a reader answering something nobody asked as soon
  // as there is a turn.
  draw({ transcript: [] })

  expect(screen.getByTestId('dlg-question')).toHaveTextContent('Where would you start?')
})

it('marks the newest question as the one waiting on the reader', () => {
  // `.dlg-pending` survives the chronological shape as a modifier and not as
  // an element: the outstanding question is not a special case, it is the last
  // thing the dialogue said. The class is what Task 5's browser test measures,
  // so it has to be on the right one of two identical-looking blocks.
  draw({
    transcript: [
      exchange({ blocks: [{ kind: 'markdown', text: 'EARLIER' }] }),
      exchange({ blocks: [{ kind: 'markdown', text: 'OUTSTANDING' }] }),
    ],
  })

  const marked = screen.getByTestId('dlg-thread').querySelectorAll('.dlg-pending')
  expect(marked).toHaveLength(1)
  expect(marked[0]).toHaveTextContent('OUTSTANDING')
})

it('keeps the marker on the last question asked while the next one is still coming', () => {
  // Mid-stream: the reader has answered and the open turn's `blocks` are empty
  // until its `prompt` frame lands. The question they were answering is the
  // PREVIOUS turn's, so that is what stays marked. Red against the obvious
  // `index === transcript.length - 1`, which marks a turn that renders no
  // question at all and leaves the page with nothing marked for the whole of
  // every model call -- the moment a reader is most likely to be looking.
  draw({
    transcript: [
      exchange({ blocks: [{ kind: 'markdown', text: 'ASKED' }] }),
      exchange({ blocks: [], settled: false }),
    ],
  })

  const marked = screen.getByTestId('dlg-thread').querySelectorAll('.dlg-pending')
  expect(marked).toHaveLength(1)
  expect(marked[0]).toHaveTextContent('ASKED')
})

it('says the dialogue is composing rather than showing a half-written question', () => {
  // Deltas drive this and nothing else -- see `domain/dialogue/conversation.ts`
  // for why the text they carry never reaches the page.
  draw({ transcript: [exchange({ composing: true })] })

  expect(screen.getByTestId('dlg-composing')).toBeInTheDocument()
})

it('offers a topic composer and no reply composer before a dialogue exists', () => {
  draw({ dialogueId: null, openingBlocks: [] })

  expect(screen.getByLabelText(/topic/i)).toBeInTheDocument()
  expect(screen.queryByLabelText(/your answer/i)).not.toBeInTheDocument()
})

it('says a dialogue has finished when it concludes', () => {
  // Constructed directly, because nothing writes `SocraticDialogueConcluded`
  // until Plan 4 -- `concluded` is false on every frame a live server sends
  // today. Rendered now so Plan 4 lands without touching this file.
  draw({ transcript: [exchange({ concluded: true })] })

  expect(screen.getByText(/this dialogue has reached its goal/i)).toBeInTheDocument()
})

it('draws a widget the reader already answered as already answered', () => {
  // B114, on the page rather than in the store: the property that
  // distinguishes this surface from the ask is that a refresh finds the
  // answers still there, and until the progress route existed the recording
  // was real in the event log and invisible here.
  //
  // The assertion is the sentence a reader sees, not a class or a prop. Red
  // against a page that drops `progress` anywhere along the chain --
  // `DialogueView`, `DialoguePage`, `DialogueThread`, `DialogueExchange` --
  // because every one of those hands back a widget that says nothing.
  draw({
    transcript: [exchange({ blocks: [componentBlock({ type: 'mcq', id: 'council-1' })] })],
    progress: {
      'turn/0': new Map([
        [
          ComponentId('council-1'),
          { attempts: 2, correct: true, bestScore: 1, lastScore: 1, checked: [] },
        ],
      ]),
    },
  })

  expect(screen.getByText(/you answered this correctly after 2 tries before/i)).toBeInTheDocument()
})

it('keys remembered answers by the turn’s position and not by its index', () => {
  // The two agree on a transcript loaded whole and diverge the moment one does
  // not start at turn 0. The failure would be silent -- one exchange's
  // verdicts drawn against another's questions -- so it is asserted with a
  // single turn whose `position` is deliberately not its index.
  //
  // Red against `progress[`turn/${index}`]`, which finds nothing here.
  draw({
    transcript: [
      exchange({ position: 3, blocks: [componentBlock({ type: 'mcq', id: 'council-1' })] }),
    ],
    progress: {
      'turn/3': new Map([
        [
          ComponentId('council-1'),
          { attempts: 1, correct: true, bestScore: 1, lastScore: 1, checked: [] },
        ],
      ]),
    },
  })

  expect(screen.getByText(/you answered this correctly before/i)).toBeInTheDocument()
})

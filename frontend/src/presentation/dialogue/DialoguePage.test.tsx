/** What jsdom can judge about the dialogue page: the order of the transcript,
 *  who said what, and that the framing is on screen.
 *
 * Height and layout belong in `DialoguePage.browser.test.tsx` (Task 5), for
 * CLAUDE.md's reason: jsdom lays nothing out.
 */
import { render, screen, within } from '@testing-library/react'
import type { ComponentProps } from 'react'
import { expect, it, vi } from 'vitest'

import { DialoguePage } from './DialoguePage.tsx'
import { exchange, PROJECT } from './dialogue-fixtures.ts'

/** Typed against the component rather than `Record<string, unknown>`, which is
 *  how the brief had it: an untyped literal makes `kind: 'markdown'` a `string`
 *  and every call site a typecheck failure, and -- worse -- it would let a
 *  renamed prop through silently. */
type Props = ComponentProps<typeof DialoguePage>

const props = (over: Partial<Props> = {}): Props => ({
  projectId: PROJECT,
  transcript: [],
  goal: 'understand what the creed settled',
  stoppingCondition: 'the reader separates the settlement from the politics',
  pendingBlocks: [{ kind: 'markdown', text: 'Where would you start?' }],
  dialogueId: 'd1',
  replying: false,
  starting: false,
  error: null,
  onStart: vi.fn(),
  onReply: vi.fn(),
  ...over,
})

it('shows the goal and the stopping condition to the reader', () => {
  // The design's §5, and the one thing that separates this from a quiz: a
  // reader who disagrees with the goal should be able to see that they
  // disagree before spending twenty minutes on it. Red against a page that
  // reads the framing off the store and renders neither.
  render(<DialoguePage {...props()} />)

  expect(screen.getByText(/what the creed settled/)).toBeInTheDocument()
  expect(screen.getByText(/separates the settlement from the politics/)).toBeInTheDocument()
})

it('draws the dialogue asking and the reader answering, in that order', () => {
  // **The direction trap.** `blocks` is the dialogue's utterance and `reply`
  // is the reader's -- the inverse of an ask. A page that reused `AskTurn`
  // unchanged would render these swapped and it would still read as a
  // conversation, which is why this asserts on which element holds which text
  // rather than on both being present.
  render(
    <DialoguePage
      {...props({
        transcript: [
          exchange({
            blocks: [{ kind: 'markdown', text: 'What makes you say settled?' }],
            reply: 'It settled Arianism.',
          }),
        ],
      })}
    />,
  )

  const drawn = screen.getByTestId('dlg-exchange-0')
  expect(within(drawn).getByTestId('dlg-question')).toHaveTextContent('What makes you say settled?')
  expect(within(drawn).getByTestId('dlg-answer')).toHaveTextContent('It settled Arianism.')
})

it('puts the question before the answer in the document, not merely in the data', () => {
  // Order on screen, not order in the array. A page that rendered the reply
  // first would satisfy the test above and still show the reader answering a
  // question printed underneath their answer.
  render(
    <DialoguePage
      {...props({
        transcript: [
          exchange({
            blocks: [{ kind: 'markdown', text: 'QUESTION FIRST' }],
            reply: 'ANSWER SECOND',
          }),
        ],
      })}
    />,
  )

  const text = screen.getByTestId('dlg-exchange-0').textContent ?? ''
  expect(text.indexOf('QUESTION FIRST')).toBeLessThan(text.indexOf('ANSWER SECOND'))
})

it('renders the outstanding question after the last exchange', () => {
  // The pending question belongs to no turn -- it is the one the reader is
  // answering now. A page that omitted it ends the transcript on the reader's
  // own words with nothing asking them anything. Red against a thread that
  // renders `transcript` alone.
  render(
    <DialoguePage
      {...props({
        transcript: [
          exchange({ blocks: [{ kind: 'markdown', text: 'EARLIER' }], reply: 'answered' }),
        ],
        pendingBlocks: [{ kind: 'markdown', text: 'OUTSTANDING' }],
      })}
    />,
  )

  const thread = screen.getByTestId('dlg-thread').textContent ?? ''
  expect(thread.indexOf('EARLIER')).toBeLessThan(thread.indexOf('OUTSTANDING'))
  expect(screen.getByTestId('dlg-pending')).toHaveTextContent('OUTSTANDING')
})

it('shows the opening question when nothing has been answered yet', () => {
  // A fresh dialogue: no turns, one outstanding question. Red against a thread
  // that renders the pending block only when the transcript is non-empty.
  render(<DialoguePage {...props({ transcript: [] })} />)

  expect(screen.getByTestId('dlg-pending')).toHaveTextContent('Where would you start?')
})

it('says the dialogue is composing rather than showing a half-written question', () => {
  // Deltas drive this and nothing else -- see `domain/dialogue/conversation.ts`
  // for why the text they carry never reaches the page.
  render(<DialoguePage {...props({ transcript: [exchange({ composing: true })] })} />)

  expect(screen.getByTestId('dlg-composing')).toBeInTheDocument()
})

it('offers a topic composer and no reply composer before a dialogue exists', () => {
  render(<DialoguePage {...props({ dialogueId: null, pendingBlocks: [] })} />)

  expect(screen.getByLabelText(/topic/i)).toBeInTheDocument()
  expect(screen.queryByLabelText(/your answer/i)).not.toBeInTheDocument()
})

it('says a dialogue has finished when it concludes', () => {
  // Constructed directly, because nothing writes `SocraticDialogueConcluded`
  // until Plan 4 -- `concluded` is false on every frame a live server sends
  // today. Rendered now so Plan 4 lands without touching this file.
  render(<DialoguePage {...props({ transcript: [exchange({ concluded: true })] })} />)

  expect(screen.getByText(/this dialogue has reached its goal/i)).toBeInTheDocument()
})

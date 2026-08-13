import type { Meta, StoryObj } from '@storybook/react-vite'

import { AskPage } from './AskPage.tsx'
import { PROJECT, transcript, turn } from './ask-fixtures.ts'

/** The whole page, in the five states it has.
 *
 * The fixed-height decorator is not decoration. This page's central layout
 * claim is that it fits a viewport it does not choose -- the thread scrolls
 * and the composer keeps the bottom edge -- and a story that lets it grow to
 * its content is showing a different component. 520px is the height
 * `AskView.browser.test.tsx` measures at, so the two agree.
 */
const meta = {
  component: AskPage,
  title: 'ask/AskPage',
  parameters: { layout: 'fullscreen' },
  decorators: [
    (Story) => (
      <div style={{ height: '520px', display: 'flex', flexDirection: 'column' }}>
        <Story />
      </div>
    ),
  ],
  args: {
    projectId: PROJECT,
    transcript: [],
    asking: false,
    error: null,
    onAsk: () => {},
    onReset: () => {},
  },
} satisfies Meta<typeof AskPage>

export default meta

type Story = StoryObj<typeof meta>

/** Nothing asked. The page says it keeps nothing in three places -- the
 *  subtitle, this empty state and the composer's hint -- which is repetition
 *  on purpose: the cost of a reader missing it is coming back tomorrow for an
 *  answer that is gone. */
export const Empty: Story = {}

export const OneTurn: Story = { args: { transcript: [turn()] } }

/** Mid-answer, with the box disabled. The store refuses a second question on
 *  a busy chat, and the disabled state is how the page says so before the
 *  reader has typed anything. */
export const Streaming: Story = {
  args: {
    asking: true,
    transcript: [turn({ answer: 'They agree on the effect and disagree on its', settled: false })],
  },
}

/** A refusal, said twice. The banner is what a reader who has scrolled away
 *  sees; the turn's own copy says which question died. */
export const Refused: Story = {
  args: {
    error: 'the model is already answering another question on this chat',
    transcript: [
      turn(),
      turn({
        question: 'And what about the third?',
        answer: '',
        citations: [],
        error: 'already answering another question on this chat',
      }),
    ],
  },
}

/** Long enough to overflow, which is the only state that shows what the
 *  layout is for: the thread scrolls and the composer does not move. */
export const LongThread: Story = { args: { transcript: transcript(12) } }

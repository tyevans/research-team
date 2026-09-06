import type { Meta, StoryObj } from '@storybook/react-vite'

import { AskHistory } from './AskHistory.tsx'
import { PROJECT } from './ask-fixtures.ts'

/** Past conversations, as the thread's empty state draws them.
 *
 * The three states are here because each is a different thing to a reader and
 * only one of them is the happy path: a project with history, a project with
 * none (which renders nothing at all -- the empty state above it already says
 * what to do), and a projection that is unwired, which the list route answers
 * with a 503 rather than an empty list precisely so the two can be told apart.
 */
const meta = {
  component: AskHistory,
  title: 'ask/AskHistory',
  args: { projectId: PROJECT, error: null },
} satisfies Meta<typeof AskHistory>

export default meta

type Story = StoryObj<typeof meta>

export const Several: Story = {
  args: {
    conversations: [
      {
        conversationId: 'c-1',
        openedAt: '2026-09-04T09:12:00Z',
        firstQuestion: 'What does the corpus say about the succession crisis of AD 193?',
        turnCount: 6,
      },
      {
        conversationId: 'c-2',
        openedAt: '2026-09-01T16:40:00Z',
        // Long on purpose: the row clamps to two lines, and a story that only
        // ever showed short questions could not show whether it does.
        firstQuestion:
          'Which of the sources gathered so far disagree with each other about the date of the Edict of Thessalonica, and on what evidence does each of them rest its claim?',
        turnCount: 2,
      },
      {
        conversationId: 'c-3',
        openedAt: '2026-08-29T11:05:00Z',
        firstQuestion: 'Summarise the findings on imperial cult.',
        turnCount: 1,
      },
    ],
  },
}

/** Renders nothing, and that is correct -- like `CitationList`'s `None`, an
 *  empty container here is the outcome rather than a story that failed. */
export const Nothing: Story = { args: { conversations: [] } }

export const Refused: Story = {
  args: { conversations: [], error: 'ask history is not configured' },
}

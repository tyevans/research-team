import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import { AskTurn } from './AskTurn.tsx'
import { PROJECT, assistantCall, toolResult, turn } from './ask-fixtures.ts'

/** One exchange, in the five states a turn passes through.
 *
 * `Streaming` is the one worth looking at deliberately: an answer arriving a
 * token at a time, with the pending line under it, is the state that decides
 * whether the page feels alive or hung, and it is on screen for a second at a
 * time in the real application.
 */
const meta = {
  component: AskTurn,
  title: 'ask/AskTurn',
  parameters: { layout: 'fullscreen' },
  // The measure is half of what a turn looks like, and it comes from the
  // thread rather than from the turn -- so a story that let the turn run the
  // full width of the canvas would be showing a shape the application never
  // draws.
  decorators: [
    (Story) => (
      <div className="ask-measure" style={{ padding: 'var(--space-5)' }}>
        <Story />
      </div>
    ),
  ],
  args: { projectId: PROJECT, open: false, onToggle: () => {} },
} satisfies Meta<typeof AskTurn>

export default meta

type Story = StoryObj<typeof meta>

export const Answered: Story = { args: { turn: turn() } }

/** With the fold open, which is the only way to see the activity list. The
 *  fold is controlled from outside, so a story that wants it open has to hold
 *  the state itself. */
export const WithActivity: Story = {
  args: {
    turn: turn({
      // Call frames and their result frames, as the stream really delivers
      // them -- the story is about how a run reads, and a story made only of
      // result frames would show the rows the join is meant to remove.
      activity: [
        assistantCall({ name: 'graph_search', args: { query: 'Imperial cult' }, id: 'c1' }),
        toolResult({
          name: 'graph_search',
          callId: 'c1',
          content:
            'Imperial cult (concept) -- 14 relationship(s) [e1]\nAugustus (person) -- 9 relationship(s) [e2]',
        }),
        assistantCall({ name: 'read_source', args: { source_id: 'wiki-imperial-cult' }, id: 'c2' }),
        toolResult({
          name: 'read_source',
          callId: 'c2',
          content:
            'wiki-imperial-cult@0-20000 of 84210 chars\ntitle: Imperial cult of ancient Rome',
        }),
        assistantCall({ name: 'read_source', args: { source_id: 'wiki-missing' }, id: 'c3' }),
        toolResult({
          name: 'read_source',
          callId: 'c3',
          content: "No source 'wiki-missing' in this project's corpus.",
          isError: true,
        }),
        // Still running: the answer streamed before this one came back.
        assistantCall({ name: 'grep', args: { pattern: 'pontifex', path: '/' }, id: 'c4' }),
      ],
    }),
  },
  render: function Open(args) {
    const [open, setOpen] = useState(true)
    return <AskTurn {...args} open={open} onToggle={() => setOpen((it) => !it)} />
  },
}

/** Mid-stream: some answer, not settled, no citations yet. Citations arrive
 *  with the `answer` frame, so a streaming turn having none is the real shape
 *  of the data rather than a gap in the fixture. */
export const Streaming: Story = {
  args: {
    turn: turn({
      answer: 'They agree on the effect and disagree on its',
      citations: [],
      settled: false,
    }),
  },
}

/** A question that did not go through. The page says this twice -- here and
 *  in the banner -- and this half is the one that says *which* question. */
export const Failed: Story = {
  args: {
    turn: turn({
      answer: '',
      citations: [],
      error: 'the model is already answering another question on this chat',
    }),
  },
}

/** Most answers cite nothing, so this is the common case rather than the edge
 *  one: `CitationList` renders nothing at all rather than an empty "Sources"
 *  heading, which would read as a page that lost its data. */
export const NoCitations: Story = { args: { turn: turn({ citations: [] }) } }

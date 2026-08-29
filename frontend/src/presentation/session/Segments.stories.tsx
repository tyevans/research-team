import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import type { Message } from '@domain/conversation/message.ts'
import { segmentTranscript } from '@domain/conversation/transcript.ts'

import { Segments } from './Segments.tsx'

/** A transcript's segments, and the two shapes it folds messages into.
 *
 * `segmentTranscript` runs consecutive tool activity together into one
 * `toolRun` and leaves everything else as its own `message`. That is the whole
 * of the transcript's structure, and the fold is what keeps a turn that made
 * eleven tool calls from burying the sentence either side of it.
 *
 * **The tool branches are why this page exists.** `Conversation` and
 * `Compaction` both render `Segments`, and between them they had exercised
 * user and assistant messages only — a tool run, an errored tool result and a
 * run whose calls are missing had never been drawn by anything. Each has its
 * own dressing (`.msg-tool`, `.msg-tool.errored` and its own background), so
 * "never rendered" also meant "never swept for contrast".
 *
 * Three rules worth the page:
 *
 * - **A run is folded shut and says how many.** The label carries the count
 *   and the tool names, so a reader decides whether to open it without
 *   opening it. `plural` is why `OneCall` exists — "1 tool calls" is the kind
 *   of thing that ships and stays.
 * - **An error on any message in a run surfaces on the closed run.**
 *   `segmentHasError` looks inside, because a failure hidden behind a fold a
 *   reader had no reason to open is a failure they will not find.
 * - **A run with no calls counts its messages instead.** Results arrive as
 *   their own messages, so a replay that starts mid-turn can produce a run
 *   whose calls are simply not in the log — and `tally.total || messages.length`
 *   is what stops that rendering as "0 tool calls".
 */
const meta: Meta = {
  title: 'session/Segments',
}

export default meta

type Story = StoryObj

const message = (over: Partial<Message> & { role: Message['role'] }): Message => ({
  content: '',
  toolCalls: [],
  name: null,
  artifact: null,
  isError: false,
  ...over,
})

const useFolds = (initial: readonly string[] = []) => {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set(initial))
  return {
    open,
    onToggle: (key: string) =>
      setOpen((current) => {
        const next = new Set(current)
        if (next.has(key)) next.delete(key)
        else next.add(key)
        return next
      }),
  }
}

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 720 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

const Live = ({ messages, openKeys }: { messages: readonly Message[]; openKeys?: string[] }) => {
  const folds = useFolds(openKeys)
  return <Segments segments={segmentTranscript(messages)} {...folds} />
}

const ASK = message({ role: 'user', content: 'Which provinces did the tetrarchy create?' })
const ANSWER = message({
  role: 'assistant',
  content: 'None directly — the provincial subdivision was a separate reform.',
})

const CALL = message({
  role: 'assistant',
  content: '',
  toolCalls: [{ name: 'search_corpus', args: { query: 'Diocletian provinces', limit: 8 } }],
})
const RESULT = message({ role: 'tool', content: '8 passages, 3 above threshold.' })

/** Messages either side of a folded run — the ordinary shape of a turn. */
export const AFoldedRun: Story = {
  render: () => (
    <Frame heading="a turn with tool calls, folded">
      <Live messages={[ASK, CALL, RESULT, ANSWER]} />
    </Frame>
  ),
}

/** The same run, opened. The tool call's arguments and its result are both
 *  inside — the fold hides detail, not evidence. */
export const AnOpenRun: Story = {
  render: () => (
    <Frame heading="the same run, opened">
      <Live messages={[ASK, CALL, RESULT, ANSWER]} openKeys={['run:1']} />
    </Frame>
  ),
}

/** **An error inside a folded run surfaces on the fold.**
 *
 *  `segmentHasError` looks inside the run, because a failure hidden behind a
 *  fold a reader had no reason to open is a failure they will not find. The
 *  chip is on the closed label; opening it shows which call failed. */
export const AFailedRun: Story = {
  render: () => (
    <Frame heading="a run containing a failure, still folded">
      <Live
        messages={[
          ASK,
          CALL,
          message({ role: 'tool', content: 'fetch: 503 from the source', isError: true }),
          ANSWER,
        ]}
      />
    </Frame>
  ),
}

/** The same failure, opened — where the errored result gets its own dressing.
 *
 *  `.msg-tool.errored` has a border and a background of its own, and neither
 *  had ever been rendered by a story before this one. */
export const AFailedRunOpen: Story = {
  render: () => (
    <Frame heading="the failure, opened">
      <Live
        messages={[
          ASK,
          CALL,
          message({ role: 'tool', content: 'fetch: 503 from the source', isError: true }),
          ANSWER,
        ]}
        openKeys={['run:1']}
      />
    </Frame>
  ),
}

/** Several calls run together into one fold.
 *
 *  This is what the fold is for: eleven calls between a question and its
 *  answer would otherwise bury both. The label names them so a reader can
 *  decide without opening. */
export const ALongRun: Story = {
  render: () => (
    <Frame heading="six calls in one run">
      <Live
        messages={[
          ASK,
          ...[
            'search_corpus',
            'read_file',
            'read_file',
            'search_corpus',
            'write_file',
            'read_file',
          ].flatMap((name) => [
            message({ role: 'assistant', toolCalls: [{ name, args: { path: 'notes.md' } }] }),
            message({ role: 'tool', content: 'ok' }),
          ]),
          ANSWER,
        ]}
      />
    </Frame>
  ),
}

/** One call. "1 tool calls" is the kind of thing that ships and stays. */
export const OneCall: Story = {
  render: () => (
    <Frame heading="the singular">
      <Live messages={[ASK, CALL, RESULT, ANSWER]} />
    </Frame>
  ),
}

/** **A run whose calls are not in the log.**
 *
 *  Results arrive as their own messages, so a replay that starts mid-turn can
 *  produce a run with results and no calls. `tally.total || messages.length`
 *  is what stops that rendering as "0 tool calls" — a count of nothing, over a
 *  fold containing something. */
export const ResultsWithoutCalls: Story = {
  render: () => (
    <Frame heading="a replay that starts mid-turn">
      <Live
        messages={[
          message({ role: 'tool', content: '8 passages, 3 above threshold.' }),
          message({ role: 'tool', content: 'wrote notes/tetrarchy.md' }),
          ANSWER,
        ]}
      />
    </Frame>
  ),
}

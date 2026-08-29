import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Message } from '@domain/conversation/message.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { MessageId, ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { Conversation } from './Conversation.tsx'

/** The transcript — the most-read surface in the console.
 *
 * Four states and one rule, and the rule is the reason this page is worth
 * having.
 *
 * **`emptyDetail` defaults to a prompt to act, and not every caller can
 * fulfil it.** `Conversation.tsx` argues it: the default wording assumes a
 * composer sits below this pane, which is true on the session route and false
 * in `WorkerDrawer`, which reuses the component read-only. A caller that
 * inherits the default tells a reader to send a turn in a view with nowhere
 * to type. `EmptyWithAComposer` and `EmptyWithoutOne` are that pair, and they
 * are the only place the difference is visible — a component rendered in one
 * caller looks correct in both.
 *
 * The other states are ones a reader meets and cannot easily reproduce: a
 * failed turn, a tool call, the historical mode where the transcript is folded
 * to a past event, and — the two added on 2026-08-28 — a turn in flight, both
 * over an existing transcript and over an empty one.
 *
 * **The streaming pair is the reason this page earns its keep now.** Live
 * entries are the last items in the same list as recorded ones, differing only
 * in how they are drawn: an accent rail and a pulsing dot rather than a
 * separate boxed-off region below the pane. Whether that reads as "still
 * arriving" without reading as "a different kind of thing" is a judgement only
 * an eye can make, and these are where it is made.
 */
const meta: Meta = {
  title: 'session/Conversation',
}

export default meta

type Story = StoryObj

const message = (over: Partial<Message> & { role: Message['role'] }): Message => ({
  content: '',
  toolCalls: [],
  isError: false,
  ...over,
})

const view = (messages: readonly Message[]): SessionProjection => ({
  id: SessionId('7d41e0aa-1111-4111-8111-444444444444'),
  projectId: ProjectId('11111111-1111-4111-8111-111111111111'),
  holdsProject: true,
  knowledgeAttached: true,
  modelName: 'claude-opus-5',
  systemPrompt: null,
  turnIndex: messages.length,
  failedTurns: 0,
  forkedFrom: null,
  forkedAt: null,
  eventCount: 260,
  compactedThrough: null,
  compactionSummary: null,
  at: null,
  files: [],
  messages,
})

const streaming = (
  id: string,
  over: Partial<Omit<ActivityEntry, 'messageId'>> = {},
): ActivityEntry => ({
  messageId: MessageId(id),
  sessionId: SessionId('7d41e0aa-1111-4111-8111-444444444444'),
  kind: 'assistant',
  text: null,
  payload: {},
  ...over,
})

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)' }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    <div style={{ height: 360, display: 'flex', flexDirection: 'column' }}>{children}</div>
  </section>
)

const EXCHANGE: readonly Message[] = [
  message({ role: 'user', content: 'Which provinces did the tetrarchy actually create?' }),
  message({
    role: 'assistant',
    content:
      'None directly — the tetrarchy divided *rule*, and the provincial subdivision that followed was Diocletian’s separate reform. The two are usually collapsed together.',
  }),
  message({ role: 'user', content: 'Show me the sources for the second half.' }),
]

/** An ordinary exchange. The baseline the other stories are read against. */
export const AnExchange: Story = {
  render: () => (
    <Frame heading="a transcript">
      <Conversation view={view(EXCHANGE)} error={null} historicalAt={null} />
    </Frame>
  ),
}

/** **The pair the component's docstring is about.** An empty transcript, in a
 *  view that has a composer.
 *
 *  The default wording tells the reader to send the first turn, which is
 *  correct here and only here. */
export const EmptyWithAComposer: Story = {
  render: () => (
    <Frame heading="empty — a composer sits below">
      <Conversation view={view([])} error={null} historicalAt={null} />
    </Frame>
  ),
}

/** The same component in a read-only view.
 *
 *  `WorkerDrawer` renders this with no composer anywhere in it. Inheriting
 *  the default would tell a reader to do something the view cannot do — which
 *  is a worse empty state than saying nothing, because it reads as a broken
 *  control rather than as an absence.
 *
 *  What to check: the two stories differ in their second line, and this one
 *  contains no instruction. */
export const EmptyWithoutOne: Story = {
  render: () => (
    <Frame heading="empty — read-only, no composer">
      <Conversation
        view={view([])}
        error={null}
        historicalAt={null}
        emptyDetail="Nothing has been said in this session yet."
      />
    </Frame>
  ),
}

/** A turn that failed. An error is not an answer and must not read as one. */
export const AFailedTurn: Story = {
  render: () => (
    <Frame heading="a failed turn">
      <Conversation
        view={view([
          ...EXCHANGE.slice(0, 2),
          message({
            role: 'assistant',
            content: 'The model returned no content.',
            isError: true,
          }),
        ])}
        error={null}
        historicalAt={null}
      />
    </Frame>
  ),
}

/** Tool calls on an assistant turn. */
export const WithToolCalls: Story = {
  render: () => (
    <Frame heading="tool calls">
      <Conversation
        view={view([
          EXCHANGE[0]!,
          message({
            role: 'assistant',
            content: 'Let me look.',
            toolCalls: [
              { name: 'search_corpus', args: { query: 'Diocletian provinces', limit: 8 } },
              { name: 'read_file', args: { path: 'notes/tetrarchy.md' } },
            ],
          }),
          message({ role: 'tool', content: '8 passages, 3 above threshold.' }),
        ])}
        error={null}
        historicalAt={null}
      />
    </Frame>
  ),
}

/** Folded to a past event.
 *
 *  The transcript renders the same components in the same places whether it
 *  is live or historical — only the messages are older. `ScrubBar` is what
 *  says which, and this story exists so the pane below it can be checked for
 *  not contradicting that. */
export const Historical: Story = {
  render: () => (
    <Frame heading="scrubbed to event 40">
      <Conversation view={view(EXCHANGE.slice(0, 2))} error={null} historicalAt={40} />
    </Frame>
  ),
}

/** The pane could not load.
 *
 *  Distinct from an empty transcript, and it has to be: "nothing was said" and
 *  "we could not find out what was said" are different facts and a reader acts
 *  on them differently. */
export const Failed: Story = {
  render: () => (
    <Frame heading="could not load">
      <Conversation view={null} error="the server answered 503" historicalAt={null} />
    </Frame>
  ),
}

/** A turn arriving, under a transcript that already has some.
 *
 *  What to check: the live bubble sits in the same column with the same gap,
 *  border and background as the messages above it — one conversation with a
 *  live end, not two surfaces stacked. The rail and the dot are the only
 *  things that say it has not been recorded.
 *
 *  Both forms are here because they are styled differently on purpose: the
 *  prose renders as markdown, the tool-call line stays literal and monospaced.
 *  A summary this code assembled is not a document, and through a parser the
 *  underscores in a filename turn its middle italic. */
export const ATurnInFlight: Story = {
  render: () => (
    <Frame heading="a turn in flight">
      <Conversation
        view={view(EXCHANGE.slice(0, 2))}
        error={null}
        historicalAt={null}
        activity={[
          streaming('a1', {
            kind: 'tool',
            payload: {
              data: { tool_calls: [{ name: 'read_file', args: { path: 'notes/tetrarchy.md' } }] },
            },
          }),
          streaming('a2', {
            text: '## What the sources say\n\nLactantius is **hostile** and the two later\nepitomes both depend on him, so the agreement is not independent',
          }),
        ]}
      />
    </Frame>
  ),
}

/** A turn arriving into a session that has said nothing yet.
 *
 *  The state the change of 2026-08-28 came from. Before it, this rendered "No
 *  conversation yet." across the pane with a second box streaming prose
 *  underneath — the empty check counted only committed messages, and the
 *  stream was a sibling it could not see. What to check: no empty state. */
export const StreamingIntoAnEmptySession: Story = {
  render: () => (
    <Frame heading="streaming, nothing recorded yet">
      <Conversation
        view={view([])}
        error={null}
        historicalAt={null}
        emptyDetail="Nothing has been said in this session yet."
        activity={[streaming('a1', { text: 'Reading the unit files…' })]}
      />
    </Frame>
  ),
}

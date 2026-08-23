import { useState } from 'react'
import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ActivityEntry } from '@domain/activity/activity.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { MessageId, SessionId } from '@domain/shared/identifier.ts'

import { Timeline } from './Timeline.tsx'

/** The event log — the console's signature view, and the surface the whole
 *  palette is a legend for.
 *
 * `tokens.css` says the colour scheme exists for this: "event kinds carry the
 * only other colour in the UI, so the log reads as a legend for itself."
 * `EveryKind` is therefore the one page where that claim is checkable, and it
 * is also what puts all eight kinds through the axe sweep at once — which is
 * how the compaction pane's three AA failures were found one story earlier.
 *
 * Two behavioural rules worth the page:
 *
 * - **It is a `grid`, not a `listbox`, and that is an accessibility decision
 *   rather than a markup preference.** Each row carries a primary action
 *   (scrub to it) *and* a secondary one (fork here). `role="grid"` is the
 *   pattern that legitimately allows a focusable control inside a row, so the
 *   fork button can be reached from the keyboard; a listbox would have forced
 *   it to be hidden from assistive technology.
 * - **Cancellation outranks classification.** `kindOf` checks
 *   `isCancellation` first, so a cancelled turn does not read as a failure —
 *   somebody stopping a run on purpose and a run falling over are different
 *   events, and the log is where that distinction has to survive.
 *
 * `classifyEventType` buckets by substring rather than enumerating, "so an
 * event type introduced later gets a sane colour instead of vanishing into a
 * default". `AnUnknownEvent` is that case: a type this build has never seen
 * still gets a row, a colour and readable prose.
 */
const meta: Meta = {
  title: 'session/Timeline',
}

export default meta

type Story = StoryObj

const entry = (
  index: number,
  type: string,
  summary: string,
  over: Partial<LogEntry> = {},
): LogEntry => ({
  index: EventIndex(index),
  type,
  occurredAt: `2026-08-21T09:${String(10 + index).padStart(2, '0')}:00Z`,
  summary,
  path: null,
  turnIndex: Math.floor(index / 3),
  isError: false,
  cancelled: null,
  ...over,
})

/** One of every bucket `classifyEventType` declares, in the order the rules
 *  test them. */
const EVERY_KIND: readonly LogEntry[] = [
  entry(1, 'SessionStarted', 'session opened on project ancient-rome'),
  entry(2, 'MessageSent', 'which provinces did the tetrarchy create?'),
  entry(3, 'ToolCalled', 'search_corpus · "Diocletian provinces"'),
  entry(4, 'FileWritten', 'notes/tetrarchy.md', { path: 'notes/tetrarchy.md' }),
  entry(5, 'TurnCompleted', 'answered in four paragraphs'),
  entry(6, 'ContextCompacted', 'the first 40 messages became a summary'),
  entry(7, 'TurnFailed', 'the model returned no content', { isError: true }),
  entry(8, 'SessionForked', 'forked at event 5'),
  entry(9, 'SomethingThisBuildHasNeverSeen', 'an event type from a newer backend'),
]

const activity = (text: string): ActivityEntry => ({
  messageId: MessageId('11111111-1111-4111-8111-111111111111'),
  sessionId: SessionId('7d41e0aa-1111-4111-8111-444444444444'),
  kind: 'assistant',
  text,
  payload: null,
})

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 460 }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    <div style={{ height: 420, display: 'flex', flexDirection: 'column' }}>{children}</div>
  </section>
)

const Live = ({
  log,
  fresh = new Map(),
  discarded = new Map(),
  at = null,
}: {
  log: readonly LogEntry[]
  fresh?: ReadonlyMap<EventIndex, number>
  discarded?: ReadonlyMap<EventIndex, readonly ActivityEntry[]>
  at?: number | null
}) => {
  const [scrub, setScrub] = useState<ScrubPoint>(
    at === null ? ScrubPoint.head() : ScrubPoint.at(EventIndex(at)),
  )
  return (
    <Timeline
      log={log}
      scrub={scrub}
      fresh={fresh}
      discarded={discarded}
      onSelect={setScrub}
      onFork={() => undefined}
    />
  )
}

/** **The legend, as one page.** Every kind the classifier declares, including
 *  one it has never seen.
 *
 *  The claim to check: a reader who has learnt these colours in the log knows
 *  them everywhere else in the console, because nothing else spends colour.
 *  If two buckets here are hard to tell apart, that is the legend failing at
 *  its only job. */
export const EveryKind: Story = {
  render: () => (
    <Frame heading="every event kind">
      <Live log={EVERY_KIND} />
    </Frame>
  ),
}

/** **Cancellation outranks classification.**
 *
 *  Both rows below are `TurnFailed`. One was cancelled by a person and one
 *  fell over. `kindOf` checks `isCancellation` first so they do not share a
 *  colour — stopping a run deliberately and a run breaking are different
 *  events, and a log that conflated them would report every deliberate stop as
 *  a fault. */
export const CancelledAgainstFailed: Story = {
  render: () => (
    <Frame heading="a cancelled turn is not a failed one">
      <Live
        log={[
          entry(1, 'MessageSent', 'start the extraction'),
          entry(2, 'TurnFailed', 'stopped by a reader', { cancelled: true }),
          entry(3, 'MessageSent', 'try again'),
          entry(4, 'TurnFailed', 'the model returned no content', { isError: true }),
        ]}
      />
    </Frame>
  ),
}

/** A row scrubbed to. The selection is the log's primary action, so it has to
 *  be unmistakable at a glance down a long column. */
export const Scrubbed: Story = {
  render: () => (
    <Frame heading="pinned to event 5">
      <Live log={EVERY_KIND} at={5} />
    </Frame>
  ),
}

/** Rows that arrived while the reader was looking.
 *
 *  `fresh` marks them so a live log does not silently grow under the eye. */
export const FreshRows: Story = {
  render: () => (
    <Frame heading="three rows just arrived">
      <Live
        log={EVERY_KIND}
        fresh={
          new Map([
            [EventIndex(7), 1],
            [EventIndex(8), 1],
            [EventIndex(9), 1],
          ])
        }
      />
    </Frame>
  ),
}

/** A failed turn with the content it had produced before it fell over.
 *
 *  `discarded` is the last failed turn's provisional text. It carries no index
 *  of its own, so the client pins it to the row a live frame would have pinned
 *  it to — which is why it is shown *under* the failure rather than beside
 *  it. */
export const DiscardedContent: Story = {
  render: () => (
    <Frame heading="what a failed turn had written">
      <Live
        log={EVERY_KIND}
        discarded={
          new Map([
            [
              EventIndex(7),
              [activity('The tetrarchy divided rule between two Augusti and two Caes')],
            ],
          ])
        }
      />
    </Frame>
  ),
}

/** An event type this build has never heard of.
 *
 *  `classifyEventType` buckets by substring precisely so a backend that grows
 *  a new event does not make rows vanish. The row is present, coloured and
 *  readable — `humaniseEventType` turns PascalCase into prose, so even an
 *  unrecognised type reads as words rather than as an identifier. */
export const AnUnknownEvent: Story = {
  render: () => (
    <Frame heading="an event from a newer backend">
      <Live log={[entry(1, 'SomethingThisBuildHasNeverSeen', 'and its summary')]} />
    </Frame>
  ),
}

/** Nothing yet. */
export const EmptyLog: Story = {
  render: () => (
    <Frame heading="no events">
      <Live log={[]} />
    </Frame>
  ),
}

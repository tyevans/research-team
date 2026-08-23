import type { Meta, StoryObj } from '@storybook/react-vite'

import type { LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { ScrubBar } from './ScrubBar.tsx'

/** The bar that says whether you are reading now or reading the past.
 *
 * **The one rule worth checking here is that the two modes do not look
 * alike.** A transcript scrubbed to event 40 of 260 renders the same
 * components, in the same places, as a transcript following the head — the
 * messages are simply older. If this bar does not say which is which, every
 * other surface on the page is quietly lying about how current it is, and a
 * reader can act on a stale file tree without ever being told.
 *
 * `Historical` and `Live` are that comparison. The historical bar gets its own
 * class, an accent dot, the words "time travel" and a way back; the live bar
 * gets none of those. Anything that makes the two converge is the defect.
 *
 * `head` is `SessionProjection | null`, and `null` is not a placeholder — it is
 * what a first paint has before the projection resolves. `Loading` is that
 * state, and it is the one where the bar has the least to say and the most
 * opportunity to say something wrong.
 */
const meta: Meta = {
  title: 'session/ScrubBar',
}

export default meta

type Story = StoryObj

const entry = (index: number, type: string, summary: string): LogEntry => ({
  index: EventIndex(index),
  type,
  occurredAt: '2026-08-20T09:14:00Z',
  summary,
  path: null,
  turnIndex: Math.floor(index / 4),
  isError: false,
  cancelled: null,
})

const LOG: readonly LogEntry[] = [
  entry(1, 'SessionStarted', 'session opened'),
  entry(2, 'MessageSent', 'what were the tetrarchy’s four capitals?'),
  entry(3, 'ToolCalled', 'search the corpus'),
  entry(4, 'TurnCompleted', 'answered in four paragraphs'),
  entry(5, 'MessageSent', 'and what happened to Nicomedia?'),
  entry(6, 'FileWritten', 'notes/tetrarchy.md'),
]

const head = (over: Partial<SessionProjection> = {}): SessionProjection => ({
  id: SessionId('7d41e0aa-1111-2222-3333-444444444444'),
  projectId: ProjectId('11111111-1111-4111-8111-111111111111'),
  holdsProject: true,
  knowledgeAttached: true,
  modelName: 'claude-opus-5',
  systemPrompt: null,
  turnIndex: 2,
  failedTurns: 0,
  forkedFrom: null,
  forkedAt: null,
  eventCount: 260,
  compactedThrough: null,
  compactionSummary: null,
  at: null,
  files: [],
  messages: [],
  ...over,
})

const noop = () => undefined

const Frame = ({ children }: { children: React.ReactNode }) => (
  <div style={{ padding: 'var(--space-3)', background: 'var(--bg)' }}>{children}</div>
)

/** Following the log. No accent, no "time travel", no way back — because
 *  there is nowhere to go back from. */
export const Live: Story = {
  render: () => (
    <Frame>
      <ScrubBar
        head={head()}
        log={LOG}
        scrub={ScrubPoint.head()}
        loading={false}
        onSelect={noop}
        onFork={noop}
        onEndSession={noop}
      />
    </Frame>
  ),
}

/** **Pinned to the past, and it must be obvious.** Compare with `Live`
 *  directly above.
 *
 *  What changes: the `historical` class on the bar, an accent dot, the words
 *  "time travel", and a description of the event being sat on. What must not
 *  change is the reader's ability to get back — a time-travel state with no
 *  exit is a console that looks broken rather than one that looks pinned. */
export const Historical: Story = {
  render: () => (
    <Frame>
      <ScrubBar
        head={head()}
        log={LOG}
        scrub={ScrubPoint.at(EventIndex(3))}
        loading={false}
        onSelect={noop}
        onFork={noop}
        onEndSession={noop}
      />
    </Frame>
  ),
}

/** The two together, which is the only arrangement the rule can be judged in.
 *
 *  Separately each bar looks deliberate. The question is whether a reader who
 *  sees only one of them can tell which one it is. */
export const LiveAgainstHistorical: Story = {
  render: () => (
    <Frame>
      <div style={{ display: 'grid', gap: 'var(--space-3)' }}>
        <ScrubBar
          head={head()}
          log={LOG}
          scrub={ScrubPoint.head()}
          loading={false}
          onSelect={noop}
          onFork={noop}
          onEndSession={noop}
        />
        <ScrubBar
          head={head()}
          log={LOG}
          scrub={ScrubPoint.at(EventIndex(3))}
          loading={false}
          onSelect={noop}
          onFork={noop}
          onEndSession={noop}
        />
      </div>
    </Frame>
  ),
}

/** Scrubbed to an event the log has not fetched yet.
 *
 *  `loading` and a historical point together: the bar knows where it is and
 *  not what is there. It must not fall back to describing the wrong event,
 *  and it must not go blank — a bar that empties while a fetch is in flight
 *  is the layout jump `Skeletons.tsx` argues about, on the one row that is
 *  always on screen. */
export const LoadingAPastPoint: Story = {
  render: () => (
    <Frame>
      <ScrubBar
        head={head()}
        log={LOG}
        scrub={ScrubPoint.at(EventIndex(180))}
        loading
        onSelect={noop}
        onFork={noop}
        onEndSession={noop}
      />
    </Frame>
  ),
}

/** First paint: no projection yet.
 *
 *  `head` is `null` before the query resolves, so `totalEvents` has only the
 *  log's length to work with. The bar has the least to say here and the most
 *  room to say something wrong — a total that later jumps from 6 to 260 reads
 *  as the session having grown rather than as the console having learned. */
export const BeforeTheProjectionArrives: Story = {
  render: () => (
    <Frame>
      <ScrubBar
        head={null}
        log={LOG}
        scrub={ScrubPoint.head()}
        loading
        onSelect={noop}
        onFork={noop}
        onEndSession={noop}
      />
    </Frame>
  ),
}

/** A forked session with failed turns — the two chips the bar can carry at
 *  once, on the busiest bar the console draws. */
export const ForkedWithFailures: Story = {
  render: () => (
    <Frame>
      <ScrubBar
        head={head({
          forkedFrom: SessionId('aaaaaaaa-1111-2222-3333-444444444444'),
          forkedAt: 42,
          failedTurns: 3,
        })}
        log={LOG}
        scrub={ScrubPoint.head()}
        loading={false}
        onSelect={noop}
        onFork={noop}
        onEndSession={noop}
      />
    </Frame>
  ),
}

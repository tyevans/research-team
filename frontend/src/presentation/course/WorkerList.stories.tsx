import type { Meta, StoryObj } from '@storybook/react-vite'

import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import type { Roster, Worker } from '@domain/worker/worker.ts'

import { WorkerList, WorkerListUnavailable } from './WorkerList.tsx'

/** The four things this panel can say, side by side.
 *
 * They are on one page because the distinction between them is the whole
 * point of the component and is impossible to check one at a time: **"nothing
 * is running" and "the last poll failed and the roster it left was empty" look
 * almost identical and mean completely different things.** One is a claim
 * about now; the other is a claim about the last time anybody knew.
 *
 * Reaching these before the fetch moved out of `Workers` meant a fake
 * repository that answered once and then threw, plus a query invalidation to
 * make it poll again. That is why they were only ever seen in a unit test.
 */
const meta: Meta = {
  title: 'course/WorkerList',
}

export default meta

type Story = StoryObj

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

const worker = (over: Partial<Worker> = {}): Worker => ({
  kind: 'turn',
  ref: 'w1',
  detail: 'answering “does spacing help?”',
  sessionId: SESSION,
  parent: null,
  startedAt: null,
  ...over,
})

const roster = (workers: readonly Worker[], idle: readonly SessionId[] = []): Roster => ({
  projectId: PROJECT,
  workers,
  idleSessionIds: idle,
})

const Frame = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)', maxWidth: 520 }}>
    <h4 style={{ font: 'inherit', color: 'var(--fg-dim)', margin: '0 0 var(--space-2)' }}>
      {title}
    </h4>
    {children}
  </section>
)

const noop = () => {}

/** A run with a turn and an extraction under it. Extraction has no session, so
 *  it is text rather than a dead button — the one rule `Row` encodes. */
export const Busy: Story = {
  render: () => (
    <Frame title="Working">
      <WorkerList
        roster={roster([
          worker({ kind: 'run', ref: 'r1', detail: 'round 3 of 10', sessionId: SESSION }),
          worker({ kind: 'turn', ref: 't1', parent: 'r1' }),
          worker({
            kind: 'extraction',
            ref: 'x1',
            detail: 'reading syllabus.pdf',
            sessionId: null,
            parent: 'r1',
          }),
        ])}
        watching={null}
        onWatch={noop}
      />
    </Frame>
  ),
}

/** Nothing running, and the console knows that as a fact. */
export const Idle: Story = {
  render: () => (
    <Frame title="Idle">
      <WorkerList roster={roster([], [SESSION])} watching={null} onWatch={noop} />
    </Frame>
  ),
}

/** The two failure readings, together, because apart they are indistinguishable
 *  from the two above.
 *
 *  Stale-with-a-roster still lists what it last saw and marks it. Stale-and-
 *  empty says only what is known — "as of the last roster that arrived" —
 *  rather than the present-tense claim this panel exists to avoid making. */
export const AfterAFailedPoll: Story = {
  render: () => (
    <>
      <Frame title="Stale, with a roster to show">
        <WorkerList roster={roster([worker()])} stale watching={SESSION} onWatch={noop} />
      </Frame>
      <Frame title="Stale, and the last roster was empty">
        <WorkerList roster={roster([])} stale watching={null} onWatch={noop} />
      </Frame>
      <Frame title="No roster has ever arrived">
        <WorkerListUnavailable />
      </Frame>
    </>
  ),
}

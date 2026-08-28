import type { Meta, StoryObj } from '@storybook/react-vite'
import { useState } from 'react'

import type { ResearchRun, RunProgress } from '@domain/research/run.ts'
import { ProjectId, RunId, SessionId } from '@domain/shared/identifier.ts'

import { ResearchDisabledNotice, RunView } from './RunPanel.tsx'

/** A run going, a run finished, and a run that ended where nobody was looking.
 *
 * The distinction this panel exists to enforce is that **"stopped" must not
 * read as "finished"** — a run cannot decide it is done, and only
 * `queue_empty` means the work ran out. The endings are on one page for the
 * same reason `EntityStatus`'s are: the rule is trivial to state and can only
 * be checked by seeing them together.
 *
 * `Ended` is the state that was previously unreachable without a fake
 * repository answering a run and then `null` on the next poll: `gone` is a
 * fact about what this page *watched*, not about the run, so it can only come
 * from outside the view.
 */
const meta: Meta = {
  title: 'course/RunView',
  parameters: { layout: 'padded' },
}

export default meta

type Story = StoryObj

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const run = (progress: RunProgress | null): ResearchRun => ({
  runId: RunId('33333333-3333-3333-3333-333333333333'),
  projectId: PROJECT,
  sessionId: SessionId('22222222-2222-2222-2222-222222222222'),
  progress,
})

const progress = (over: Partial<RunProgress> = {}): RunProgress => ({
  status: 'running',
  rounds: 3,
  turns: 3,
  findings: 7,
  stopReason: null,
  workingOn: 'does spacing help?',
  quietRounds: 0,
  failures: 0,
  budget: { maxRounds: 10, quietRounds: 3 },
  readOnly: false,
  ...over,
})

/** Each story owns the cap box, because an input nothing types into
 *  demonstrates nothing — the same reason the layout stories use `render`. */
const Live = ({
  value,
  gone = false,
  live = false,
}: {
  value: ResearchRun | null
  gone?: boolean
  live?: boolean
}) => {
  const [cap, setCap] = useState('')
  return (
    <RunView
      run={value}
      gone={gone}
      live={live}
      cap={cap}
      onCap={setCap}
      starting={false}
      stopping={false}
      onStart={() => {}}
      onStop={() => {}}
    />
  )
}

export const NoRun: Story = { render: () => <Live value={null} /> }

export const Running: Story = { render: () => <Live value={run(progress())} live /> }

/** Under a policy that floors fetch at ask. The chip is the only thing that
 *  says so, and it is easy to lose against the status chip beside it. */
export const ReadOnly: Story = {
  render: () => <Live value={run(progress({ readOnly: true }))} live />,
}

/** The work ran out. The only ending that should read as finished. */
export const QueueEmpty: Story = {
  render: () => <Live value={run(progress({ status: 'stopped', stopReason: 'queue_empty' }))} />,
}

/** Stopped, and not because it was done. */
export const StoppedShort: Story = {
  render: () => (
    <>
      <Live value={run(progress({ status: 'stopped', stopReason: 'max_rounds' }))} />
      <Live value={run(progress({ status: 'stopped', stopReason: 'no_new_findings' }))} />
      <Live value={run(progress({ status: 'stopped', stopReason: 'error_rate', failures: 4 }))} />
    </>
  ),
}

/** It left the live route and this page never saw why. Honest, rather than
 *  quietly retracting an ending nobody read. */
export const Ended: Story = { render: () => <Live value={null} gone /> }

export const Disabled: Story = { render: () => <ResearchDisabledNotice /> }

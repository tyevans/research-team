import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { AuthoringRun, AuthoringStatus } from '@domain/knowledge/authoring.ts'

import { AuthoringBar } from './AuthoringBar.tsx'

const run = (over: Partial<AuthoringRun> = {}): AuthoringRun => ({
  runId: 'r1',
  status: 'done',
  kind: 'path',
  targets: ['rome', 'carthage', 'complete'],
  completed: ['rome', 'carthage', 'complete'],
  sessions: ['s1', 's2', 's3'],
  current: null,
  failures: [],
  ...over,
})

const show = (props: Partial<Parameters<typeof AuthoringBar>[0]> = {}) =>
  render(
    <AuthoringBar
      status={null}
      areaSlug={null}
      areaTitle={null}
      pathLength={2}
      pending={false}
      stopping={false}
      error={null}
      onAuthor={() => {}}
      onCancel={() => {}}
      {...props}
    />,
  )

const running = (over: Partial<AuthoringRun> = {}): AuthoringStatus => ({
  current: run({
    status: 'running',
    completed: ['rome'],
    sessions: ['s1'],
    current: 'carthage',
    ...over,
  }),
  last: null,
})

describe('the stop control', () => {
  it('is absent when nothing is running', () => {
    // A control that is always there and does nothing most of the time trains
    // the reader to ignore it.
    show({ status: { current: null, last: run() } })

    expect(screen.queryByRole('button', { name: /stop writing/i })).not.toBeInTheDocument()
  })

  it('appears while a run is in flight, and is the one live control', () => {
    // The write buttons are disabled for exactly the period the stop exists,
    // which is the whole argument for showing it only then.
    show({ status: running() })

    expect(screen.getByRole('button', { name: /stop writing/i })).toBeEnabled()
    expect(screen.getByRole('button', { name: /write every course/i })).toBeDisabled()
  })

  it('asks to stop when pressed', async () => {
    const onCancel = vi.fn()
    show({ status: running(), onCancel })

    await userEvent.click(screen.getByRole('button', { name: /stop writing/i }))

    expect(onCancel).toHaveBeenCalledOnce()
  })

  it('cannot be pressed twice while the first press is in flight', async () => {
    show({ status: running(), stopping: true })

    expect(screen.getByRole('button', { name: /stopping/i })).toBeDisabled()
  })
})

describe('how a finished run is reported', () => {
  it('says nothing extra about an ordinary finish', () => {
    // The count already says how it went. A "done" label on every successful
    // run is noise on the ninety-nine that were fine.
    show({ status: { current: null, last: run() } })

    expect(screen.getByText(/wrote 3 of 3/i)).toBeInTheDocument()
    expect(screen.queryByText(/stopped|interrupted|failed/i)).not.toBeInTheDocument()
  })

  it('names a stop as a stop rather than a failure', () => {
    // A cancelled run and a failed one leave the same partial set of courses
    // behind, which is why reporting one as the other misreads both.
    show({
      status: {
        current: null,
        last: run({ status: 'cancelled', completed: ['rome'], sessions: ['s1'] }),
      },
    })

    expect(screen.getByText(/last run stopped/i)).toBeInTheDocument()
  })

  it('spells out a run a restart interrupted', () => {
    // The one status a reader cannot guess: it is neither something they did
    // nor something the model did.
    show({
      status: {
        current: null,
        last: run({ status: 'interrupted', completed: ['rome'], sessions: ['s1'] }),
      },
    })

    expect(screen.getByText(/interrupted by a restart/i)).toBeInTheDocument()
  })

  it('still links every course a stopped run wrote', () => {
    // The point of stopping rather than killing the server. These courses
    // exist, in that session's workspace, and this link is the only way in.
    show({
      status: {
        current: null,
        last: run({ status: 'cancelled', completed: ['rome'], sessions: ['s1'] }),
      },
    })

    expect(screen.getByRole('link', { name: 'rome' })).toHaveAttribute(
      'href',
      expect.stringContaining('s1'),
    )
  })

  it('counts the targets a stopped run never started', () => {
    // Otherwise invisible: "wrote 1 of 3" and an empty failure list account
    // for two of the three, and say nothing about the third.
    show({
      status: {
        current: null,
        last: run({ status: 'cancelled', completed: ['rome'], sessions: ['s1'] }),
      },
    })

    expect(screen.getByText(/2 never started/i)).toBeInTheDocument()
  })

  it('does not count anything as unstarted when a done run lost a target', () => {
    // A `done` run reached the end of its list. Its failures are named
    // separately, and adding "0 never started" beside them would be a second
    // sentence saying nothing.
    show({
      status: {
        current: null,
        last: run({
          completed: ['rome', 'complete'],
          sessions: ['s1', 's3'],
          failures: [{ target: 'carthage', detail: 'the model refused' }],
        }),
      },
    })

    expect(screen.queryByText(/never started/i)).not.toBeInTheDocument()
    expect(screen.getByText(/carthage: the model refused/i)).toBeInTheDocument()
  })
})

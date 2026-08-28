import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { ResearchRun, RunProgress } from '@domain/research/run.ts'
import { ProjectId, RunId, SessionId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { RunView } from './RunPanel.tsx'

/** The one claim this panel makes in the present tense.
 *
 * `RunPanel.tsx` had no test file at all; this covers the tense of the working
 * line and nothing else, because that is the part that was wrong. The rest of
 * the panel — the endings, the chips, the stop control — is checked in
 * `RunView.stories.tsx`, where the whole point is seeing three endings beside
 * each other, which no assertion replaces.
 *
 * `RunView` rather than `RunPanel`: `live` is a fact about what the *page*
 * watched rather than about the run, so it only exists as a prop. Driving it
 * through the container would mean a fake repository answering a run and then
 * `null`, to establish the same two booleans by a longer road.
 */
const run = (over: Partial<RunProgress> = {}): ResearchRun => ({
  runId: RunId('33333333-3333-3333-3333-333333333333'),
  projectId: ProjectId('11111111-1111-1111-1111-111111111111'),
  sessionId: SessionId('22222222-2222-2222-2222-222222222222'),
  progress: {
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
  },
})

/** The counters hang their explanations off tooltips, and a tooltip with no
 *  host renders nothing — deliberately, so a layer whose host is missing is
 *  invisible rather than escaping to `document.body`. That makes the host a
 *  precondition of rendering this panel at all rather than scenery. */
const show = (value: ResearchRun, live: boolean) =>
  render(
    <OverlayHost>
      <RunView
        run={value}
        gone={false}
        live={live}
        cap=""
        onCap={() => {}}
        starting={false}
        stopping={false}
        onStart={() => {}}
        onStop={() => {}}
      />
    </OverlayHost>,
  )

it('says a live run is working on its topic', () => {
  show(run(), true)

  expect(screen.getByText(/working on/)).toBeInTheDocument()
  expect(screen.getByText('does spacing help?')).toBeInTheDocument()
})

it('puts the topic of a stopped run in the past tense', () => {
  // `workingOn` survives the run that set it, so a stopped run printed
  // "working on does spacing help?" directly above a box saying it had
  // stopped. This panel's whole job is keeping "stopped" from reading as
  // anything else, and a present-tense claim about work in flight is the
  // reading it exists to prevent.
  //
  // Fails with the `live` ternary reverted: the line reads "working on" under
  // a `stopped` chip. `live` is the flag rather than `status`, because a run
  // that left the live route without a reason is stopped as far as this page
  // can honestly say, and `gone` renders no `progress.status` at all.
  show(run({ status: 'stopped', stopReason: 'queue_empty' }), false)

  expect(screen.getByText(/last worked on/)).toBeInTheDocument()
  expect(screen.queryByText(/working on/)).not.toBeInTheDocument()
  expect(screen.getByText('does spacing help?')).toBeInTheDocument()
})

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { EventIndex } from '@domain/session/event-index.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { ProjectId } from '@domain/shared/identifier.ts'
import type { SessionProjection } from '@domain/session/session.ts'

import { ScrubBar } from './ScrubBar.tsx'

/** What the bar promises about where the view is anchored.
 *
 * Named by `docs/component-system-spec.md` §10 among phase 4's prerequisites.
 * It is the cheapest of the six and the one whose defects would be loudest,
 * because every control it renders is conditional: which actions exist at all
 * depends on whether the reader is at HEAD, and whether this session still
 * holds its project.
 *
 * The claim worth testing is not that a button appears. It is that **a control
 * is absent when it could not work** -- "Fork here" on a session that is not
 * scrubbed anywhere, "End session" on a project another session has taken
 * over. A disabled button would be the weaker answer and this component
 * already chose the stronger one; nothing asserted it.
 *
 * **Proved red** against three breaks: the `End session` condition widened to
 * `head?.projectId` alone (fails the two cases about holding and about
 * position); `Back to live` pinning `ScrubPoint.at(total)` instead of
 * `head()`; and the `not held` chip removed. The first taking down two cases
 * is the point rather than a coupling -- one condition carries both rules, so
 * a single careless edit to it loses both.
 *
 * **What this does not assert:** the summary strings. `describeHead` and
 * `describeHistorical` are string builders over `plural` and
 * `humaniseEventType`, both tested where they live, and pinning their exact
 * output here would make this file fail every time somebody improves a
 * sentence.
 */

const projection = (over: Partial<SessionProjection> = {}): SessionProjection =>
  ({
    eventCount: 3,
    turnIndex: 1,
    files: [],
    modelName: 'claude',
    failedTurns: 0,
    projectId: null,
    holdsProject: false,
    knowledgeAttached: false,
    ...over,
  }) as unknown as SessionProjection

const entry = (index: number): LogEntry => ({
  index: EventIndex(index),
  type: 'FileWritten',
  occurredAt: '2026-08-10T12:00:00Z',
  summary: `event ${index}`,
  path: null,
  turnIndex: null,
  isError: false,
  cancelled: null,
})

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const LOG = [entry(1), entry(2), entry(3)]

const bar = (over: Partial<Parameters<typeof ScrubBar>[0]> = {}) =>
  render(
    <ScrubBar
      head={projection()}
      log={LOG}
      scrub={ScrubPoint.head()}
      loading={false}
      onSelect={vi.fn()}
      onFork={vi.fn()}
      onEndSession={vi.fn()}
      {...over}
    />,
  )

it('says whether the log is growing underneath the reader', () => {
  const { unmount } = bar()
  // "live · head" and "time travel" are different *states*, not different
  // numbers, because the difference a reader needs first is whether what they
  // are looking at will change while they look at it.
  expect(screen.getByText('live · head')).toBeInTheDocument()
  unmount()

  bar({ scrub: ScrubPoint.at(EventIndex(2)) })
  expect(screen.getByText('time travel')).toBeInTheDocument()
})

it('offers fork and back-to-live only when there is somewhere to go back from', () => {
  const { unmount } = bar()

  // At HEAD both are meaningless: forking here is starting a session from the
  // present, which is what the project page already does, and "back to live"
  // is where you are. Absent rather than disabled.
  expect(screen.queryByRole('button', { name: 'Fork here' })).not.toBeInTheDocument()
  expect(screen.queryByRole('button', { name: 'Back to live' })).not.toBeInTheDocument()
  unmount()

  bar({ scrub: ScrubPoint.at(EventIndex(2)) })
  expect(screen.getByRole('button', { name: 'Fork here' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Back to live' })).toBeInTheDocument()
})

it('sends back-to-live to HEAD rather than to the newest event', async () => {
  const user = userEvent.setup()
  const onSelect = vi.fn()
  bar({ scrub: ScrubPoint.at(EventIndex(2)), onSelect })

  await user.click(screen.getByRole('button', { name: 'Back to live' }))

  // `ScrubPoint.head()`, not `at(3)`. They render the same content this
  // instant and mean different things the next: HEAD follows the log as it
  // grows, and event 3 is a pin that happens to sit at the end right now.
  expect(onSelect).toHaveBeenCalledWith(ScrubPoint.head())
})

it('offers to end the session only while this session still holds the project', () => {
  const held = { projectId: PROJECT, holdsProject: true }

  const { unmount } = bar({ head: projection(held) })
  expect(screen.getByRole('button', { name: 'End session' })).toBeInTheDocument()
  unmount()

  // Taken over by another session: ending it would release a lease this
  // session no longer has. The control is gone, and the chip below says why.
  const takenOver = bar({ head: projection({ projectId: PROJECT, holdsProject: false }) })
  expect(screen.queryByRole('button', { name: 'End session' })).not.toBeInTheDocument()
  takenOver.unmount()

  // No project at all: there is nothing to hand back.
  bar({ head: projection() })
  expect(screen.queryByRole('button', { name: 'End session' })).not.toBeInTheDocument()
})

it('does not offer to end the session from a historical position', () => {
  // Releasing is an act on the present. Offered while scrubbed, it reads as
  // "end the session as of event 2", which is not a thing that can happen.
  bar({
    head: projection({ projectId: PROJECT, holdsProject: true }),
    scrub: ScrubPoint.at(EventIndex(2)),
  })

  expect(screen.queryByRole('button', { name: 'End session' })).not.toBeInTheDocument()
})

it('says when work here no longer reaches the project', () => {
  bar({ head: projection({ projectId: PROJECT, holdsProject: false }) })

  // The sharpest fact this bar carries: another session has taken the project
  // over, so nothing written here will be passed on. Silence would leave a
  // reader typing into a session they believe is the project's.
  expect(screen.getByText('not held')).toBeInTheDocument()
})

it('says whether the agent has the graph its prompt promises', () => {
  const { unmount } = bar({ head: projection({ projectId: PROJECT, knowledgeAttached: true }) })
  expect(screen.getByText('graph on')).toBeInTheDocument()
  unmount()

  bar({ head: projection({ projectId: PROJECT, knowledgeAttached: false }) })
  expect(screen.getByText('graph off')).toBeInTheDocument()
})

it('shows no project chips at all when the session is not in a project', () => {
  bar({ head: projection() })

  expect(screen.queryByText(/^project /)).not.toBeInTheDocument()
  expect(screen.queryByText(/^graph /)).not.toBeInTheDocument()
})

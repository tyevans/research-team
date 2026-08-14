import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import { queryKeys } from '@application/queries/keys.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { Project } from '@domain/project/project.ts'
import type { SessionSummary } from '@domain/session/session.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'
import type { Roster, Worker } from '@domain/worker/worker.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { TreeView } from './TreeView.tsx'

/** The landing page's liveness chip, which had no test of any kind.
 *
 * Written with the slice that re-sourced it from the global roster, and the
 * request-count test below is the one that justifies that slice.
 *
 * **All seven proved red**, against the previous two-query `ProjectActivity.tsx`
 * restored from git: six failed on the chip never appearing, because the old
 * code never calls `everywhere` at all. That is a real failure but a cheap one,
 * so the count test was re-proved properly — with a throwaway copy of this file
 * whose fakes answered `research.current` and `workers.on` per project, so every
 * chip rendered and only the count could fail. It did: **`expected 1, got 6`**,
 * three drawn rows × two per-project reads. That is the number the slice buys
 * down, measured rather than argued.
 *
 * Rendered through `TreeView` rather than by calling the hook, because the
 * thing under test is "N mounted rows issue one request" and the mounting is
 * the virtualizer's, not a test's. jsdom is the right home: every assertion is
 * rendered text or a call count, and nothing here is a measurement.
 */

const ATLAS = ProjectId('11111111-1111-1111-1111-111111111111')
const SANDBOX = ProjectId('22222222-2222-2222-2222-222222222222')
const HARBOUR = ProjectId('33333333-3333-3333-3333-333333333333')
const SESSION = SessionId('44444444-4444-4444-4444-444444444444')

const NOW = Date.parse('2026-08-09T12:00:00Z')

const project = (id: ProjectId, name: string): Project => ({
  id,
  name,
  activeSessionId: null,
  tipAtEvent: 0,
  workflow: null,
  stage: null,
})

const session = (id: string, projectId: ProjectId): SessionSummary => ({
  id: SessionId(id),
  projectId,
  startedAt: '2026-08-09T09:00:00Z',
  turns: 0,
  files: 0,
  firstMessage: null,
  forkedFrom: null,
  forkedAt: null,
  failedTurns: 0,
})

const worker = (over: Partial<Worker> = {}): Worker => ({
  kind: 'turn',
  ref: SESSION,
  detail: 'turn 12',
  sessionId: SESSION,
  parent: null,
  startedAt: null,
  ...over,
})

const rosterOf = (projectId: ProjectId, workers: readonly Worker[]): Roster => ({
  projectId,
  workers,
  idleSessionIds: [],
})

/** Three projects, each with a session so the rows sort and draw, and one
 *  roster read the test controls. `research.current` is deliberately **not**
 *  answered: nothing on this page may reach for it any more, and a fake that
 *  answered it would hide a regression that reintroduced the call. */
const setup = (
  everywhere: () => Promise<readonly Roster[]>,
  projects: readonly Project[] = [
    project(ATLAS, 'atlas'),
    project(SANDBOX, 'sandbox'),
    project(HARBOUR, 'harbour'),
  ],
) => {
  const spy = vi.fn(everywhere)
  const sessions = projects.map((one, index) =>
    session(`aaaaaaa${index}-0000-0000-0000-00000000000${index}`, one.id),
  )
  const container = {
    now: () => NOW,
    sessions: {
      list: vi.fn().mockResolvedValue(sessions),
      tree: vi.fn().mockResolvedValue(sessions.map((row) => ({ ...row, children: [] }))),
    },
    projects: {
      list: vi.fn().mockResolvedValue(projects),
      presets: vi.fn().mockResolvedValue([]),
      create: vi.fn(),
      chooseWorkflow: vi.fn(),
      join: vi.fn(),
      delete: vi.fn(),
    },
    workers: { everywhere: spy },
    health: {
      summaries: vi.fn().mockResolvedValue({ healthy: true, following: true, failedEvents: 0 }),
      rebuildSummaries: vi.fn(),
    },
  } as unknown as AppContainer

  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <OverlayHost>{children}</OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return { ...render(<TreeView />, { wrapper }), client, everywhere: spy }
}

it('draws one chip per running kind, in the words the roster gives it', async () => {
  setup(() =>
    Promise.resolve([
      rosterOf(ATLAS, [worker({ kind: 'run' })]),
      rosterOf(SANDBOX, [worker({ kind: 'turn' })]),
      rosterOf(HARBOUR, [worker({ kind: 'extraction' })]),
    ]),
  )

  // `run running`, not `run · round 4`: the roster carries no round count, and
  // accepting that degradation is the decision the slice took. A test that
  // expected the old string would be asserting a backlog entry, not the code.
  expect(await screen.findByText('⟳ run running')).toBeInTheDocument()
  expect(await screen.findByText('⟳ turn running')).toBeInTheDocument()
  expect(await screen.findByText('⟳ extraction running')).toBeInTheDocument()
})

it('appends how long it has been running when the roster knows', async () => {
  setup(() => Promise.resolve([rosterOf(ATLAS, [worker({ startedAt: Date.now() - 30_000 })])]))

  // The suffix, not the exact number: `elapsed` reads the wall clock, and
  // pinning `30s` would make this fail on a slow machine rather than on a bug.
  expect(await screen.findByText(/^⟳ turn running · \d+s$/)).toBeInTheDocument()
})

it('prefers the run when a project has several things going', async () => {
  // The ordering the two-query version had for free, because it checked
  // `research.current` first and returned before it looked at the roster.
  // `everywhere()` documents no order within a roster, so this fails the moment
  // the lookup becomes `workers[0]` — the turn is deliberately first here.
  setup(() =>
    Promise.resolve([rosterOf(ATLAS, [worker({ kind: 'turn' }), worker({ kind: 'run' })])]),
  )

  expect(await screen.findByText('⟳ run running')).toBeInTheDocument()
  expect(screen.queryByText('⟳ turn running')).not.toBeInTheDocument()
})

it('draws no chip for a project the roster does not mention', async () => {
  // `everywhere()` omits projects with nothing running rather than sending an
  // empty roster for them, so absence is the ordinary answer and not a gap.
  setup(() => Promise.resolve([rosterOf(ATLAS, [worker({ kind: 'run' })])]))

  expect(await screen.findByText('⟳ run running')).toBeInTheDocument()
  expect(screen.queryByText(/⟳ turn running/)).not.toBeInTheDocument()
  expect(screen.getAllByText(/⟳/)).toHaveLength(1)
})

it('draws no chip and no error when the roster read fails', async () => {
  // A failed liveness read must not degrade the row: the row is still a working
  // link to four places, and an error where a chip would go says nothing a
  // reader can act on. `retry: false` is what keeps the failure to one request.
  const { everywhere } = setup(() => Promise.reject(new Error('nope')))

  expect(await screen.findByText('atlas')).toBeInTheDocument()
  await waitFor(() => expect(everywhere).toHaveBeenCalled())
  expect(screen.queryByText(/⟳/)).not.toBeInTheDocument()
  expect(screen.queryByText(/nope/)).not.toBeInTheDocument()
})

it('asks once for the whole page, however many rows are drawn', async () => {
  // **The assertion the slice exists for.** The previous implementation issued
  // `research.current` and `workers.on` per drawn row — six calls for these
  // three projects, and ~32 for the sixteen rows the virtualizer mounts at
  // eight visible, re-paid on every debounced log burst. Run against that
  // version this test fails on the count; run against this one the rows share
  // a single `queryKeys.runningAgents()` cache entry.
  const { everywhere } = setup(() =>
    Promise.resolve([
      rosterOf(ATLAS, [worker({ kind: 'run' })]),
      rosterOf(SANDBOX, [worker({ kind: 'turn' })]),
      rosterOf(HARBOUR, [worker({ kind: 'dispatch' })]),
    ]),
  )

  expect(await screen.findByText('⟳ run running')).toBeInTheDocument()
  expect(await screen.findByText('⟳ turn running')).toBeInTheDocument()
  expect(await screen.findByText('⟳ dispatch running')).toBeInTheDocument()
  expect(everywhere).toHaveBeenCalledTimes(1)
})

it('refreshes off the invalidation the landing page already fires', async () => {
  // **The cross-file coupling this slice chose to rely on, asserted rather than
  // commented.** `App.tsx:157-174` arms a `useFrameRefresh` while the route is
  // `home` and invalidates `queryKeys.allWorkers()` — `['workers']` — on a log
  // frame. `queryKeys.runningAgents()` is `['workers','all']`, deliberately
  // *under* that prefix (`keys.ts:40-46`), so the chip is refreshed by a path
  // the landing page already owns and needs no subscription of its own.
  //
  // This is what fails if anyone moves `runningAgents()` out from under the
  // prefix: the chip would then sit at whatever the first render saw until the
  // reader reloaded, and nothing else in the suite would notice.
  const { everywhere, client } = setup(() =>
    Promise.resolve([rosterOf(ATLAS, [worker({ kind: 'run' })])]),
  )

  expect(await screen.findByText('⟳ run running')).toBeInTheDocument()
  expect(everywhere).toHaveBeenCalledTimes(1)

  await client.invalidateQueries({ queryKey: queryKeys.allWorkers() })

  await waitFor(() => expect(everywhere).toHaveBeenCalledTimes(2))
})

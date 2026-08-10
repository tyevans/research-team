import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type {
  ExtractionRepository,
  ProjectRepository,
  ResearchRepository,
  WorkerRepository,
} from '@application/ports/repositories.ts'
import type { Course, StageProgress } from '@domain/project/course.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { FRAME_DEBOUNCE_MS } from '../shell/use-frame-refresh.ts'
import { CourseView } from './CourseView.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')
const OTHER = ProjectId('99999999-9999-9999-9999-999999999999')

const stage = (over: Partial<StageProgress> = {}): StageProgress => ({
  index: 1,
  id: 'step0.intake',
  name: 'Intake',
  kind: 'author',
  spine: 0,
  scopeLevel: 'course',
  status: 'current',
  outputs: [],
  gateDecisions: [],
  reviewerRole: null,
  findingsReport: null,
  ...over,
})

const course = (stages: readonly StageProgress[], position: number): Course => ({
  projectId: PROJECT,
  projectName: 'Spacing',
  holdingSessionId: null,
  preset: { id: 'hybrid.default', name: 'Hybrid', version: '1' },
  position,
  stageCount: stages.length,
  stages,
  findings: [],
  unimplementedChecks: [],
})

/** Two reads of the same project, before and after a stage advanced.
 *
 * The stage names differ so an assertion can tell which one is on screen: a
 * page that never re-read still shows "Intake", which is exactly the reported
 * bug and exactly what a count-based assertion would have missed.
 */
const beforeAdvance = course([stage({ name: 'Intake', status: 'current' })], 1)
const afterAdvance = course(
  [
    stage({ name: 'Intake', status: 'done' }),
    stage({ index: 2, id: 'step1.framing', name: 'Framing', status: 'current' }),
  ],
  2,
)

/** Mirrors `DocumentList.test.tsx`'s fake stream, so a live-update assertion
 *  drives the real `StreamProvider` fan-out rather than calling a prop. */
const fakeStream = () => {
  let listener: EventStreamListener | null = null
  const stream: EventStream = {
    connect: (received) => {
      listener = received
    },
    disconnect: () => {
      listener = null
    },
  }
  return {
    stream,
    pushProject: (
      projectId: string = PROJECT,
      change = 'StageAdvanced',
      decision: string | null = 'approve',
    ) =>
      act(() => {
        listener?.onFrame({ kind: 'project', projectId, change, decision })
      }),
    pushLog: () =>
      act(() => {
        listener?.onFrame({
          kind: 'log',
          sessionId: SessionId('cccccccc-cccc-cccc-cccc-cccccccccccc'),
          entry: {
            index: EventIndex(1),
            type: 'FileWritten',
            occurredAt: '2026-01-01T00:00:00Z',
            summary: '/a.md',
            path: '/a.md',
            turnIndex: null,
            isError: false,
            cancelled: null,
          },
        })
      }),
  }
}

/** The panes beside the rail each read something of their own, and none of it
 *  is what these tests are about. Stubbed quiet rather than mocked away: the
 *  view the application renders is the one worth asserting against, and a
 *  version of it with children removed could pass while the real page did
 *  not. */
const quietParts = () => ({
  workers: {
    everywhere: vi.fn<WorkerRepository['everywhere']>().mockResolvedValue([]),
    on: vi
      .fn<WorkerRepository['on']>()
      .mockResolvedValue({ projectId: PROJECT, workers: [], idleSessionIds: [] }),
  },
  research: { current: vi.fn<ResearchRepository['current']>().mockResolvedValue(null) },
  extractions: {
    on: vi.fn<ExtractionRepository['on']>().mockResolvedValue({ current: [], last: [] }),
  },
})

const renderCourse = (projects: Partial<ProjectRepository>, stream: EventStream) => {
  const container = { stream, projects, ...quietParts() } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>{children}</StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(<CourseView projectId={PROJECT} watching={null} onWatch={() => {}} />, { wrapper })
}

it('moves the rail when a stage advances, without a reload', async () => {
  // The reported bug. `advance_stage` appended `StageAdvanced` and this page
  // went on showing the stage it had read at mount until somebody refreshed --
  // half of it because the server's feed filtered `Project` streams out
  // entirely, half because this view subscribed to nothing.
  //
  // Asserting the new stage's *name*, not a refetch count: a page that
  // re-read and drew the old answer is the same defect to a reader, and a
  // count would call it fixed.
  const list = vi
    .fn<ProjectRepository['course']>()
    .mockResolvedValueOnce(beforeAdvance)
    .mockResolvedValue(afterAdvance)
  const feed = fakeStream()

  renderCourse({ course: list }, feed.stream)
  expect(await screen.findByText('Intake')).toBeInTheDocument()
  expect(screen.queryByText('Framing')).not.toBeInTheDocument()

  feed.pushProject()

  expect(await screen.findByText('Framing', {}, { timeout: 2_000 })).toBeInTheDocument()
})

it('draws a rail when a workflow is chosen, without a reload', async () => {
  // The sibling defect, and the reason the subscription is not filtered to
  // `StageAdvanced`. Before a workflow is selected the course route answers
  // 409 and this page says "No course to show"; `WorkflowSelected` is what
  // makes there be a course at all, so a frame filter naming only the advance
  // would leave the page reading its error until a reload.
  const list = vi
    .fn<ProjectRepository['course']>()
    .mockRejectedValueOnce(new Error('this project has no workflow'))
    .mockResolvedValue(beforeAdvance)
  const feed = fakeStream()

  renderCourse({ course: list }, feed.stream)
  expect(await screen.findByText(/no course to show/i)).toBeInTheDocument()

  feed.pushProject(PROJECT, 'WorkflowSelected', null)

  expect(await screen.findByText('Intake', {}, { timeout: 2_000 })).toBeInTheDocument()
})

it('re-reads once for a burst of project frames, not once each', async () => {
  // A run crossing several stage boundaries in quick succession commits a
  // frame each. Without the debounce that is one course read per frame for one
  // repaint.
  const list = vi.fn<ProjectRepository['course']>().mockResolvedValue(beforeAdvance)
  const feed = fakeStream()

  renderCourse({ course: list }, feed.stream)
  await screen.findByText('Intake')
  expect(list).toHaveBeenCalledTimes(1)

  feed.pushProject()
  feed.pushProject()
  feed.pushProject()

  await waitFor(() => expect(list).toHaveBeenCalledTimes(2))
  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(list).toHaveBeenCalledTimes(2)
})

it('ignores another project’s advance, and log frames', async () => {
  // A project frame names its project, so another project's advance can be
  // dropped without a read that would discover nothing changed. Log frames are
  // ignored for the reason `DocumentList` ignores them: the tree already
  // refetches on every one, and re-reading the course on every token of every
  // turn is a request per token for a rail that moves at stage boundaries.
  //
  // Stated plainly: this one passes with the subscription removed entirely. It
  // pins the *scope* of the fix, not the fix -- the two above are the red ones.
  const list = vi.fn<ProjectRepository['course']>().mockResolvedValue(beforeAdvance)
  const feed = fakeStream()

  renderCourse({ course: list }, feed.stream)
  await screen.findByText('Intake')

  feed.pushProject(OTHER)
  feed.pushLog()

  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(list).toHaveBeenCalledTimes(1)
})

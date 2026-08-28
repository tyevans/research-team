import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { ExtractionRepository } from '@application/ports/repositories.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { StreamProvider } from '../../shell/StreamProvider.tsx'
import { ExtractionPane } from './ExtractionPane.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const frame = (over: Record<string, unknown> = {}) => ({
  type: 'Extraction',
  project_id: PROJECT,
  source_id: 'notes',
  stage: 'extracting',
  detail: '',
  entities: null,
  relationships: null,
  domain: null,
  domain_confidence: null,
  index: null,
  total: null,
  model_calls: null,
  ...over,
})

/** A stream whose listener the test keeps, so frames can be pushed the way the
 *  real socket pushes them — through the provider's fan-out, not around it. */
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
    push: (payload: unknown) =>
      act(() => {
        listener?.onFrame({ kind: 'extraction', payload })
      }),
    reconnect: () =>
      act(() => {
        listener?.onReconnect(true)
      }),
  }
}

/** Mirrors `Workers.test.tsx`'s harness, plus the `StreamProvider` this pane
 *  reads its frames from. */
const renderWithContainer = (ui: ReactElement, parts: Partial<AppContainer>) => {
  const container = parts as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>{children}</StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

const emptyRepo = () => ({
  on: vi.fn<ExtractionRepository['on']>().mockResolvedValue({ current: [], last: [] }),
})

it('says nothing has run rather than showing an empty box', async () => {
  const extractions = emptyRepo()
  const { stream } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })

  expect(await screen.findByText(/No extraction has run on this project yet\./)).toBeInTheDocument()
})

it('shows the stages, the model calls and the counts as they arrive', async () => {
  const extractions = emptyRepo()
  const { stream, push } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })
  await screen.findByText(/No extraction has run/)

  push(frame({ stage: 'storing' }))
  push(frame({ stage: 'extracting', model_calls: 4 }))

  expect(screen.getByText('storing')).toBeInTheDocument()
  expect(screen.getByText(/model calls: 4/)).toBeInTheDocument()

  push(frame({ stage: 'extracted', entities: 31, relationships: 12, domain: 'ecology' }))

  expect(screen.getByText(/31 entities/)).toBeInTheDocument()
  expect(screen.getByText(/12 relationships/)).toBeInTheDocument()
  expect(screen.getByText(/ecology/)).toBeInTheDocument()
})

it('renders a zero confidence as a fallback warning, not as a score', async () => {
  // Zero means the classifier gave up. Printed as `0.00` it reads as a
  // confident low score, which is the misreading this render exists to stop.
  const extractions = emptyRepo()
  const { stream, push } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })
  await screen.findByText(/No extraction has run/)

  push(frame({ stage: 'extracted', domain: 'general', domain_confidence: 0 }))

  expect(screen.getByText(/fallback — treat the shape as unverified/)).toBeInTheDocument()
  expect(screen.queryByText(/0\.00/)).not.toBeInTheDocument()
})

it('says nothing about confidence when no classifier ran', async () => {
  // Null is a different fact from a low score: no classifier ran at all.
  const extractions = emptyRepo()
  const { stream, push } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })
  await screen.findByText(/No extraction has run/)

  push(frame({ stage: 'extracted', domain: 'ecology', domain_confidence: null }))

  expect(screen.getByText(/ecology/)).toBeInTheDocument()
  expect(screen.queryByText(/confidence/i)).not.toBeInTheDocument()
  expect(screen.queryByText(/fallback/)).not.toBeInTheDocument()
})

it('lists the consolidation pass under its position', async () => {
  const extractions = emptyRepo()
  const { stream, push } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })
  await screen.findByText(/No extraction has run/)

  push(frame({ stage: 'consolidating', detail: 'otter — merged into Lutra', index: 1, total: 9 }))
  push(frame({ stage: 'consolidating', detail: 'kelp — kept, no match', index: 2, total: 9 }))

  expect(screen.getByText(/2\/9/)).toBeInTheDocument()
  expect(screen.getByText('otter — merged into Lutra')).toBeInTheDocument()
  expect(screen.getByText('kelp — kept, no match')).toBeInTheDocument()
})

it('still has the merge verdicts after the extraction finishes', async () => {
  // The consolidation verdicts are the only record there is: nothing durable
  // stores them, which is the stated reason this disclosure exists at all. They
  // used to be rendered by the running section alone, so the moment a frame
  // arrived with a terminal stage the store moved the extraction to `last` and
  // every verdict left the screen -- a reader who looked away for the minute
  // the ingest took saw none of them, and the pane that calls itself "the only
  // account of what just happened" accounted for nothing.
  //
  // Fails with `MergeList` removed from `Last`: the disclosure opens on the
  // counts line and neither verdict is in the document.
  const extractions = emptyRepo()
  const { stream, push } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })
  await screen.findByText(/No extraction has run/)

  push(frame({ stage: 'consolidating', detail: 'otter — merged into Lutra', index: 1, total: 2 }))
  push(frame({ stage: 'consolidating', detail: 'kelp — kept, no match', index: 2, total: 2 }))
  push(frame({ stage: 'consolidated', detail: 'stored' }))

  // Gone from the screen entirely first, because the disclosure is collapsed:
  // history should not compete with a run in flight on a page they share.
  expect(screen.queryByText('otter — merged into Lutra')).not.toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { expanded: false }))
  expect(screen.getByText('otter — merged into Lutra')).toBeInTheDocument()
  expect(screen.getByText('kelp — kept, no match')).toBeInTheDocument()
})

it('keeps a failed extraction on screen with a failed tone', async () => {
  const extractions = emptyRepo()
  const { stream, push } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })
  await screen.findByText(/No extraction has run/)

  push(frame({ stage: 'failed', detail: 'the model refused' }))

  // The tone is claimed on the *summary*, which is what a reader sees without
  // opening anything -- and that is what this test is named for. It used to
  // anchor on the failure detail instead, which worked only because a closed
  // `<details>` still holds its content in the DOM. `Disclosure` renders
  // `null` while closed, so the old anchor is gone; the behaviour a reader
  // experiences is unchanged, since neither one showed the detail.
  const summary = screen.getByText(/The last extraction failed/)
  expect(summary.closest('.extraction-last')).toHaveClass('extraction-failed')

  // And the reason is one click away rather than absent, which is the half
  // that would otherwise go untested now that it is not in the DOM by default.
  await userEvent.click(screen.getByRole('button', { expanded: false }))
  expect(screen.getByText(/the model refused/)).toBeInTheDocument()
})

it('ignores another project’s frames', async () => {
  // The connection is application-wide: without the store's project filter
  // this pane would show another course's extraction.
  const extractions = emptyRepo()
  const { stream, push } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })
  await screen.findByText(/No extraction has run/)

  push(frame({ project_id: '99999999-9999-9999-9999-999999999999', stage: 'extracting' }))

  expect(screen.getByText(/No extraction has run/)).toBeInTheDocument()
})

it('refetches on reconnect, because a dropped frame cannot be replayed', async () => {
  const extractions = emptyRepo()
  const { stream, reconnect } = fakeStream()

  renderWithContainer(<ExtractionPane projectId={PROJECT} />, { extractions, stream })
  await screen.findByText(/No extraction has run/)

  expect(extractions.on).toHaveBeenCalledTimes(1)

  reconnect()

  expect(extractions.on).toHaveBeenCalledTimes(2)
})

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement, ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { GraphRepository, UsagesRepository } from '@application/ports/repositories.ts'
import type { EntityGroup } from '@domain/knowledge/entity-tree.ts'
import { emptyGraph } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { EntityTreeBrowser, EntityTreePane } from './EntityTreePane.tsx'

const projectId = ProjectId('11111111-1111-1111-1111-111111111111')

const groups: readonly EntityGroup[] = [
  { entityType: 'person', entities: [{ id: 'p1', name: 'Hinton', entityType: 'person' }] },
]

const props = {
  projectId,
  view: emptyGraph,
  groups,
  open: new Set(['person']),
  selected: null,
  loading: false,
  error: null as string | null,
  partial: false,
  filtered: false,
  onToggle: () => {},
  onSelect: () => {},
  onClose: () => {},
}

describe('EntityTreeBrowser', () => {
  it('lists the entities it was given', () => {
    render(<EntityTreeBrowser {...props} />)

    expect(screen.getByText('Hinton')).toBeInTheDocument()
  })

  /** The three empty states must stay three. A fetch that failed saying "this
   *  project has no entities" is the defect `GraphPane`'s own empty state was
   *  written to correct. */
  it('says the entities could not be read, rather than that there are none', () => {
    render(<EntityTreeBrowser {...props} groups={[]} error="network down" />)

    expect(screen.getByText(/could not be read/i)).toBeInTheDocument()
    expect(screen.queryByText(/nothing has been extracted/i)).not.toBeInTheDocument()
  })

  it('blames the filter when a filter is what emptied the list', () => {
    render(<EntityTreeBrowser {...props} groups={[]} filtered />)

    expect(screen.getByText(/nothing matched/i)).toBeInTheDocument()
    expect(screen.queryByText(/nothing has been extracted/i)).not.toBeInTheDocument()
  })

  it('says the project is empty only when it is', () => {
    render(<EntityTreeBrowser {...props} groups={[]} />)

    expect(screen.getByText(/nothing has been extracted/i)).toBeInTheDocument()
  })

  /** A truncated list reads as an inventory and is not one. Fails if the
   *  notice is dropped, which looks identical to a complete graph on screen. */
  it('admits when the server capped what it sent', () => {
    render(<EntityTreeBrowser {...props} partial />)

    expect(screen.getByText(/part of a larger graph/i)).toBeInTheDocument()
  })

  it('does not claim a cap that did not happen', () => {
    render(<EntityTreeBrowser {...props} />)

    expect(screen.queryByText(/part of a larger graph/i)).not.toBeInTheDocument()
  })
})

const fakeGraphs = (over: Partial<GraphRepository> = {}): GraphRepository => ({
  whole: vi.fn().mockResolvedValue({ entities: [], relationships: [], truncated: false }),
  search: vi.fn().mockResolvedValue({ entities: [], truncated: false }),
  neighborhood: vi.fn().mockRejectedValue(new Error('neighborhood was not stubbed for this test')),
  ...over,
})

const fakeUsages = (over: Partial<UsagesRepository> = {}): UsagesRepository => ({
  usages: vi.fn().mockResolvedValue([]),
  ...over,
})

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
    pushGraph: (projectIdArg: string = projectId, change = 'DocumentExtracted') =>
      act(() => {
        listener?.onFrame({ kind: 'graph', projectId: projectIdArg, change })
      }),
  }
}

const renderWithContainer = (
  ui: ReactElement,
  parts: Partial<AppContainer>,
  stream: EventStream = fakeStream().stream,
) => {
  const container = {
    stream,
    usages: fakeUsages(),
    ...parts,
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>
          <OverlayHost>{children}</OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(ui, { wrapper })
}

describe('EntityTreePane', () => {
  it('draws the project’s entities without being asked to search first', async () => {
    const whole = vi.fn().mockResolvedValue({
      entities: [{ id: 'p1', name: 'Hinton', entityType: 'person' }],
      relationships: [],
      truncated: false,
    })

    renderWithContainer(<EntityTreePane projectId={projectId} entity={null} onEntity={vi.fn()} />, {
      graphs: fakeGraphs({ whole }),
    })

    expect(await screen.findByRole('button', { name: /person/ })).toBeInTheDocument()
  })

  it('opens every group on a small graph, so the tab enumerates something', async () => {
    const whole = vi.fn().mockResolvedValue({
      entities: [{ id: 'p1', name: 'Hinton', entityType: 'person' }],
      relationships: [],
      truncated: false,
    })

    renderWithContainer(<EntityTreePane projectId={projectId} entity={null} onEntity={vi.fn()} />, {
      graphs: fakeGraphs({ whole }),
    })

    expect(await screen.findByText('Hinton')).toBeInTheDocument()
  })

  it('keeps a collapsed group collapsed across a reload triggered by extraction', async () => {
    // The defect this pins: `loadAll` reruns on every `graph` frame, and
    // recomputing the default openness there would silently reopen a group
    // the reader had just closed, during the one activity that changes this
    // list.
    const whole = vi.fn().mockResolvedValue({
      entities: [{ id: 'p1', name: 'Hinton', entityType: 'person' }],
      relationships: [],
      truncated: false,
    })
    const feed = fakeStream()
    const user = userEvent.setup()

    renderWithContainer(
      <EntityTreePane projectId={projectId} entity={null} onEntity={vi.fn()} />,
      { graphs: fakeGraphs({ whole }) },
      feed.stream,
    )

    await screen.findByText('Hinton')
    await user.click(screen.getByRole('button', { name: /person/ }))
    expect(screen.queryByText('Hinton')).not.toBeInTheDocument()

    feed.pushGraph()
    await waitFor(() => expect(whole).toHaveBeenCalledTimes(2))

    expect(screen.queryByText('Hinton')).not.toBeInTheDocument()
  })

  /** The once-per-project token must not be spent on an empty first load: a
   *  project with nothing extracted yet at mount time is the common case for
   *  a project mid-extraction, and burning the token there leaves every group
   *  that arrives on a later `graph` frame closed for the rest of the
   *  session -- the state `OPEN_ALL_BELOW`'s comment says the tab exists to
   *  avoid. Distinct from the test above: that one proves a *closed* group
   *  survives a reload; this one proves an empty *first* load does not
   *  poison the default for every reload after it. */
  it('still defaults a group open when the first load found nothing to open', async () => {
    const whole = vi
      .fn()
      .mockResolvedValueOnce({ entities: [], relationships: [], truncated: false })
      .mockResolvedValue({
        entities: [{ id: 'p1', name: 'Hinton', entityType: 'person' }],
        relationships: [],
        truncated: false,
      })
    const feed = fakeStream()

    renderWithContainer(
      <EntityTreePane projectId={projectId} entity={null} onEntity={vi.fn()} />,
      { graphs: fakeGraphs({ whole }) },
      feed.stream,
    )

    await waitFor(() => expect(whole).toHaveBeenCalledTimes(1))

    feed.pushGraph()
    await waitFor(() => expect(whole).toHaveBeenCalledTimes(2))

    expect(await screen.findByText('Hinton')).toBeInTheDocument()
  })
})

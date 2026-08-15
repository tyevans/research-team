import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream } from '@application/ports/event-stream.ts'
import type { GraphRepository, TimelineRepository } from '@application/ports/repositories.ts'
import type { GraphNode, Neighborhood } from '@domain/knowledge/graph.ts'
import type { Timeline, TimelineBand } from '@domain/knowledge/timeline.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { TimelinePane } from './TimelinePane.tsx'

// The canvas is an SVG of computed positions, which jsdom lays out as
// nothing. Stubbed to a list of buttons so this file can assert *behaviour*
// -- which bands arrive, what a click does -- and leave geometry to
// `timeline-geometry.browser.test.tsx`, where it can actually be measured.
vi.mock('./TimelineCanvas.tsx', () => ({
  TimelineCanvas: ({
    bands,
    onSelect,
  }: {
    bands: readonly TimelineBand[]
    onSelect: (id: string) => void
  }) => (
    <div data-testid="canvas">
      {bands.map((band) => (
        <button key={band.id} onClick={() => onSelect(band.id)}>
          {band.name}
        </button>
      ))}
    </div>
  ),
}))

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const band = (id: string, name: string): TimelineBand => ({
  id,
  name,
  entityType: 'event',
  extent: '1815',
  start: '1815-01-01T00:00:00',
  end: '1816-01-01T00:00:00',
  precision: 'YEAR',
  uncertainty: 'EXACT',
})

const timeline = (over: Partial<Timeline> = {}): Timeline => ({
  bands: [band('e1', 'Waterloo')],
  undatedCount: 0,
  truncated: false,
  ...over,
})

const fakeTimelines = (over: Partial<TimelineRepository> = {}): TimelineRepository => ({
  timeline: vi.fn().mockResolvedValue(timeline()),
  ...over,
})

const node = (over: Partial<GraphNode> = {}): GraphNode => ({
  id: 'e1',
  name: 'Waterloo',
  entityType: 'event',
  ...over,
})

/** A `neighborhood` resolving to a root with no neighbours -- enough to open
 *  the detail panel without exercising `GraphDetail`'s edge rendering, which
 *  is `GraphPane.test.tsx`'s concern. */
const fakeGraphsWithNeighborhood = (): GraphRepository => ({
  whole: vi.fn().mockRejectedValue(new Error('whole was not stubbed for this test')),
  search: vi.fn().mockRejectedValue(new Error('search was not stubbed for this test')),
  neighborhood: vi.fn().mockResolvedValue({
    root: node(),
    entities: [],
    relationships: [],
  } satisfies Neighborhood),
})

/** `TimelinePane` with the route wired up, mirroring `GraphPane.test.tsx`'s
 *  `RoutedGraphPane`: selection lives in the URL in the real app, and a pane
 *  rendered with a fixed `entity` and a no-op `onEntity` could never select
 *  anything at all. */
const RoutedTimelinePane = () => {
  const [entity, setEntity] = useState<string | null>(null)
  return <TimelinePane projectId={PROJECT} entity={entity} onEntity={setEntity} />
}

/** A stream that never emits: nothing in this file needs a live frame, and a
 *  `connect` that never gets called is a `StreamProvider` that never throws. */
const fakeStream = (): EventStream => ({
  connect: () => {},
  disconnect: () => {},
})

/** `StreamProvider` is not decoration: the pane subscribes to the graph feed
 *  through `useFrameRefresh`, which throws outside one. `OverlayHost` is what
 *  `GraphDetail`'s Escape handling registers against -- without it in scope
 *  Escape does nothing, the same contract `GraphPane.test.tsx` documents. */
const renderPane = (parts: Partial<AppContainer>) => {
  const container = { stream: fakeStream(), ...parts } as unknown as AppContainer
  return render(
    <ContainerProvider container={container}>
      <StreamProvider>
        <OverlayHost>
          <RoutedTimelinePane />
        </OverlayHost>
      </StreamProvider>
    </ContainerProvider>,
  )
}

describe('TimelinePane', () => {
  it('draws the bands the repository returned', async () => {
    renderPane({ timelines: fakeTimelines() })

    expect(await screen.findByText('Waterloo')).toBeInTheDocument()
  })

  it('says how many entities are undated rather than showing bands alone', async () => {
    // The failure this prevents is silent: a timeline showing one bar out of
    // four hundred entities looks exactly like a project containing one thing.
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockResolvedValue(timeline({ undatedCount: 312 })),
      }),
    })

    expect(await screen.findByText(/312/)).toBeInTheDocument()
  })

  it('says so when the server capped the timeline', async () => {
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockResolvedValue(timeline({ truncated: true })),
      }),
    })

    await waitFor(() => expect(screen.getByText(/more/i)).toBeInTheDocument())
  })

  it('shows an empty state when the project has no dated entities at all', async () => {
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockResolvedValue(timeline({ bands: [], undatedCount: 40 })),
      }),
    })

    // Distinguishes "nothing is dated" from "nothing was extracted": the
    // undated count is the only thing that tells those apart, and a reader
    // shown a bare empty state would go looking for an extraction failure.
    expect(await screen.findByText(/no dated entities/i)).toBeInTheDocument()
    expect(screen.getByText(/40/)).toBeInTheDocument()
  })

  it('surfaces a failed load rather than showing an empty timeline', async () => {
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockRejectedValue(new Error('the server said no')),
      }),
    })

    expect(await screen.findByText(/the server said no/)).toBeInTheDocument()
  })

  it('asks the route for one entity type when the filter is set', async () => {
    const timelines = fakeTimelines()
    renderPane({ timelines })

    await screen.findByText('Waterloo')
    await userEvent.selectOptions(screen.getByLabelText(/type/i), 'event')

    await waitFor(() =>
      expect(timelines.timeline).toHaveBeenLastCalledWith(expect.anything(), 'event'),
    )
  })

  it('opens the detail panel for a clicked band, with no remove control', async () => {
    // The remove control belongs to the graph canvas. Offering it here would
    // be a button that either does nothing or silently prunes the tab next
    // door -- see `GraphDetail.onRemove`.
    const graphs = fakeGraphsWithNeighborhood()
    renderPane({ timelines: fakeTimelines(), graphs })

    await userEvent.click(await screen.findByText('Waterloo'))

    await waitFor(() => expect(graphs.neighborhood).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
  })
})

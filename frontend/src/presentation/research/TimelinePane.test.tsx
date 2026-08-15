import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
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

/** A band of a second type, so the type roster has something to lose. */
const personBand = (id: string, name: string): TimelineBand => ({
  ...band(id, name),
  entityType: 'person',
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
 *  is `GraphPane.test.tsx`'s concern.
 *
 * Takes the mock rather than building its own, so a caller that needs to
 * assert against it (`expect(neighborhood).toHaveBeenCalled()`) holds the
 * function directly instead of reaching through the returned object --
 * `@typescript-eslint/unbound-method` flags the latter as an unbound method
 * reference. */
const fakeGraphsWithNeighborhood = (
  neighborhood: GraphRepository['neighborhood'] = vi.fn().mockResolvedValue({
    root: node(),
    entities: [],
    relationships: [],
  } satisfies Neighborhood),
): GraphRepository => ({
  whole: vi.fn().mockRejectedValue(new Error('whole was not stubbed for this test')),
  search: vi.fn().mockRejectedValue(new Error('search was not stubbed for this test')),
  neighborhood,
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
 *  Escape does nothing, the same contract `GraphPane.test.tsx` documents.
 *
 *  `QueryClientProvider` and the two empty repositories below are here for a
 *  reason worth stating: `GraphDetail` gained mentions and definition
 *  sections, each a query of its own, so every route that opens that panel
 *  now needs a client in scope. The timeline reaches the same panel the graph
 *  does, which is the point of `showInGraphHref` -- so it inherits the
 *  requirement. Without the provider the panel throws on render and the
 *  failure names a hook, not the missing provider. */
const renderPane = (parts: Partial<AppContainer>) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  const container = {
    stream: fakeStream(),
    // Empty rather than omitted: these tests are about bands and the panel's
    // shell, not about mentions, and a repository that resolves to nothing
    // keeps those sections in their empty state instead of an error state
    // that would compete with what is being asserted.
    usages: { usages: async () => [] },
    definitions: {
      definition: async () => ({
        text: null,
        citations: [],
        model: null,
        generatedAt: null,
        stale: false,
      }),
    },
    ...parts,
  } as unknown as AppContainer
  return render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>
          <OverlayHost>
            <RoutedTimelinePane />
          </OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>,
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
    // Captured in its own variable rather than read through `timelines.timeline`:
    // a mock method reference passed to `expect` unbound loses `this`, which
    // `@typescript-eslint/unbound-method` flags even though vitest's mocks do
    // not actually depend on it.
    const fetchTimeline = vi.fn().mockResolvedValue(timeline())
    renderPane({ timelines: fakeTimelines({ timeline: fetchTimeline }) })

    await screen.findByText('Waterloo')
    await userEvent.selectOptions(screen.getByLabelText(/type/i), 'event')

    await waitFor(() => expect(fetchTimeline).toHaveBeenLastCalledWith(expect.anything(), 'event'))
  })

  it('keeps every type on offer after one of them is chosen', async () => {
    // The defect this pins: the filter is pushed to the server, so the
    // response for `event` contains only event bands. Options derived from the
    // bands in hand then collapse to `All` + `event`, and the reader has to go
    // back to `All` to reach `person` at all. Fails against the version that
    // read `timeline.bands`, where `person` is gone from the second assertion.
    const fetchTimeline = vi
      .fn()
      .mockResolvedValueOnce(
        timeline({ bands: [band('e1', 'Waterloo'), personBand('p1', 'Wellington')] }),
      )
      .mockResolvedValue(timeline({ bands: [band('e1', 'Waterloo')] }))
    renderPane({ timelines: fakeTimelines({ timeline: fetchTimeline }) })

    const select = await screen.findByLabelText(/type/i)
    await waitFor(() => expect(screen.getByRole('option', { name: 'person' })).toBeInTheDocument())

    await userEvent.selectOptions(select, 'event')

    await waitFor(() => expect(fetchTimeline).toHaveBeenCalledTimes(2))
    expect(screen.getByRole('option', { name: 'person' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'event' })).toBeInTheDocument()
  })

  it('names the filtered type in the undated notice rather than claiming the project', async () => {
    // The server counts undated entities *within* the filter, so "312 of 313
    // entities are undated" would be a claim about the project made from a
    // number about events.
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockResolvedValue(timeline({ undatedCount: 312 })),
      }),
    })

    await screen.findByText('Waterloo')
    await userEvent.selectOptions(await screen.findByLabelText(/type/i), 'event')

    expect(await screen.findByText(/312 of 313 event entities are undated/)).toBeInTheDocument()
  })

  it('drops the undated denominator when the timeline was capped', async () => {
    // `bands` is post-cap, so `undated + bands.length` understates the project
    // -- and the capped notice directly below would then contradict it. Fails
    // against the version that always rendered the total, which said
    // "312 of 313".
    renderPane({
      timelines: fakeTimelines({
        timeline: vi.fn().mockResolvedValue(timeline({ undatedCount: 312, truncated: true })),
      }),
    })

    expect(await screen.findByText(/312 entities are undated/)).toBeInTheDocument()
    expect(screen.queryByText(/of 313/)).not.toBeInTheDocument()
  })

  it('offers a route into the graph view for the selected band', async () => {
    // Without this the timeline is a dead end: a reader who finds an
    // interesting band has no way through to what it is connected to. The
    // href, not just the label, because the two views are peers only if the
    // link actually lands on the entity facet.
    renderPane({ timelines: fakeTimelines(), graphs: fakeGraphsWithNeighborhood() })

    await userEvent.click(await screen.findByText('Waterloo'))

    const link = await screen.findByRole('link', { name: /show in graph/i })
    expect(link).toHaveAttribute('href', `#/p/${PROJECT}/entity/e1`)
  })

  it('opens the detail panel for a clicked band, with no remove control', async () => {
    // The remove control belongs to the graph canvas. Offering it here would
    // be a button that either does nothing or silently prunes the tab next
    // door -- see `GraphDetail.onRemove`.
    const neighborhood = vi.fn().mockResolvedValue({
      root: node(),
      entities: [],
      relationships: [],
    } satisfies Neighborhood)
    renderPane({ timelines: fakeTimelines(), graphs: fakeGraphsWithNeighborhood(neighborhood) })

    await userEvent.click(await screen.findByText('Waterloo'))

    await waitFor(() => expect(neighborhood).toHaveBeenCalled())
    expect(screen.queryByRole('button', { name: /remove/i })).not.toBeInTheDocument()
  })
})

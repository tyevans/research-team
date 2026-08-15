import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import { ApiError } from '@application/ports/errors.ts'
import type { GraphRepository, UsagesRepository } from '@application/ports/repositories.ts'
import type { GraphNode, Neighborhood } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { FRAME_DEBOUNCE_MS } from '../shell/use-frame-refresh.ts'
import { GraphPane } from './GraphPane.tsx'

// Asserting on canvas pixels would test the library, not this pane -- the
// canvas is mocked to a stub that exposes what the pane hands it, so these
// tests can drive expansion through it without a real d3-force simulation.
vi.mock('./GraphCanvas.tsx', () => ({
  GraphCanvas: ({ onNodeClick }: { onNodeClick: (id: string) => void }) => (
    <button type="button" onClick={() => onNodeClick('ada')}>
      canvas
    </button>
  ),
}))

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const node = (over: Partial<GraphNode> = {}): GraphNode => ({
  id: 'ada',
  name: 'Ada Lovelace',
  entityType: 'Person',
  ...over,
})

const hoodOf = (root: GraphNode): Neighborhood => ({ root, entities: [root], relationships: [] })

const fakeGraphs = (over: Partial<GraphRepository> = {}): GraphRepository => ({
  // Empty by default so the existing search-and-expand tests still start from
  // a bare canvas; the tests about the opening draw stub it themselves.
  whole: vi.fn().mockResolvedValue({ entities: [], relationships: [], truncated: false }),
  search: vi.fn().mockResolvedValue({ entities: [], truncated: false }),
  neighborhood: vi.fn().mockRejectedValue(new Error('neighborhood was not stubbed for this test')),
  ...over,
})

/** `GraphPane` with the route wired up, which is the only way the real app
 *  ever renders it: selection lives in the URL, so a pane rendered with a
 *  fixed `entity` and a no-op `onEntity` could never select anything at all.
 *  This stands in for the address bar. */
const RoutedGraphPane = ({ start = null }: { start?: string | null }) => {
  const [entity, setEntity] = useState<string | null>(start)
  return <GraphPane projectId={PROJECT} entity={entity} onEntity={setEntity} />
}

/** Mirrors `TopicList.test.tsx`'s fake stream, so a live-update assertion
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
    pushGraph: (projectId: string = PROJECT, change = 'DocumentExtracted') =>
      act(() => {
        listener?.onFrame({ kind: 'graph', projectId, change })
      }),
    pushCorpus: () =>
      act(() => {
        listener?.onFrame({
          kind: 'corpus',
          projectId: PROJECT,
          change: 'CorpusDocumentStored',
        })
      }),
  }
}

/** `OverlayHost` joined this harness when `GraphDetail` stopped listening for
 *  Escape on `window` and started taking its turn in the host's layer stack.
 *  Without a host in scope the panel simply does not register, so Escape does
 *  nothing -- the same contract `Overlay` has, where a hostless layer renders
 *  `null` rather than escaping to `document.body`. That the *application*
 *  mounts one is `App.test.tsx`'s claim, and it deliberately supplies none of
 *  its own.
 *
 *  The `StreamProvider` is not decoration: `GraphPane` subscribes to the feed,
 *  and a harness without one would exercise a component the application never
 *  renders. */
// `GraphDetail` reads usages through a query hook (`useUsages`), which is the
// only reason a `QueryClient` joined this harness -- everything else here is
// still the zustand store `createGraphStore` owns. Resolved to empty rather
// than left unstubbed: none of the suites below are about mentions, and a
// panel that threw on mount because this repository was missing would fail
// every one of them for a reason that has nothing to do with what they test.
const fakeUsages = (over: Partial<UsagesRepository> = {}): UsagesRepository => ({
  usages: vi.fn().mockResolvedValue([]),
  ...over,
})

const renderWithContainer = (
  ui: ReactElement,
  parts: Partial<AppContainer>,
  stream: EventStream = fakeStream().stream,
) => {
  const container = { stream, usages: fakeUsages(), ...parts } as unknown as AppContainer
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

it('populates results from a search', async () => {
  const ada = node()
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')

  expect(await screen.findByText(/Ada Lovelace/)).toBeInTheDocument()
})

it('expands a clicked result into the canvas', async () => {
  const ada = node()
  const neighborhood = vi.fn().mockResolvedValue(hoodOf(ada))
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood,
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  const result = await screen.findByText(/Ada Lovelace/)
  await user.click(result)

  await waitFor(() => expect(neighborhood).toHaveBeenCalledWith(PROJECT, 'ada'))
})

it('does not re-fetch an already-expanded node clicked again from the canvas', async () => {
  const ada = node()
  const neighborhood = vi.fn().mockResolvedValue(hoodOf(ada))
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood,
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  const result = await screen.findByText(/Ada Lovelace/)
  await user.click(result)
  await waitFor(() => expect(neighborhood).toHaveBeenCalledTimes(1))

  // The lazy canvas mock's click always targets the same node id ('ada'),
  // which is already expanded from the search-result click above.
  const canvasButton = await screen.findByRole('button', { name: 'canvas' })
  await user.click(canvasButton)

  expect(neighborhood).toHaveBeenCalledTimes(1)
})

it('surfaces a 422 from too-deep a request rather than failing silently', async () => {
  const ada = node()
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood: vi.fn().mockRejectedValue(new ApiError('depth 3 exceeds the maximum of 2', 422)),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  const result = await screen.findByText(/Ada Lovelace/)
  await user.click(result)

  expect(await screen.findByText(/depth 3 exceeds the maximum of 2/)).toBeInTheDocument()
})

it('debounces search rather than issuing one request per keystroke', async () => {
  const ada = node()
  const search = vi.fn().mockResolvedValue({ entities: [ada], truncated: false })
  const graphs = fakeGraphs({ search })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')

  await waitFor(() => expect(search).toHaveBeenCalled())
  // Four keystrokes, and the debounce settled once, at the final value --
  // the whole point is that this is not four requests.
  expect(search).toHaveBeenCalledTimes(1)
  expect(search).toHaveBeenCalledWith(PROJECT, 'ada', undefined)
})

it('tells the reader when the server held back more matches than it showed', async () => {
  const ada = node()
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: true }),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')

  expect(await screen.findByText(/first 1 match/i)).toBeInTheDocument()
})

it('passes the selected entity type filter to the repository', async () => {
  const ada = node()
  const search = vi.fn().mockResolvedValue({ entities: [ada], truncated: false })
  const graphs = fakeGraphs({ search })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  await screen.findByText(/Ada Lovelace/)

  await user.selectOptions(
    screen.getByRole('combobox', { name: /filter by entity type/i }),
    'Person',
  )

  await waitFor(() => expect(search).toHaveBeenLastCalledWith(PROJECT, 'ada', 'Person'))
})

it('says what a clicked entity is and what it connects to', async () => {
  // The answer to "I can click a node and nothing meaningful happens".
  // Expanding draws more dots; this is the part that says what the dot was.
  const ada = node()
  const babbage = node({ id: 'babbage', name: 'Charles Babbage', entityType: 'Person' })
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood: vi.fn().mockResolvedValue({
      root: ada,
      entities: [babbage],
      relationships: [{ source: 'ada', target: 'babbage', relationshipType: 'collaborated_with' }],
    } satisfies Neighborhood),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  await user.click(await screen.findByRole('button', { name: /Ada Lovelace/ }))

  const detail = await screen.findByRole('complementary', { name: /about ada lovelace/i })
  expect(detail).toHaveTextContent('Person')
  // The relationship type is the content of a knowledge graph -- a panel that
  // only said "connected to" would be throwing away the part worth reading --
  // and the arrow is what makes the row read as a sentence about Ada rather
  // than one the reader has to reverse in their head.
  expect(detail).toHaveTextContent('collaborated_with')
  expect(detail).toHaveTextContent('Charles Babbage')
  expect(detail.textContent).toContain('→')
})

it('closes the detail panel without disturbing the drawing', async () => {
  const ada = node()
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood: vi.fn().mockResolvedValue(hoodOf(ada)),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  await user.click(await screen.findByRole('button', { name: /Ada Lovelace/ }))
  await screen.findByRole('complementary', { name: /about ada lovelace/i })

  await user.click(screen.getByRole('button', { name: /close entity details/i }))

  expect(
    screen.queryByRole('complementary', { name: /about ada lovelace/i }),
  ).not.toBeInTheDocument()
  // The canvas stub stands in for the drawing: closing the panel is a change
  // of what is described, not of what is drawn.
  expect(screen.getByRole('button', { name: 'canvas' })).toBeInTheDocument()
})

it('gets the result list out of the way once a result is picked', async () => {
  // The list floats over the canvas, so leaving it up after a pick covers the
  // drawing the pick just produced. You chose the thing in order to look at
  // it.
  const ada = node()
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood: vi.fn().mockResolvedValue(hoodOf(ada)),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  const box = screen.getByRole('searchbox', { name: /search the graph/i })
  await user.type(box, 'ada')
  await user.click(await screen.findByRole('button', { name: /Ada Lovelace/ }))

  // Scoped to the results list rather than to the name: the detail panel that
  // opens on a pick has a Remove button carrying the same entity name, so a
  // bare name query would find that instead and pass whether or not the list
  // had gone.
  await waitFor(() => {
    expect(screen.queryByRole('list', { name: /search results/i })).not.toBeInTheDocument()
  })
  // Empty and ready for the next search, which is the state somebody who has
  // finished with this one wants it in.
  expect(box).toHaveValue('')
})

it('distinguishes an entity with no relationships from one not yet expanded', async () => {
  // Telling a reader to click again on an entity whose neighbourhood already
  // came back empty sends them to fetch a second time for the same nothing.
  const ada = node()
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood: vi.fn().mockResolvedValue(hoodOf(ada)),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  await user.click(await screen.findByRole('button', { name: /Ada Lovelace/ }))

  const detail = await screen.findByRole('complementary', { name: /about ada lovelace/i })
  expect(detail).toHaveTextContent(/no relationships were recorded/i)
  expect(detail).not.toHaveTextContent(/click it on the canvas/i)
})

it('takes an entity off the drawing, and the panel with it', async () => {
  // Browsing accumulates, and until now the only way back was to reload the
  // page -- which threw away every expansion, not just the unwanted one.
  const ada = node()
  const babbage = node({ id: 'babbage', name: 'Charles Babbage', entityType: 'Person' })
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood: vi.fn().mockResolvedValue({
      root: ada,
      entities: [babbage],
      relationships: [{ source: 'ada', target: 'babbage', relationshipType: 'collaborated_with' }],
    } satisfies Neighborhood),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  await user.click(await screen.findByRole('button', { name: /Ada Lovelace/ }))
  await screen.findByRole('complementary', { name: /about ada lovelace/i })

  await user.click(screen.getByRole('button', { name: /remove ada lovelace from the view/i }))

  // The panel describes the selection, so a removed selection must not leave
  // it describing something no longer on the canvas.
  expect(
    screen.queryByRole('complementary', { name: /about ada lovelace/i }),
  ).not.toBeInTheDocument()
  // Babbage arrived only as Ada's neighbour and was never asked for, so he
  // goes with her -- which empties the canvas. This project's whole graph is
  // stubbed empty, so an empty canvas is the truth here.
  expect(await screen.findByText(/this graph is empty/i)).toBeInTheDocument()
})

it('draws the whole graph on arrival, before anybody searches', async () => {
  // The complaint this answers: the page opened barren and only ever showed
  // what you had already picked, which meant you had to know an entity's name
  // to see that the project had any.
  const ada = node()
  const babbage = node({ id: 'babbage', name: 'Charles Babbage' })
  const whole = vi.fn().mockResolvedValue({
    entities: [ada, babbage],
    relationships: [{ source: 'ada', target: 'babbage', relationshipType: 'collaborated_with' }],
    truncated: false,
  })

  renderWithContainer(<RoutedGraphPane />, { graphs: fakeGraphs({ whole }) })

  await waitFor(() => expect(whole).toHaveBeenCalledWith(PROJECT))
  expect(await screen.findByRole('button', { name: 'canvas' })).toBeInTheDocument()
  expect(screen.queryByText(/this graph is empty/i)).not.toBeInTheDocument()
})

it('says an empty canvas means an empty graph, not an unasked question', async () => {
  const whole = vi.fn().mockResolvedValue({ entities: [], relationships: [], truncated: false })

  renderWithContainer(<RoutedGraphPane />, { graphs: fakeGraphs({ whole }) })

  expect(await screen.findByText(/this graph is empty/i)).toBeInTheDocument()
  expect(screen.getByText(/nothing has been extracted/i)).toBeInTheDocument()
})

it('does not call a failed load an empty graph', async () => {
  // The two look identical on a blank canvas and mean opposite things: one
  // says the project has nothing in it, the other that this page could not
  // find out.
  const whole = vi.fn().mockRejectedValue(new ApiError('no graph read model is configured', 503))

  renderWithContainer(<RoutedGraphPane />, { graphs: fakeGraphs({ whole }) })

  expect(await screen.findByText(/could not be read/i)).toBeInTheDocument()
  expect(screen.queryByText(/this graph is empty/i)).not.toBeInTheDocument()
  expect(screen.getByText(/no graph read model is configured/i)).toBeInTheDocument()
})

it('says when the drawing is only part of a larger graph', async () => {
  // A capped graph draws exactly like a complete one; without this the
  // reader would take the first 500 nodes for the whole project.
  const whole = vi
    .fn()
    .mockResolvedValue({ entities: [node()], relationships: [], truncated: true })

  renderWithContainer(<RoutedGraphPane />, { graphs: fakeGraphs({ whole }) })

  expect(await screen.findByText(/part of a larger graph/i)).toBeInTheDocument()
})

it('restores the whole graph after pruning, rather than emptying the canvas', async () => {
  const ada = node()
  const babbage = node({ id: 'babbage', name: 'Charles Babbage' })
  const whole = vi.fn().mockResolvedValue({
    entities: [ada, babbage],
    relationships: [{ source: 'ada', target: 'babbage', relationshipType: 'collaborated_with' }],
    truncated: false,
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs: fakeGraphs({ whole }) })
  await waitFor(() => expect(whole).toHaveBeenCalledTimes(1))

  await user.click(await screen.findByRole('button', { name: /reset view/i }))

  // Re-read rather than restored from a snapshot: extraction runs while the
  // tab is open, so "show me everything" has to mean everything there is now.
  await waitFor(() => expect(whole).toHaveBeenCalledTimes(2))
  expect(screen.getByRole('button', { name: 'canvas' })).toBeInTheDocument()
})

it('closes the detail panel on Escape, the way the drawers do', async () => {
  const ada = node()
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood: vi.fn().mockResolvedValue(hoodOf(ada)),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  await user.click(await screen.findByRole('button', { name: /Ada Lovelace/ }))
  await screen.findByRole('complementary', { name: /about ada lovelace/i })

  await user.keyboard('{Escape}')

  expect(
    screen.queryByRole('complementary', { name: /about ada lovelace/i }),
  ).not.toBeInTheDocument()
  // Closing the description does not undraw what it described.
  expect(screen.getByRole('button', { name: 'canvas' })).toBeInTheDocument()
})

it('draws the entity named in the route on load, with no search first', async () => {
  const ada = node()
  const neighborhood = vi.fn().mockResolvedValue(hoodOf(ada))
  const graphs = fakeGraphs({ neighborhood })

  renderWithContainer(<RoutedGraphPane start="ada" />, { graphs })

  // The whole point of the entity being in the URL: a pasted link draws the
  // graph it describes, without anybody retyping the search that found it.
  await waitFor(() => expect(neighborhood).toHaveBeenCalledWith(PROJECT, 'ada'))
  expect(
    await screen.findByRole('complementary', { name: /about ada lovelace/i }),
  ).toBeInTheDocument()
})

it('reports a picked result outward instead of selecting behind the route’s back', async () => {
  const ada = node()
  const onEntity = vi.fn()
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [ada], truncated: false }),
    neighborhood: vi.fn().mockResolvedValue(hoodOf(ada)),
  })
  const user = userEvent.setup()

  renderWithContainer(<GraphPane projectId={PROJECT} entity={null} onEntity={onEntity} />, {
    graphs,
  })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  await user.click(await screen.findByText(/Ada Lovelace/))

  expect(onEntity).toHaveBeenCalledWith('ada')
})

it('says a search matched nothing, rather than rendering silence', async () => {
  const graphs = fakeGraphs({
    search: vi.fn().mockResolvedValue({ entities: [], truncated: false }),
  })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'zzzz')

  // Silence is what a search still being typed looks like, so the one case
  // where the answer is already known must not look like waiting.
  expect(await screen.findByText(/nothing matched/i)).toBeInTheDocument()
})

it('reports nothing before a term has been asked for', () => {
  const graphs = fakeGraphs()

  renderWithContainer(<RoutedGraphPane />, { graphs })

  expect(screen.queryByText(/nothing matched/i)).not.toBeInTheDocument()
})

it('keeps a type on offer after choosing it has narrowed the results to it', async () => {
  const search = vi
    .fn()
    .mockResolvedValueOnce({
      entities: [node({ id: 'a', entityType: 'fact' }), node({ id: 'b', entityType: 'study' })],
      truncated: false,
    })
    .mockResolvedValue({ entities: [node({ id: 'a', entityType: 'fact' })], truncated: false })
  const user = userEvent.setup()

  renderWithContainer(<RoutedGraphPane />, { graphs: fakeGraphs({ search }) })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'x')
  await screen.findByRole('option', { name: 'study' })

  await user.selectOptions(screen.getByRole('combobox', { name: /filter by entity type/i }), 'fact')

  // The results are all facts now. `study` must still be reachable, or the
  // control that just offered it has trapped the reader on their own choice.
  await waitFor(() => expect(search).toHaveBeenCalledTimes(2))
  expect(screen.getByRole('option', { name: 'study' })).toBeInTheDocument()
})

it('draws an entity extracted after the page loaded, without a reload', async () => {
  // The bug this whole change exists for. `loadAll` runs once per project, so
  // a pane opened before an ingest drew the graph as it was then and never
  // again -- a reader watched the transcript report twelve entities against a
  // canvas that showed none of them. Reverting either half (the `Graph` frame
  // or this subscription) fails here.
  const ada = node()
  const whole = vi
    .fn()
    .mockResolvedValueOnce({ entities: [], relationships: [], truncated: false })
    .mockResolvedValue({ entities: [ada], relationships: [], truncated: false })
  const graphs = fakeGraphs({ whole })
  const feed = fakeStream()

  renderWithContainer(<RoutedGraphPane />, { graphs }, feed.stream)
  await waitFor(() => expect(whole).toHaveBeenCalledTimes(1))

  feed.pushGraph()

  await waitFor(() => expect(whole).toHaveBeenCalledTimes(2), { timeout: 2_000 })
  expect(await screen.findByText(/canvas/)).toBeInTheDocument()
})

it('re-reads the graph once for a burst of frames, not once each', async () => {
  // An ingest emits one extraction and then one merge per entity it resolved,
  // so a document yielding twelve entities can commit a dozen frames in a
  // row. Without the debounce that is a dozen whole-graph reads for one
  // repaint -- and this is the pane that redraws a force-directed layout.
  const whole = vi.fn().mockResolvedValue({ entities: [], relationships: [], truncated: false })
  const feed = fakeStream()

  renderWithContainer(<RoutedGraphPane />, { graphs: fakeGraphs({ whole }) }, feed.stream)
  await waitFor(() => expect(whole).toHaveBeenCalledTimes(1))

  feed.pushGraph()
  feed.pushGraph()
  feed.pushGraph()

  await waitFor(() => expect(whole).toHaveBeenCalledTimes(2))
  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(whole).toHaveBeenCalledTimes(2)
})

it('ignores another project’s graph frame, and a corpus frame', async () => {
  // The frame names its project, so a second project extracting in another tab
  // costs this pane nothing. A corpus frame is ignored for a different reason:
  // it rides the same ingest, and a document being stored changes no entity --
  // the graph frame that follows it is the one that means anything here.
  //
  // Stated plainly: this test passes with the subscription removed. It pins
  // the scope of the fix, not the fix; the two above are the red ones.
  const whole = vi.fn().mockResolvedValue({ entities: [], relationships: [], truncated: false })
  const feed = fakeStream()

  renderWithContainer(<RoutedGraphPane />, { graphs: fakeGraphs({ whole }) }, feed.stream)
  await waitFor(() => expect(whole).toHaveBeenCalledTimes(1))

  feed.pushGraph('99999999-9999-9999-9999-999999999999')
  feed.pushCorpus()

  await new Promise((resolve) => setTimeout(resolve, FRAME_DEBOUNCE_MS * 2))
  expect(whole).toHaveBeenCalledTimes(1)
})

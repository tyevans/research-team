import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import type { ReactElement } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { ApiError } from '@application/ports/errors.ts'
import type { GraphRepository } from '@application/ports/repositories.ts'
import type { GraphNode, Neighborhood } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

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

const renderWithContainer = (ui: ReactElement, parts: Partial<AppContainer>) => {
  const container = parts as unknown as AppContainer
  return render(<ContainerProvider container={container}>{ui}</ContainerProvider>)
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
  // goes with her -- which empties the canvas back to its invitation.
  expect(await screen.findByText(/nothing drawn yet/i)).toBeInTheDocument()
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

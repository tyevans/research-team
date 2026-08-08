import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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

  renderWithContainer(<GraphPane projectId={PROJECT} />, { graphs })

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

  renderWithContainer(<GraphPane projectId={PROJECT} />, { graphs })

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

  renderWithContainer(<GraphPane projectId={PROJECT} />, { graphs })

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

  renderWithContainer(<GraphPane projectId={PROJECT} />, { graphs })

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

  renderWithContainer(<GraphPane projectId={PROJECT} />, { graphs })

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

  renderWithContainer(<GraphPane projectId={PROJECT} />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')

  expect(await screen.findByText(/first 1 match/i)).toBeInTheDocument()
})

it('passes the selected entity type filter to the repository', async () => {
  const ada = node()
  const search = vi.fn().mockResolvedValue({ entities: [ada], truncated: false })
  const graphs = fakeGraphs({ search })
  const user = userEvent.setup()

  renderWithContainer(<GraphPane projectId={PROJECT} />, { graphs })

  await user.type(screen.getByRole('searchbox', { name: /search the graph/i }), 'ada')
  await screen.findByText(/Ada Lovelace/)

  await user.selectOptions(
    screen.getByRole('combobox', { name: /filter by entity type/i }),
    'Person',
  )

  await waitFor(() => expect(search).toHaveBeenLastCalledWith(PROJECT, 'ada', 'Person'))
})

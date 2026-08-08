import { expect, it, vi } from 'vitest'

import { ApiError } from '@application/ports/errors.ts'
import type { GraphRepository } from '@application/ports/repositories.ts'
import type { GraphNode, Neighborhood } from '@domain/knowledge/graph.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { createGraphStore } from './graph-store.ts'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const node = (over: Partial<GraphNode> = {}): GraphNode => ({
  id: 'ada',
  name: 'Ada Lovelace',
  entityType: 'Person',
  ...over,
})

const hoodOf = (root: GraphNode, ...others: readonly GraphNode[]): Neighborhood => ({
  root,
  entities: [root, ...others],
  relationships: others.map((other) => ({
    source: root.id,
    target: other.id,
    relationshipType: 'advised',
  })),
})

const fakeGraphs = (over: Partial<GraphRepository> = {}): GraphRepository => ({
  search: vi.fn().mockResolvedValue({ entities: [], truncated: false }),
  neighborhood: vi.fn().mockRejectedValue(new Error('neighborhood was not stubbed for this test')),
  ...over,
})

const store = (graphs: GraphRepository = fakeGraphs()) =>
  createGraphStore({ graphs, projectId: PROJECT })

it('populates results from a search', async () => {
  const ada = node()
  const search = vi.fn().mockResolvedValue({ entities: [ada], truncated: false })
  const graphs = fakeGraphs({ search })
  const graph = store(graphs)

  await graph.getState().search('ada')

  expect(graph.getState().results).toEqual([ada])
  expect(graph.getState().truncated).toBe(false)
  expect(search).toHaveBeenCalledWith(PROJECT, 'ada', undefined)
})

it('reports when the server held more matches back than the page returned', async () => {
  const ada = node()
  const search = vi.fn().mockResolvedValue({ entities: [ada], truncated: true })
  const graphs = fakeGraphs({ search })
  const graph = store(graphs)

  await graph.getState().search('a')

  expect(graph.getState().truncated).toBe(true)
})

it('passes an entity type filter through to the repository', async () => {
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const graphs = fakeGraphs({ search })
  const graph = store(graphs)

  await graph.getState().search('ada', 'Person')

  expect(search).toHaveBeenCalledWith(PROJECT, 'ada', 'Person')
})

it('clears results without a request for a blank search with no type filter', async () => {
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const graphs = fakeGraphs({ search })
  const graph = store(graphs)

  await graph.getState().search('   ')

  expect(graph.getState().results).toEqual([])
  expect(search).not.toHaveBeenCalled()
})

it('still searches on a blank term when a type filter is set', async () => {
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const graphs = fakeGraphs({ search })
  const graph = store(graphs)

  await graph.getState().search('   ', 'Person')

  expect(search).toHaveBeenCalledWith(PROJECT, '', 'Person')
})

it('expands a clicked node into the view', async () => {
  const ada = node()
  const grace = node({ id: 'grace', name: 'Grace Hopper' })
  const graphs = fakeGraphs({ neighborhood: vi.fn().mockResolvedValue(hoodOf(ada, grace)) })
  const graph = store(graphs)

  await graph.getState().expandNode('ada')

  expect(graph.getState().view.nodes.map((n) => n.id)).toEqual(['ada', 'grace'])
  expect(graph.getState().view.links).toHaveLength(1)
})

it('does not re-fetch an already-expanded node', async () => {
  const ada = node()
  const neighborhood = vi.fn().mockResolvedValue(hoodOf(ada))
  const graphs = fakeGraphs({ neighborhood })
  const graph = store(graphs)

  await graph.getState().expandNode('ada')
  await graph.getState().expandNode('ada')

  expect(neighborhood).toHaveBeenCalledTimes(1)
})

it('surfaces a 422 from too deep a request rather than swallowing it', async () => {
  const graphs = fakeGraphs({
    neighborhood: vi.fn().mockRejectedValue(new ApiError('depth 3 exceeds the maximum of 2', 422)),
  })
  const graph = store(graphs)

  await graph.getState().expandNode('ada')

  expect(graph.getState().error).toBe('depth 3 exceeds the maximum of 2')
  expect(graph.getState().view.nodes).toEqual([])
})

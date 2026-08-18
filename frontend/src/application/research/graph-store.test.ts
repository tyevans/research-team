import { expect, it, vi } from 'vitest'

import type { Emitter } from '@application/interaction-log/emitter.ts'
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
  whole: vi.fn().mockResolvedValue({ entities: [], relationships: [], truncated: false }),
  search: vi.fn().mockResolvedValue({ entities: [], truncated: false }),
  neighborhood: vi.fn().mockRejectedValue(new Error('neighborhood was not stubbed for this test')),
  ...over,
})

const store = (graphs: GraphRepository = fakeGraphs(), emitter?: Pick<Emitter, 'record'>) =>
  createGraphStore({ graphs, projectId: PROJECT, ...(emitter ? { emitter } : {}) })

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

it('draws the whole graph, wired, without being asked for a node', async () => {
  const ada = node()
  const grace = node({ id: 'grace', name: 'Grace Hopper' })
  const whole = vi.fn().mockResolvedValue({
    entities: [ada, grace],
    relationships: [{ source: 'ada', target: 'grace', relationshipType: 'advised' }],
    truncated: false,
  })
  const graph = store(fakeGraphs({ whole }))

  await graph.getState().loadAll()

  expect(graph.getState().view.nodes.map((n) => n.id)).toEqual(['ada', 'grace'])
  expect(graph.getState().view.links).toHaveLength(1)
  expect(graph.getState().partial).toBe(false)
  expect(whole).toHaveBeenCalledWith(PROJECT)
})

it('surfaces the edge cap separately from the node cap', async () => {
  const ada = node()
  const whole = vi.fn().mockResolvedValue({
    entities: [ada],
    relationships: [],
    truncated: false,
    inferredTruncated: true,
  })
  const graph = store(fakeGraphs({ whole }))

  await graph.getState().loadAll()

  expect(graph.getState().partial).toBe(false)
  expect(graph.getState().edgesPartial).toBe(true)
})

it('treats a complete graph as fully expanded, so clicking costs no request', async () => {
  const ada = node()
  const neighborhood = vi.fn()
  const whole = vi.fn().mockResolvedValue({ entities: [ada], relationships: [], truncated: false })
  const graph = store(fakeGraphs({ whole, neighborhood }))

  await graph.getState().loadAll()
  await graph.getState().expandNode('ada')

  expect(neighborhood).not.toHaveBeenCalled()
  expect(graph.getState().selected).toBe('ada')
})

it('leaves a truncated graph expandable, since its edges are not all drawn', async () => {
  const ada = node()
  const grace = node({ id: 'grace', name: 'Grace Hopper' })
  const whole = vi.fn().mockResolvedValue({ entities: [ada], relationships: [], truncated: true })
  const neighborhood = vi.fn().mockResolvedValue(hoodOf(ada, grace))
  const graph = store(fakeGraphs({ whole, neighborhood }))

  await graph.getState().loadAll()
  expect(graph.getState().partial).toBe(true)

  await graph.getState().expandNode('ada')

  expect(neighborhood).toHaveBeenCalledTimes(1)
  expect(graph.getState().view.nodes.map((n) => n.id)).toEqual(['ada', 'grace'])
})

it('reports a failed load rather than showing an empty graph as an empty project', async () => {
  const whole = vi.fn().mockRejectedValue(new ApiError('no graph read model is configured', 503))
  const graph = store(fakeGraphs({ whole }))

  await graph.getState().loadAll()

  expect(graph.getState().error).toBe('no graph read model is configured')
  expect(graph.getState().loading).toBe(false)
  expect(graph.getState().view.nodes).toEqual([])
})

it('resets a pruned drawing by fetching the whole graph again', async () => {
  const ada = node()
  const grace = node({ id: 'grace', name: 'Grace Hopper' })
  const whole = vi.fn().mockResolvedValue({
    entities: [ada, grace],
    relationships: [{ source: 'ada', target: 'grace', relationshipType: 'advised' }],
    truncated: false,
  })
  const graph = store(fakeGraphs({ whole }))

  await graph.getState().loadAll()
  graph.getState().removeNode('grace')
  expect(graph.getState().view.nodes.map((n) => n.id)).toEqual(['ada'])

  await graph.getState().reset()

  expect(graph.getState().view.nodes.map((n) => n.id)).toEqual(['ada', 'grace'])
  // Re-read, not restored from a snapshot: the server's graph moves while
  // the page is open.
  expect(whole).toHaveBeenCalledTimes(2)
})

it('drops a selection the reloaded graph no longer contains', async () => {
  const ada = node()
  const whole = vi
    .fn()
    .mockResolvedValueOnce({ entities: [ada], relationships: [], truncated: false })
    .mockResolvedValueOnce({ entities: [], relationships: [], truncated: false })
  const graph = store(fakeGraphs({ whole }))

  await graph.getState().loadAll()
  graph.getState().select('ada')
  await graph.getState().reset()

  expect(graph.getState().selected).toBeNull()
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

it('selects a synthesised class node without fetching a neighbourhood for it', async () => {
  // A discovered class's id comes from the ontology table and belongs to no
  // stored entity, so `/neighborhood` answers 404 for it and `/definition` has
  // nothing to define. Asserting the fetch does not happen, rather than that
  // the error is handled: a handled 404 still costs a round trip on every
  // click and still writes a spurious failure into the network log a reader
  // may be reading for real ones.
  const neighborhood = vi.fn()
  const graph = store(fakeGraphs({ neighborhood }))
  graph.setState({
    view: {
      nodes: [node({ id: 'difficulty', name: 'Difficulty', entityType: 'class', inferred: true })],
      links: [],
      expanded: new Set<string>(),
    },
  })

  await graph.getState().expandNode('difficulty')

  expect(neighborhood).not.toHaveBeenCalled()
  // Still selected: clicking a class means "tell me about this one", and the
  // panel has plenty to say about it without a request.
  expect(graph.getState().selected).toBe('difficulty')
})

it('still fetches a neighbourhood for an ordinary node', async () => {
  // Would pass with fetching disabled outright, which is why it is here.
  const neighborhood = vi.fn().mockResolvedValue(hoodOf(node()))
  const graph = store(fakeGraphs({ neighborhood }))

  await graph.getState().expandNode('ada')

  expect(neighborhood).toHaveBeenCalledTimes(1)
})

it('does not fetch for a class node it has never drawn', async () => {
  // The id arrives from the address bar rather than from a click, so nothing
  // in the view identifies it as synthesised. Guarding only on a node already
  // on the canvas would leave the pasted-URL path issuing the 404 this exists
  // to prevent -- and `GraphPane` routes every selection, including the
  // initial one, through `expandNode`.
  const neighborhood = vi.fn().mockRejectedValue(new Error('404'))
  const graph = store(fakeGraphs({ neighborhood }))

  await graph.getState().expandNode('unknown-to-the-view')

  expect(neighborhood).toHaveBeenCalledTimes(1)
})

it('records EntityOpened with source "graph" when a node is selected explicitly', () => {
  const record = vi.fn<Emitter['record']>()
  const graph = store(fakeGraphs(), { record })

  graph.getState().select('ada')

  expect(record).toHaveBeenCalledWith('EntityOpened', { entity_id: 'ada', source: 'graph' })
})

it('records no EntityOpened when the selection is cleared', () => {
  const record = vi.fn<Emitter['record']>()
  const graph = store(fakeGraphs(), { record })

  graph.getState().select(null)

  expect(record).not.toHaveBeenCalledWith('EntityOpened', expect.anything())
})

it('records EntityOpened when expandNode selects a node, via the same default source', async () => {
  const record = vi.fn<Emitter['record']>()
  const neighborhood = vi.fn().mockResolvedValue(hoodOf(node()))
  const graph = store(fakeGraphs({ neighborhood }), { record })

  await graph.getState().expandNode('ada')

  expect(record).toHaveBeenCalledWith('EntityOpened', { entity_id: 'ada', source: 'graph' })
})

it('records SearchPerformed with the term and how many results came back', async () => {
  const record = vi.fn<Emitter['record']>()
  const ada = node()
  const search = vi.fn().mockResolvedValue({ entities: [ada], truncated: false })
  const graph = store(fakeGraphs({ search }), { record })

  await graph.getState().search('ada')

  expect(record).toHaveBeenCalledWith('SearchPerformed', { query_text: 'ada', result_count: 1 })
})

it('records EmptyResultEncountered alongside SearchPerformed when nothing matches', async () => {
  const record = vi.fn<Emitter['record']>()
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const graph = store(fakeGraphs({ search }), { record })

  await graph.getState().search('nobody')

  expect(record).toHaveBeenCalledWith('SearchPerformed', {
    query_text: 'nobody',
    result_count: 0,
  })
  expect(record).toHaveBeenCalledWith('EmptyResultEncountered', {
    where: 'graph-search',
    query_length: 6,
  })
})

it('records no ActionRetried for the first search', async () => {
  const record = vi.fn<Emitter['record']>()
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const graph = store(fakeGraphs({ search }), { record })

  await graph.getState().search('ada')

  expect(record).not.toHaveBeenCalledWith('ActionRetried', expect.anything())
})

it('records ActionRetried when the identical search is pressed again', async () => {
  const record = vi.fn<Emitter['record']>()
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const graph = store(fakeGraphs({ search }), { record })

  await graph.getState().search('ada')
  await graph.getState().search('ada')

  expect(record).toHaveBeenCalledWith('ActionRetried', {
    action_kind: 'search',
    attempt_number: 2,
  })
})

it('does not treat a changed search as a retry', async () => {
  const record = vi.fn<Emitter['record']>()
  const search = vi.fn().mockResolvedValue({ entities: [], truncated: false })
  const graph = store(fakeGraphs({ search }), { record })

  await graph.getState().search('ada')
  await graph.getState().search('grace')

  expect(record).not.toHaveBeenCalledWith('ActionRetried', expect.anything())
})

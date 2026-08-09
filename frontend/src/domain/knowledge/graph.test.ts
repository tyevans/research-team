import { describe, expect, it } from 'vitest'

import {
  edgesOf,
  emptyGraph,
  expand,
  isExpanded,
  loadWhole,
  remove,
  type GraphView,
  type Neighborhood,
  type WholeGraph,
} from './graph.ts'

// A neighbourhood whose root is `root` and whose entities are `others`, with
// no relationships. Enough to exercise node merging without needing an edge in
// every test.
//
// The root is deliberately *absent* from `entities`, because that is what the
// server sends: `Neighborhood` carries the root in its own field and
// `GraphReadPort.neighborhood` documents that it "is not repeated inside
// `entities`". Fixtures that included it agreed with the bug rather than with
// the API, and kept this suite green while every click in the browser threw.
const hoodWith = (root: string, ...others: readonly string[]): Neighborhood => ({
  root: { id: root, name: root, entityType: 'concept' },
  entities: others.map((id) => ({ id, name: id, entityType: 'concept' })),
  relationships: [],
})

// A neighbourhood carrying a single directed edge from `source` to `target`,
// rooted at `source` -- so `source` arrives only as the root, exactly as the
// route returns it.
const edge = (source: string, target: string): Neighborhood => ({
  root: { id: source, name: source, entityType: 'concept' },
  entities: [{ id: target, name: target, entityType: 'concept' }],
  relationships: [{ source, target, relationshipType: 'advised' }],
})

describe('expand', () => {
  it('keeps the existing node object so d3 does not lose its position', () => {
    // react-force-graph writes x/y onto the node objects themselves. A fresh
    // object for a node already on screen throws its position away and the
    // whole graph jumps on every expansion.
    const first = expand(emptyGraph, hoodWith('prandtl'))
    const second = expand(first, hoodWith('prandtl', 'karman'))

    expect(second.nodes.find((n) => n.id === 'prandtl')).toBe(
      first.nodes.find((n) => n.id === 'prandtl'),
    )
  })

  it('does not duplicate a node arriving from two neighborhoods', () => {
    const view = expand(expand(emptyGraph, hoodWith('a', 'shared')), hoodWith('b', 'shared'))

    expect(view.nodes.filter((n) => n.id === 'shared')).toHaveLength(1)
  })

  it('does not duplicate an edge seen from both of its ends', () => {
    // Edges are directed and keyed on source|target|relationshipType, so
    // advised(a→b) and advised(b→a) are genuinely different edges and both
    // survive. What must collapse is the *same* directed edge arriving twice,
    // which happens because a neighbourhood fetched from either endpoint
    // reports the relationship. `edge('a', 'b')` twice is that case.
    const view = expand(expand(emptyGraph, edge('a', 'b')), edge('a', 'b'))

    expect(view.links).toHaveLength(1)
  })

  it('keeps the reverse of an edge as a distinct link', () => {
    const view = expand(expand(emptyGraph, edge('a', 'b')), edge('b', 'a'))

    expect(view.links).toHaveLength(2)
  })

  it('draws the root, which the server sends beside `entities` rather than in it', () => {
    const view = expand(emptyGraph, hoodWith('prandtl', 'karman'))

    expect(view.nodes.map((n) => n.id).sort()).toEqual(['karman', 'prandtl'])
  })

  it('leaves no link whose endpoint is missing from the node set', () => {
    // d3-force resolves every link endpoint against the node array and throws
    // `node not found: <id>` when one is absent, which takes down the whole
    // canvas rather than dropping the edge. A merge that can emit a dangling
    // link is therefore a crash, not a cosmetic gap.
    const view = expand(expand(emptyGraph, edge('a', 'b')), edge('b', 'c'))
    const ids = new Set(view.nodes.map((n) => n.id))

    for (const link of view.links) {
      expect(ids).toContain(link.source)
      expect(ids).toContain(link.target)
    }
  })

  it('records what has been expanded so a node is not re-fetched', () => {
    const view = expand(emptyGraph, hoodWith('prandtl'))

    expect(isExpanded(view, 'prandtl')).toBe(true)
  })

  it('does not report an unexpanded node as expanded', () => {
    expect(isExpanded(emptyGraph, 'prandtl')).toBe(false)
  })
})

describe('edgesOf', () => {
  it('reports both directions distinctly, with the node at the far end', () => {
    const view = expand(expand(emptyGraph, edge('a', 'b')), edge('c', 'a'))

    const edges = edgesOf(view, 'a')

    expect(edges).toHaveLength(2)
    expect(edges).toContainEqual({
      relationshipType: 'advised',
      direction: 'out',
      other: expect.objectContaining({ id: 'b' }),
    })
    expect(edges).toContainEqual({
      relationshipType: 'advised',
      direction: 'in',
      other: expect.objectContaining({ id: 'c' }),
    })
  })

  it('reads endpoints that d3-force has replaced with node objects', () => {
    // The drawing mutates the very link objects this module hands it, swapping
    // each id for a reference to the node it resolved to. A link read back
    // after the canvas has drawn it once therefore has objects where the type
    // says strings, and a reader that assumed strings would show an entity as
    // having no connections at all the moment it was drawn.
    const view = expand(emptyGraph, edge('a', 'b'))
    const drawn: GraphView = {
      ...view,
      links: view.links.map((link) => ({
        ...link,
        source: view.nodes.find((n) => n.id === 'a')!,
        target: view.nodes.find((n) => n.id === 'b')!,
      })) as unknown as GraphView['links'],
    }

    expect(edgesOf(drawn, 'a')).toEqual([
      {
        relationshipType: 'advised',
        direction: 'out',
        other: expect.objectContaining({ id: 'b' }),
      },
    ])
  })

  it('ignores links that do not touch the node', () => {
    const view = expand(emptyGraph, edge('a', 'b'))

    expect(edgesOf(view, 'zz')).toEqual([])
  })
})

describe('remove', () => {
  it('drops neighbours that arrived only because of the node being removed', () => {
    // `b` came in as a neighbour of `a` and was never asked for. With `a` gone
    // it is a dot connected to nothing, which is the clutter this exists to
    // clear.
    const view = expand(emptyGraph, edge('a', 'b'))

    const after = remove(view, 'a')

    expect(after.nodes).toEqual([])
    expect(after.links).toEqual([])
  })

  it('keeps a node the reader expanded themselves, even once it is unconnected', () => {
    // `b` was expanded in its own right, so it is something the reader asked
    // for. Removing `a` should not take it away as a side effect.
    const view = expand(expand(emptyGraph, edge('a', 'b')), hoodWith('b'))

    const after = remove(view, 'a')

    expect(after.nodes.map((n) => n.id)).toEqual(['b'])
    expect(after.links).toEqual([])
  })

  it('keeps neighbours that are still connected to something else', () => {
    const view = expand(expand(emptyGraph, edge('a', 'b')), edge('c', 'b'))

    const after = remove(view, 'a')

    expect(after.nodes.map((n) => n.id).sort()).toEqual(['b', 'c'])
    expect(after.links).toHaveLength(1)
  })

  it('leaves no link dangling behind a removed node', () => {
    // The same invariant `expand` maintains, from the other direction: d3-force
    // throws on a link whose endpoint is absent, so a removal that orphaned one
    // would crash the canvas rather than tidy it.
    const view = expand(expand(emptyGraph, edge('a', 'b')), edge('b', 'c'))

    const after = remove(view, 'b')
    const ids = new Set(after.nodes.map((n) => n.id))

    for (const link of after.links) {
      expect(ids).toContain(link.source)
      expect(ids).toContain(link.target)
    }
  })

  it('forgets that a removed node was expanded, so it can be drawn again', () => {
    const view = expand(emptyGraph, hoodWith('a'))

    const after = remove(view, 'a')

    expect(isExpanded(after, 'a')).toBe(false)
  })
})

describe('loadWhole', () => {
  const graph = (
    ids: readonly string[],
    links: readonly (readonly [string, string])[] = [],
    truncated = false,
  ): WholeGraph => ({
    entities: ids.map((id) => ({ id, name: id, entityType: 'concept' })),
    relationships: links.map(([source, target]) => ({
      source,
      target,
      relationshipType: 'advised',
    })),
    truncated,
  })

  it('draws every node and edge it was given', () => {
    const view = loadWhole(emptyGraph, graph(['a', 'b'], [['a', 'b']]))

    expect(view.nodes.map((n) => n.id)).toEqual(['a', 'b'])
    expect(view.links).toHaveLength(1)
  })

  it('replaces the drawing rather than merging into it', () => {
    // A node the server has since merged away would otherwise survive on the
    // canvas forever, because it once arrived in a neighbourhood.
    const before = expand(emptyGraph, hoodWith('gone', 'a'))

    const view = loadWhole(before, graph(['a']))

    expect(view.nodes.map((n) => n.id)).toEqual(['a'])
  })

  it('keeps the existing node object so d3 does not lose its position', () => {
    const before = expand(emptyGraph, hoodWith('a'))
    const original = before.nodes.find((n) => n.id === 'a')

    const view = loadWhole(before, graph(['a', 'b']))

    expect(view.nodes.find((n) => n.id === 'a')).toBe(original)
  })

  it('counts a complete graph as expanded everywhere, since nothing is behind it', () => {
    const view = loadWhole(emptyGraph, graph(['a', 'b'], [['a', 'b']]))

    expect(isExpanded(view, 'a')).toBe(true)
    expect(isExpanded(view, 'b')).toBe(true)
  })

  it('promises nothing about a truncated graph, whose edges are also cut', () => {
    const view = loadWhole(emptyGraph, graph(['a', 'b'], [['a', 'b']], true))

    expect(isExpanded(view, 'a')).toBe(false)
    expect(isExpanded(view, 'b')).toBe(false)
  })

  it('leaves no link dangling, the invariant d3-force crashes on', () => {
    const view = loadWhole(emptyGraph, graph(['a', 'b'], [['a', 'b']]))
    const ids = new Set(view.nodes.map((n) => n.id))

    for (const link of view.links) {
      expect(ids).toContain(link.source)
      expect(ids).toContain(link.target)
    }
  })
})

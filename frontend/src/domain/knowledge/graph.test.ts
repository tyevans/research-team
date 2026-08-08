import { describe, expect, it } from 'vitest'

import {
  edgesOf,
  emptyGraph,
  expand,
  isExpanded,
  type GraphView,
  type Neighborhood,
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

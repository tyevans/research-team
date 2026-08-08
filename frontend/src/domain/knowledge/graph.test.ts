import { describe, expect, it } from 'vitest'

import { emptyGraph, expand, isExpanded, type Neighborhood } from './graph.ts'

// A neighbourhood whose root is `root` and whose entities are `root` plus
// `others`, with no relationships. Enough to exercise node merging without
// needing an edge in every test.
const hoodWith = (root: string, ...others: readonly string[]): Neighborhood => ({
  root: { id: root, name: root, entityType: 'concept' },
  entities: [root, ...others].map((id) => ({ id, name: id, entityType: 'concept' })),
  relationships: [],
})

// A neighbourhood carrying a single directed edge from `source` to `target`,
// rooted at `source`.
const edge = (source: string, target: string): Neighborhood => ({
  root: { id: source, name: source, entityType: 'concept' },
  entities: [
    { id: source, name: source, entityType: 'concept' },
    { id: target, name: target, entityType: 'concept' },
  ],
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

  it('records what has been expanded so a node is not re-fetched', () => {
    const view = expand(emptyGraph, hoodWith('prandtl'))

    expect(isExpanded(view, 'prandtl')).toBe(true)
  })

  it('does not report an unexpanded node as expanded', () => {
    expect(isExpanded(emptyGraph, 'prandtl')).toBe(false)
  })
})

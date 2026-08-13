import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import {
  emptyGraph,
  type GraphLink,
  type GraphNode,
  type GraphView,
} from '@domain/knowledge/graph.ts'

import { GraphLegend } from './GraphLegend.tsx'

const node = (id: string, entityType: string): GraphNode => ({ id, name: id, entityType })

const viewOf = (nodes: readonly GraphNode[]): GraphView => ({ ...emptyGraph, nodes })

it('renders nothing when nothing is drawn', () => {
  const { container } = render(<GraphLegend view={emptyGraph} />)

  // A key to an empty picture is a box that explains nothing.
  expect(container).toBeEmptyDOMElement()
})

it('names each entity type on the canvas once, with how many there are', () => {
  render(
    <GraphLegend view={viewOf([node('a', 'fact'), node('b', 'fact'), node('c', 'hypothesis')])} />,
  )

  const rows = screen.getAllByRole('listitem').map((row) => row.textContent)
  expect(rows).toEqual(['fact2', 'hypothesis1'])
})

it('puts the commonest type first, since that is most of what is on screen', () => {
  render(
    <GraphLegend view={viewOf([node('a', 'rare'), node('b', 'common'), node('c', 'common')])} />,
  )

  const rows = screen.getAllByRole('listitem').map((row) => row.textContent)
  expect(rows[0]).toContain('common')
})

it('says what a hollow node means, which is the only place that rule is written', () => {
  render(<GraphLegend view={viewOf([node('a', 'fact')])} />)

  expect(screen.getByText(/hollow nodes have more to pull in/i)).toBeInTheDocument()
})

it('drops the hollow-node rule when the graph is drawn whole', () => {
  // Every node expanded means every node filled, and a key describing a shape
  // the canvas is not using sends the reader looking for one.
  const drawn = viewOf([node('a', 'fact'), node('b', 'fact')])
  render(<GraphLegend view={{ ...drawn, expanded: new Set(['a', 'b']) }} />)

  expect(screen.queryByText(/hollow nodes have more to pull in/i)).not.toBeInTheDocument()
  // The colour key is still the reason this box exists.
  expect(screen.getAllByRole('listitem')).toHaveLength(1)
})

it('says what a dashed edge means, when the view has one', () => {
  const link: GraphLink = {
    source: 'a',
    target: 'b',
    relationshipType: 'temporally-near',
    inferred: true,
  }
  render(
    <GraphLegend view={{ ...viewOf([node('a', 'fact'), node('b', 'fact')]), links: [link] }} />,
  )

  expect(screen.getByText(/dashed edges are inferred from dates/i)).toBeInTheDocument()
})

it('drops the dashed-edge rule when no edge on the canvas is inferred', () => {
  // No inferred link means no dashed line, and a key describing a mark that
  // is not on the canvas sends the reader hunting for one.
  const link: GraphLink = { source: 'a', target: 'b', relationshipType: 'asserted' }
  render(
    <GraphLegend view={{ ...viewOf([node('a', 'fact'), node('b', 'fact')]), links: [link] }} />,
  )

  expect(screen.queryByText(/dashed edges are inferred from dates/i)).not.toBeInTheDocument()
})

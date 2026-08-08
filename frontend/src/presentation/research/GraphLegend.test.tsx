import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { emptyGraph, type GraphNode, type GraphView } from '@domain/knowledge/graph.ts'

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

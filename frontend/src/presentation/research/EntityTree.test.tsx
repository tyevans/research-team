import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { EntityGroup } from '@domain/knowledge/entity-tree.ts'

import { EntityTree } from './EntityTree.tsx'

const groups: readonly EntityGroup[] = [
  {
    entityType: 'concept',
    entities: [
      { id: 'c1', name: 'Backprop', entityType: 'concept' },
      { id: 'c2', name: 'Gradient descent', entityType: 'concept' },
    ],
  },
  { entityType: 'person', entities: [{ id: 'p1', name: 'Hinton', entityType: 'person' }] },
]

const noop = () => {}

describe('EntityTree', () => {
  it('names every type, with how many entities are under it', () => {
    render(
      <EntityTree
        groups={groups}
        open={new Set()}
        selected={null}
        onToggle={noop}
        onSelect={noop}
      />,
    )

    expect(screen.getByRole('button', { name: /concept/ })).toHaveTextContent('2')
    expect(screen.getByRole('button', { name: /person/ })).toHaveTextContent('1')
  })

  /** The assertion is the entity's name, not that the component rendered: a
   *  test asserting only the headings would pass with every row dropped. */
  it('shows an open group’s entities and hides a closed one’s', () => {
    render(
      <EntityTree
        groups={groups}
        open={new Set(['concept'])}
        selected={null}
        onToggle={noop}
        onSelect={noop}
      />,
    )

    expect(screen.getByText('Backprop')).toBeInTheDocument()
    expect(screen.getByText('Gradient descent')).toBeInTheDocument()
    expect(screen.queryByText('Hinton')).not.toBeInTheDocument()
  })

  it('says which groups are open, for a screen reader as well as a caret', () => {
    render(
      <EntityTree
        groups={groups}
        open={new Set(['concept'])}
        selected={null}
        onToggle={noop}
        onSelect={noop}
      />,
    )

    expect(screen.getByRole('button', { name: /concept/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('button', { name: /person/ })).toHaveAttribute('aria-expanded', 'false')
  })

  it('asks for a group to be toggled rather than toggling it itself', async () => {
    const onToggle = vi.fn()
    render(
      <EntityTree
        groups={groups}
        open={new Set()}
        selected={null}
        onToggle={onToggle}
        onSelect={noop}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: /person/ }))

    expect(onToggle).toHaveBeenCalledWith('person')
  })

  it('selects by id, not by name', async () => {
    const onSelect = vi.fn()
    render(
      <EntityTree
        groups={groups}
        open={new Set(['person'])}
        selected={null}
        onToggle={noop}
        onSelect={onSelect}
      />,
    )

    await userEvent.click(screen.getByRole('button', { name: 'Hinton' }))

    expect(onSelect).toHaveBeenCalledWith('p1')
  })

  /** `aria-current` rather than a colour alone: which row is selected is
   *  information, and a border is not available to a screen reader. */
  it('marks the selected row', () => {
    render(
      <EntityTree
        groups={groups}
        open={new Set(['person'])}
        selected="p1"
        onToggle={noop}
        onSelect={noop}
      />,
    )

    expect(screen.getByRole('button', { name: 'Hinton' })).toHaveAttribute('aria-current', 'true')
  })
})

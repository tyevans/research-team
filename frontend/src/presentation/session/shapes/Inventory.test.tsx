import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { Inventory } from './Inventory.tsx'
import { inventory } from './fixtures.ts'

describe('Inventory', () => {
  it('sorts by size and puts every bar on the largest item’s scale', () => {
    render(<Inventory artifact={inventory} phase="settled" />)
    const names = screen.getAllByTestId('inventory-item').map((node) => node.dataset['name'])
    expect(names).toEqual(['reedsy.com', 'fredner.org', 'tidepooloctopus.com'])
    expect(screen.getAllByTestId('bar-fill')[0]).toHaveStyle({ width: '100%' })
    expect(screen.getAllByTestId('bar-fill')[1]).toHaveStyle({ width: '33.33%' })
  })

  it('reads the unit off the artifact rather than assuming characters', () => {
    // A list mixing characters and bytes on one bar axis is the multi-column
    // grid mistake in miniature: two marks that look comparable and are not.
    // The unit travels on the parent for that reason, and the renderer has to
    // actually read it.
    render(<Inventory artifact={{ ...inventory, unit: 'bytes' }} phase="settled" />)
    expect(screen.getByText('11.7 KB')).toBeInTheDocument()
  })

  it('formats a character count compactly', () => {
    render(<Inventory artifact={inventory} phase="settled" />)
    expect(screen.getByText('12.0k')).toBeInTheDocument()
  })

  it('caps at five with an expander', () => {
    const many = {
      ...inventory,
      total: 9,
      items: Array.from({ length: 9 }, (_, index) => ({
        item_id: `i${index}`,
        title: `item ${index}`,
        label: null,
        size: 100 - index,
        detail: null,
      })),
    }
    render(<Inventory artifact={many} phase="settled" />)
    expect(screen.getAllByTestId('inventory-item')).toHaveLength(5)
    expect(screen.getByRole('button', { name: /4 more/ })).toBeInTheDocument()
  })
})

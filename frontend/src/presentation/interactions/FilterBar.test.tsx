import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { INTERACTION_KINDS, NO_INTERACTION_FILTERS } from '../routing/routes.ts'
import { FilterBar } from './FilterBar.tsx'

describe('FilterBar', () => {
  it('offers every kind in the vocabulary, including ones the data has never held', () => {
    // The point of the whole pane: a filter built from the table's contents
    // cannot express "show me the thing I think is broken", because the thing
    // that is broken is the thing with no rows.
    render(<FilterBar filters={NO_INTERACTION_FILTERS} seenViews={[]} onChange={vi.fn()} />)
    for (const kind of INTERACTION_KINDS) {
      expect(screen.getByRole('checkbox', { name: kind })).toBeInTheDocument()
    }
  })

  it('reads its ticks from the filters it was given, not from state of its own', () => {
    render(
      <FilterBar
        filters={{ ...NO_INTERACTION_FILTERS, kinds: ['ViewExited'] }}
        seenViews={[]}
        onChange={vi.fn()}
      />,
    )
    expect(screen.getByRole('checkbox', { name: 'ViewExited' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'ViewEntered' })).not.toBeChecked()
  })

  it('reports a ticked kind out rather than keeping it', async () => {
    const onChange = vi.fn()
    render(<FilterBar filters={NO_INTERACTION_FILTERS} seenViews={[]} onChange={onChange} />)
    await userEvent.click(screen.getByRole('checkbox', { name: 'SearchPerformed' }))
    expect(onChange).toHaveBeenCalledWith({
      ...NO_INTERACTION_FILTERS,
      kinds: ['SearchPerformed'],
    })
  })

  it('unticks a kind that was already on', async () => {
    const onChange = vi.fn()
    render(
      <FilterBar
        filters={{ ...NO_INTERACTION_FILTERS, kinds: ['ViewExited', 'ViewEntered'] }}
        seenViews={[]}
        onChange={onChange}
      />,
    )
    await userEvent.click(screen.getByRole('checkbox', { name: 'ViewExited' }))
    expect(onChange).toHaveBeenCalledWith({
      ...NO_INTERACTION_FILTERS,
      kinds: ['ViewEntered'],
    })
  })

  it('offers the views it was shown, plus any the filter names but the window no longer holds', () => {
    render(
      <FilterBar
        filters={{ ...NO_INTERACTION_FILTERS, views: ['interactions'] }}
        seenViews={['home', 'project/catalog']}
        onChange={vi.fn()}
      />,
    )
    // Without the second half, narrowing the window until a filtered view has
    // no rows leaves a tick nobody can remove.
    expect(screen.getByRole('checkbox', { name: 'interactions' })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'home' })).toBeInTheDocument()
  })

  it('writes an absolute instant for a window preset, so the reading stays linkable', async () => {
    const onChange = vi.fn()
    render(<FilterBar filters={NO_INTERACTION_FILTERS} seenViews={[]} onChange={onChange} />)
    await userEvent.click(screen.getByRole('button', { name: 'last hour' }))
    const [next] = onChange.mock.calls[0] as [{ since: string | null; until: string | null }]
    expect(next.until).toBeNull()
    expect(Date.now() - Date.parse(next.since as string)).toBeGreaterThan(3_500_000)
    expect(Date.now() - Date.parse(next.since as string)).toBeLessThan(3_700_000)
  })

  it('clears the window rather than naming one when "all" is pressed', async () => {
    const onChange = vi.fn()
    render(
      <FilterBar
        filters={{ ...NO_INTERACTION_FILTERS, since: '2026-08-01T00:00:00Z' }}
        seenViews={[]}
        onChange={onChange}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'all' }))
    expect(onChange).toHaveBeenCalledWith({ ...NO_INTERACTION_FILTERS, since: null, until: null })
  })

  it('commits a typed id once, on Enter, rather than on every keystroke', async () => {
    const onChange = vi.fn()
    render(<FilterBar filters={NO_INTERACTION_FILTERS} seenViews={[]} onChange={onChange} />)
    await userEvent.type(screen.getByLabelText('project'), 'p-7{Enter}')
    expect(onChange).toHaveBeenCalledTimes(1)
    expect(onChange).toHaveBeenCalledWith({ ...NO_INTERACTION_FILTERS, projectId: 'p-7' })
  })

  it('offers no Clear button until there is something to clear', async () => {
    const onChange = vi.fn()
    const { rerender } = render(
      <FilterBar filters={NO_INTERACTION_FILTERS} seenViews={[]} onChange={onChange} />,
    )
    expect(screen.queryByRole('button', { name: 'Clear filters' })).not.toBeInTheDocument()

    rerender(
      <FilterBar
        filters={{ ...NO_INTERACTION_FILTERS, installId: 'in-1' }}
        seenViews={[]}
        onChange={onChange}
      />,
    )
    await userEvent.click(screen.getByRole('button', { name: 'Clear filters' }))
    expect(onChange).toHaveBeenCalledWith(NO_INTERACTION_FILTERS)
  })
})

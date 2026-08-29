import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import { EntityList } from './EntityList.tsx'
import { entityList, tenEntities } from './fixtures.ts'

const named = (name: string) =>
  screen.getAllByTestId('entity').find((node) => node.dataset['name'] === name)

describe('EntityList', () => {
  it('sorts by relationship count', () => {
    render(<EntityList artifact={tenEntities} phase="settled" />)
    const names = screen.getAllByTestId('entity').map((node) => node.dataset['name'])
    expect(names[0]).toBe('science fiction')
  })

  it('caps at five and says how many are behind the expander', () => {
    render(<EntityList artifact={tenEntities} phase="settled" />)
    expect(screen.getAllByTestId('entity')).toHaveLength(5)
    expect(screen.getByRole('button', { name: /5 more/ })).toBeInTheDocument()
  })

  it('separates unlinked entities and does not label them 0', () => {
    // An entity the graph knows by name and has connected to nothing is the
    // most actionable thing this tool returns, and in the paragraph this
    // replaces it was the least visible. `0` reads as a measurement; `–` reads
    // as the absence it is.
    render(<EntityList artifact={entityList} phase="settled" />)
    const orphan = named('magic')
    expect(orphan).toHaveTextContent('–')
    expect(orphan).not.toHaveTextContent('0')
    expect(orphan?.querySelector('[data-testid="stream-name"]')).toHaveAttribute(
      'data-linked',
      'false',
    )
  })

  it('draws no bar for an entity that is on no axis', () => {
    // A fill of width zero is still a bar, and a bar drawn for a value that
    // does not exist puts the entity on a scale it is not on.
    render(<EntityList artifact={entityList} phase="settled" />)
    expect(named('magic')?.querySelector('[data-testid="bar-fill"]')).toBeNull()
    expect(named('science fiction')?.querySelector('[data-testid="bar-fill"]')).not.toBeNull()
  })

  it('spends its five lines on the linked entities first', () => {
    // Five linked and one unlinked: the unlinked one is still shown, because
    // five linked leaves it out only when there are more than five linked.
    render(<EntityList artifact={entityList} phase="settled" />)
    const names = screen.getAllByTestId('entity').map((node) => node.dataset['name'])
    expect(names).toHaveLength(6)
    expect(names[names.length - 1]).toBe('magic')
  })

  it('counts the hidden linked and hidden unlinked separately', () => {
    const crowded = {
      ...tenEntities,
      entities: [
        ...tenEntities.entities,
        { entity_id: 'u1', name: 'unlinked one', entity_type: 'concept', relationship_count: 0 },
        { entity_id: 'u2', name: 'unlinked two', entity_type: 'concept', relationship_count: 0 },
      ],
    }
    render(<EntityList artifact={crowded} phase="settled" />)
    expect(screen.getByRole('button', { name: /5 more · 2 unlinked/ })).toBeInTheDocument()
  })

  it('shows everything when the expander is opened', async () => {
    render(<EntityList artifact={tenEntities} phase="settled" />)
    // By name: the header's argument is a tooltip trigger and therefore also a
    // button, so an unqualified role query matches two controls here.
    await userEvent.click(screen.getByRole('button', { name: /5 more/ }))
    expect(screen.getAllByTestId('entity')).toHaveLength(10)
  })

  it('keeps the search mode reachable rather than dropping it', () => {
    // `mode` exists to make a silent degradation visible -- a console that
    // drops it reintroduces exactly the silence the field was added to break.
    //
    // It used to be a `title` attribute, and the assertion used to be
    // `getByTitle`. It is a `Tooltip` now, per the S-D3 deletion: a `title` is
    // announced on hover and on nothing else, so a reader who is not holding a
    // mouse could not reach the very field that exists to be reachable. What
    // is asserted here is the *trigger* -- a focusable control describing the
    // argument -- because the explanation itself renders only inside an
    // `OverlayHost`, which this bare render has none of. `Tooltip.test.tsx`
    // owns the question of whether an open tooltip shows its text.
    render(<EntityList artifact={tenEntities} phase="settled" />)
    const trigger = screen.getByRole('button', { name: /magic/ })
    expect(trigger).toHaveAttribute('data-state', 'closed')
  })
})

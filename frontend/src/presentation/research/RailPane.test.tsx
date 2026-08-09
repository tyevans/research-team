import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Container } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

import { RailPane } from './RailPane.tsx'

/** Only the port this component reaches for. The rest stay absent on purpose,
 *  the way `use-panes.test.tsx` does it: a fake that implemented everything
 *  would hide which dependency this really has. */
const containerWith = (preferences: InMemoryPreferenceStore): Container =>
  ({ preferences }) as unknown as Container

const show = (preferences = new InMemoryPreferenceStore()) =>
  render(
    <ContainerProvider container={containerWith(preferences)}>
      <RailPane name="topics" title="Topics" label="Topics">
        <p>the queue</p>
      </RailPane>
    </ContainerProvider>,
  )

describe('RailPane', () => {
  it('folds its contents away, and gives them back', async () => {
    show()
    expect(screen.getByText('the queue')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Fold Topics away' }))
    // Unmounted rather than hidden: a list nobody can see should not still be
    // measuring itself.
    expect(screen.queryByText('the queue')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Expand Topics' }))
    expect(screen.getByText('the queue')).toBeInTheDocument()
  })

  it('stays folded across a reload', async () => {
    const preferences = new InMemoryPreferenceStore()
    const first = show(preferences)
    await userEvent.click(screen.getByRole('button', { name: 'Fold Topics away' }))
    first.unmount()

    show(preferences)
    expect(screen.queryByText('the queue')).not.toBeInTheDocument()
  })

  it('leaves another view’s stored layout alone', async () => {
    const preferences = new InMemoryPreferenceStore()
    preferences.setCollapsedPanes('session', ['timeline'])

    show(preferences)
    await userEvent.click(screen.getByRole('button', { name: 'Fold Topics away' }))

    // The two views shared one stored list before this change, so the second
    // writer erased the first's layout. Reverting the grouping fails here.
    expect(preferences.collapsedPanes('session')).toEqual(['timeline'])
    expect(preferences.collapsedPanes('research')).toEqual(['topics'])
  })
})

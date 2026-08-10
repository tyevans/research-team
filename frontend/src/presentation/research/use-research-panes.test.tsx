import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { Container } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InMemoryPreferenceStore } from '@infrastructure/storage/preference-store.ts'

import { Pane } from '../layout/Pane.tsx'
import { useResearchPanes } from './use-research-panes.ts'

/** Only the port this hook reaches for. The rest stay absent on purpose, the
 *  way `use-session-panes.test.tsx` does it: a fake that implemented
 *  everything would hide which dependency this really has. */
const containerWith = (preferences: InMemoryPreferenceStore): Container =>
  ({ preferences }) as unknown as Container

/** The rail, reduced to the part under test: two panes driven by one hook,
 *  which is the arrangement `ResearchView` uses. Two rather than one because
 *  the bug this hook exists to make impossible needs two to show up. */
const Rail = () => {
  const { folded, toggle } = useResearchPanes()
  return (
    <>
      <Pane
        id="topics"
        label="Topics"
        collapseTo="strip"
        unmountWhenCollapsed
        collapsed={folded.has('topics')}
        onToggle={() => toggle('topics')}
      >
        <p>the queue</p>
      </Pane>
      <Pane
        id="documents"
        label="Documents"
        collapseTo="strip"
        unmountWhenCollapsed
        collapsed={folded.has('documents')}
        onToggle={() => toggle('documents')}
      >
        <p>the corpus</p>
      </Pane>
    </>
  )
}

const show = (preferences = new InMemoryPreferenceStore()) =>
  render(
    <ContainerProvider container={containerWith(preferences)}>
      <Rail />
    </ContainerProvider>,
  )

describe('the research rail’s fold state', () => {
  it('folds a pane away, and gives it back', async () => {
    show()
    expect(screen.getByText('the queue')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Collapse Topics' }))
    // Unmounted rather than hidden: a list nobody can see should not still be
    // measuring itself, and the document list's virtualizer caches a
    // zero-height scroller if it is left mounted behind a fold.
    expect(screen.queryByText('the queue')).not.toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Expand Topics' }))
    expect(screen.getByText('the queue')).toBeInTheDocument()
  })

  it('stays folded across a reload', async () => {
    const preferences = new InMemoryPreferenceStore()
    const first = show(preferences)
    await userEvent.click(screen.getByRole('button', { name: 'Collapse Topics' }))
    first.unmount()

    show(preferences)
    expect(screen.queryByText('the queue')).not.toBeInTheDocument()
  })

  /** The reason the set is owned once rather than per pane.
   *
   * `RailPane` gave every pane its own copy of the fold state and its own
   * writer to one stored list, so a write had to re-read the list rather than
   * trust what it had rendered from -- a comment in that file said so. Folding
   * two panes in a row is what breaks the version without the re-read: the
   * second write is computed from a list read before the first landed and
   * stores only itself.
   *
   * This would pass against `RailPane` too, which had the re-read. What it
   * pins is that the arrangement replacing it does not need one -- revert to
   * two independent `useState` copies and this fails.
   */
  it('remembers both panes when they are folded one after the other', async () => {
    const preferences = new InMemoryPreferenceStore()
    show(preferences)

    await userEvent.click(screen.getByRole('button', { name: 'Collapse Topics' }))
    await userEvent.click(screen.getByRole('button', { name: 'Collapse Documents' }))

    expect([...preferences.collapsedPanes('research')].sort()).toEqual(['documents', 'topics'])
  })

  /** Unlike the session panes, the rail lets every one of its panes fold at
   *  once. That is safe here and only here: a `strip` leaves its head -- title
   *  and toggle -- on screen, so nothing becomes unreachable. `Split`'s
   *  unconditional refusal is what this view would have inherited by using it,
   *  and it would have been wrong. */
  it('allows every pane to be folded, because a folded pane keeps its toggle', async () => {
    show()

    await userEvent.click(screen.getByRole('button', { name: 'Collapse Topics' }))
    await userEvent.click(screen.getByRole('button', { name: 'Collapse Documents' }))

    expect(screen.queryByText('the queue')).not.toBeInTheDocument()
    expect(screen.queryByText('the corpus')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand Topics' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Expand Documents' })).toBeInTheDocument()
  })

  it('leaves another view’s stored layout alone', async () => {
    const preferences = new InMemoryPreferenceStore()
    preferences.setCollapsedPanes('session', ['timeline'])

    show(preferences)
    await userEvent.click(screen.getByRole('button', { name: 'Collapse Topics' }))

    // The two views shared one stored list before the group was split, so the
    // second writer erased the first's layout. Reverting the grouping fails
    // here.
    expect(preferences.collapsedPanes('session')).toEqual(['timeline'])
    expect(preferences.collapsedPanes('research')).toEqual(['topics'])
  })
})

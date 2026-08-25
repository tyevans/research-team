import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'

import type { AreaMember } from '@domain/knowledge/curriculum.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { CourseMembers } from './CourseMembers.tsx'

const project = ProjectId('11111111-1111-1111-1111-111111111111')

const member = (over: Partial<AreaMember> & { name: string }): AreaMember => ({
  entityId: `id-${over.name}`,
  entityType: 'person',
  centrality: 1,
  temporal: null,
  ...over,
})

/** More than `FILTER_ABOVE` (12), so the filter box is present. Named for the
 *  property rather than the number: a test that says "thirteen" reads as a
 *  coincidence, and this one depends on the threshold being crossed. */
const enoughToFilter = (): AreaMember[] =>
  Array.from({ length: 13 }, (_, index) => member({ name: `Person ${index}` }))

const show = (members: readonly AreaMember[]) =>
  render(<CourseMembers projectId={project} members={members} />)

const fold = () => screen.getByRole('button', { name: /entities in this cluster/ })

describe('CourseMembers', () => {
  it('is collapsed by default, showing the count and none of the names', () => {
    show([member({ name: 'Caesar' })])

    expect(fold()).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('link', { name: 'Caesar' })).not.toBeInTheDocument()
  })

  it('announces the count on the toggle itself', () => {
    show([member({ name: 'Caesar' }), member({ name: 'Pompey' })])

    expect(fold()).toHaveAccessibleName('2 entities in this cluster')
  })

  it('reveals the names when the fold is opened, and hides them again', async () => {
    const user = userEvent.setup()
    show([member({ name: 'Caesar' })])

    await user.click(fold())
    expect(fold()).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('link', { name: 'Caesar' })).toBeInTheDocument()

    await user.click(fold())
    expect(screen.queryByRole('link', { name: 'Caesar' })).not.toBeInTheDocument()
  })

  it('opens from the keyboard alone', async () => {
    const user = userEvent.setup()
    show([member({ name: 'Caesar' })])

    await user.tab()
    expect(fold()).toHaveFocus()
    await user.keyboard('{Enter}')

    expect(screen.getByRole('link', { name: 'Caesar' })).toBeInTheDocument()
  })

  it('links each member into its entity facet', async () => {
    const user = userEvent.setup()
    show([member({ name: 'Caesar' })])
    await user.click(fold())

    expect(screen.getByRole('link', { name: 'Caesar' }).getAttribute('href')).toContain('id-Caesar')
  })

  it('groups by type, with each type carrying its own count and fold', async () => {
    const user = userEvent.setup()
    show([
      member({ name: 'Caesar', entityType: 'person' }),
      member({ name: 'Pompey', entityType: 'person' }),
      member({ name: 'Rubicon', entityType: 'place' }),
    ])
    await user.click(fold())

    const people = screen.getByRole('button', { name: /^person/ })
    expect(people).toHaveAccessibleName('person 2')
    expect(screen.getByRole('button', { name: /^place/ })).toHaveAccessibleName('place 1')
  })

  it('opens every type group once the fold is open', async () => {
    const user = userEvent.setup()
    show([member({ name: 'Caesar', entityType: 'person' })])
    await user.click(fold())

    expect(screen.getByRole('button', { name: /^person/ })).toHaveAttribute('aria-expanded', 'true')
  })

  it('folds one type away without touching the others', async () => {
    const user = userEvent.setup()
    show([
      member({ name: 'Caesar', entityType: 'person' }),
      member({ name: 'Rubicon', entityType: 'place' }),
    ])
    await user.click(fold())
    await user.click(screen.getByRole('button', { name: /^person/ }))

    expect(screen.queryByRole('link', { name: 'Caesar' })).not.toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Rubicon' })).toBeInTheDocument()
  })

  it('drops the type off the rows, because the group heading carries it', async () => {
    const user = userEvent.setup()
    show([member({ name: 'Caesar', entityType: 'person' })])
    await user.click(fold())

    const row = screen.getByRole('link', { name: 'Caesar' }).closest('li')
    expect(row).not.toBeNull()
    expect(within(row as HTMLElement).queryByText('person')).not.toBeInTheDocument()
  })

  it('shows a temporal string beside the name when there is one', async () => {
    const user = userEvent.setup()
    show([member({ name: 'Caesar', temporal: '100 BC - 44 BC' })])
    await user.click(fold())

    expect(screen.getByText('100 BC - 44 BC')).toBeInTheDocument()
  })

  it('offers no filter for a list short enough to read at a glance', async () => {
    const user = userEvent.setup()
    show([member({ name: 'Caesar' })])
    await user.click(fold())

    expect(screen.queryByRole('searchbox')).not.toBeInTheDocument()
  })

  it('offers a filter once the list is long', async () => {
    const user = userEvent.setup()
    show(enoughToFilter())
    await user.click(fold())

    expect(screen.getByRole('searchbox', { name: 'Filter these entities' })).toBeInTheDocument()
  })

  it('narrows the list as the filter is typed', async () => {
    const user = userEvent.setup()
    const members = [...enoughToFilter(), member({ name: 'Caesar' })]
    show(members)
    await user.click(fold())
    await user.type(screen.getByRole('searchbox'), 'caes')

    expect(screen.getByRole('link', { name: 'Caesar' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Person 0' })).not.toBeInTheDocument()
  })

  it('announces how many of the whole a filter kept', async () => {
    const user = userEvent.setup()
    show([...enoughToFilter(), member({ name: 'Caesar' })])
    await user.click(fold())
    await user.type(screen.getByRole('searchbox'), 'caes')

    expect(screen.getByRole('status')).toHaveTextContent('1 of 14 match')
  })

  it('says nothing about counts until a filter is actually typed', async () => {
    const user = userEvent.setup()
    show(enoughToFilter())
    await user.click(fold())

    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('drops a type heading whose members all fail the filter', async () => {
    const user = userEvent.setup()
    show([...enoughToFilter(), member({ name: 'Rubicon', entityType: 'place' })])
    await user.click(fold())
    await user.type(screen.getByRole('searchbox'), 'person')

    expect(screen.queryByRole('button', { name: /^place/ })).not.toBeInTheDocument()
  })

  it('says so when a filter matches nothing, rather than showing an empty fold', async () => {
    const user = userEvent.setup()
    show(enoughToFilter())
    await user.click(fold())
    await user.type(screen.getByRole('searchbox'), 'zzzz')

    expect(screen.getByText(/Nothing matched/)).toBeInTheDocument()
  })

  it('offers no fold at all for a cluster with no members', () => {
    show([])

    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getByText('No entities in this cluster.')).toBeInTheDocument()
  })
})

import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { EntityHead } from '@domain/entity/entity-head.ts'

import { EntityRef } from './EntityRef.tsx'

/** The `Ref` density's two promises: it never fetches in order to name a
 *  thing, and it does not let an id pass for a name.
 *
 *  Both are structural and jsdom can hold both, which is unusual for this
 *  project's presentation tests and is the reason this file is worth having:
 *  what a ref renders is entirely a function of its props.
 */

const project: EntityHead = {
  kind: 'project',
  id: '3f2a1b9c-dead-beef-0000-000000000000',
  label: 'apollo',
}
const session: EntityHead = {
  kind: 'session',
  id: '7d41e0aa-dead-beef-0000-000000000000',
  label: null,
}

it('uses the name when it has one', () => {
  render(<EntityRef head={project} />)
  expect(screen.getByText('apollo')).toBeInTheDocument()
})

it('falls back to a short id, visibly marked as one', () => {
  const { container } = render(<EntityRef head={session} />)

  // The short id is the console's existing convention — `Breadcrumbs` names a
  // project this way deliberately, to avoid a request on every session load.
  expect(screen.getByText('7d41e0aa')).toBeInTheDocument()
  // Marked, because a short id in the same face as a name reads as a name and
  // a reader cannot tell the console does not know what this is called.
  expect(container.querySelector('.ent-ref-id')).not.toBeNull()
})

it('does not mark a real name as an id', () => {
  const { container } = render(<EntityRef head={project} />)
  expect(container.querySelector('.ent-ref-id')).toBeNull()
})

it('treats a blank label as no label', () => {
  // A name the backend sent as an empty string is not a name, and rendering it
  // produces a ref with nothing in it — a reference to something the reader
  // cannot identify at all, which is worse than the id.
  render(<EntityRef head={{ ...project, label: '   ' }} />)
  expect(screen.getByText('3f2a1b9c')).toBeInTheDocument()
})

it('renders a link when it has somewhere to go', () => {
  render(<EntityRef head={project} href="/project/3f2a" />)

  // L-§9.3: "Nothing on the page is a link. Every navigation is a `<button>`
  // calling `navigate()`. No ⌘-click, no middle-click, no copy-link, no
  // status-bar preview." A real anchor is what gives all four back.
  expect(screen.getByRole('link', { name: 'apollo' })).toHaveAttribute('href', '/project/3f2a')
})

it('renders plain text when it does not, rather than a dead link', () => {
  const { container } = render(<EntityRef head={project} />)

  // C-F62's distinction: muted text with a reason, deliberately not a disabled
  // control. A disabled link is a thing a reader tries to click.
  expect(screen.queryByRole('link')).toBeNull()
  // The anchor element itself, not just the role, and the difference caught a
  // real hole: a mutation that always took the anchor branch produced
  // `<a>` with no `href`, which has no `link` role either — so the role check
  // alone passed while the markup was wrong, and `a.ent-ref:hover` would have
  // styled a non-link as one.
  expect(container.querySelector('a')).toBeNull()
  expect(screen.getByText('apollo')).toBeInTheDocument()
})

it('keeps a prefix attached to the name it qualifies', () => {
  const { container } = render(<EntityRef head={session} prefix="held by" />)

  // One element, so `held by 3f2a1b9c` cannot wrap into two fragments that
  // read as unrelated in a narrow rail.
  const ref = container.querySelector('.ent-ref')
  expect(ref?.textContent).toBe('held by 7d41e0aa')
})

it('carries its kind for a stylesheet and for a reader of the DOM', () => {
  const { container } = render(<EntityRef head={project} />)
  expect(container.querySelector('[data-kind="project"]')).not.toBeNull()
})

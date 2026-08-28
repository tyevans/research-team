import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import type { Route } from '../routing/routes.ts'
import { projectHref, homeHref } from '../routing/routes.ts'
import { Breadcrumbs } from './Breadcrumbs.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

it('names the selected facet and links back to the tree', () => {
  const route: Route = { name: 'project', id: PROJECT, selection: { facet: 'entity', id: null } }
  render(<Breadcrumbs route={route} session={null} projectName={null} />)

  expect(screen.getByText('entity')).toBeInTheDocument()
  // Falls back to the id's short form because the crumb is drawn before the
  // project read that carries the name has settled.
  expect(screen.getByText(PROJECT.slice(0, 8))).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'projects' })).toHaveAttribute('href', homeHref())
})

it('prefers the loaded project name over the id', () => {
  const route: Route = { name: 'project', id: PROJECT, selection: { facet: 'entity', id: null } }
  render(<Breadcrumbs route={route} session={null} projectName="Spaced repetition" />)

  expect(screen.getByText('Spaced repetition')).toBeInTheDocument()
})

it('offers the project itself as the way out of a selection', () => {
  // The step a reader wants after following somebody's link into one topic:
  // the same project with nothing selected. Dead text before this, because
  // there was one page per noun and no "the project, plainly".
  const route: Route = { name: 'project', id: PROJECT, selection: { facet: 'topic', id: 't1' } }
  render(<Breadcrumbs route={route} session={null} projectName={null} />)

  expect(screen.getByRole('link', { name: PROJECT.slice(0, 8) })).toHaveAttribute(
    'href',
    projectHref(PROJECT),
  )
})

it('leaves the project crumb unlinked when it is already what you are on', () => {
  const route: Route = { name: 'project', id: PROJECT, selection: null }
  render(<Breadcrumbs route={route} session={null} projectName={null} />)

  expect(screen.queryByRole('link', { name: PROJECT.slice(0, 8) })).not.toBeInTheDocument()
  expect(screen.getByText(PROJECT.slice(0, 8))).toBeInTheDocument()
})

it("links a session to its project's two pages", () => {
  // The course and research pages link to each other, and neither could be
  // reached from a transcript -- so watching a worker was a one-way trip, out
  // through the session tree and back in. This is the way back.
  const route: Route = { name: 'session', id: SessionId('s1'), at: ScrubPoint.head(), path: null }
  const session = { projectId: PROJECT, events: [] } as unknown as SessionProjection

  render(<Breadcrumbs route={route} session={session} projectName={null} />)

  expect(screen.getByRole('link', { name: 'course' })).toHaveAttribute('href', projectHref(PROJECT))
  expect(screen.getByRole('link', { name: 'research' })).toHaveAttribute(
    'href',
    projectHref(PROJECT, { facet: 'entity', id: null }),
  )
})

it('leaves the project links off a session that belongs to no project', () => {
  const route: Route = { name: 'session', id: SessionId('s1'), at: ScrubPoint.head(), path: null }
  const session = { projectId: null, events: [] } as unknown as SessionProjection

  render(<Breadcrumbs route={route} session={session} projectName={null} />)

  expect(screen.queryByRole('link', { name: 'research' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'course' })).not.toBeInTheDocument()
})

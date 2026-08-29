import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import type { Route } from '../routing/routes.ts'
import { projectHref, homeHref, NO_INTERACTION_FILTERS } from '../routing/routes.ts'
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

it('draws no trail at all on the project list', () => {
  // The root has nowhere to go up to, and the one-item trail it used to draw
  // was a `projects` span wearing the separator's colour -- a crumb that named
  // the page you were already on and could not be clicked. The brand link is
  // the way home from everywhere, so there is nothing left for this to say.
  const { container } = render(
    <Breadcrumbs route={{ name: 'home' }} session={null} projectName={null} />,
  )

  expect(container.querySelector('#crumbs')).not.toBeInTheDocument()
})

it('walks back to the project from its settings page', () => {
  // The defect this is written against: every route that was not `project` or
  // `session` fell through to a dead `projects` span, so the settings page --
  // which is reachable only *from* a project -- had no way back to it.
  const route: Route = {
    name: 'settings',
    scope: 'project',
    scopeId: PROJECT,
    group: null,
  }
  render(<Breadcrumbs route={route} session={null} projectName="Ancient Rome" />)

  expect(screen.getByRole('link', { name: 'projects' })).toHaveAttribute('href', homeHref())
  expect(screen.getByRole('link', { name: 'Ancient Rome' })).toHaveAttribute(
    'href',
    projectHref(PROJECT),
  )
  // The page you are on is named but not linked, the way a project's own crumb
  // is when nothing is selected.
  expect(screen.queryByRole('link', { name: 'settings' })).not.toBeInTheDocument()
  expect(screen.getByText('settings')).toBeInTheDocument()
})

it('falls back to a short id in the settings trail before the name settles', () => {
  const route: Route = {
    name: 'settings',
    scope: 'project',
    scopeId: PROJECT,
    group: null,
  }
  render(<Breadcrumbs route={route} session={null} projectName={null} />)

  expect(screen.getByRole('link', { name: PROJECT.slice(0, 8) })).toHaveAttribute(
    'href',
    projectHref(PROJECT),
  )
})

it('names the scope instead of a project on settings that belong to no project', () => {
  // `#/settings/tenant/<id>` is the same screen over different data, and there
  // is no project to walk back to -- so the trail says which scope you are
  // editing rather than inventing a project link out of a tenant id.
  const route: Route = {
    name: 'settings',
    scope: 'tenant',
    scopeId: 't-1',
    group: null,
  }
  render(<Breadcrumbs route={route} session={null} projectName={null} />)

  expect(screen.getByRole('link', { name: 'projects' })).toHaveAttribute('href', homeHref())
  expect(screen.getByText('tenant settings')).toBeInTheDocument()
  expect(screen.queryByText('t-1')).not.toBeInTheDocument()
})

it('offers the way home from the interaction log', () => {
  // Same fallthrough, same defect: the log is reached from the header on every
  // page and had a dead crumb to go back with.
  const route: Route = { name: 'interactions', filters: NO_INTERACTION_FILTERS }
  render(<Breadcrumbs route={route} session={null} projectName={null} />)

  expect(screen.getByRole('link', { name: 'projects' })).toHaveAttribute('href', homeHref())
  expect(screen.getByText('log')).toBeInTheDocument()
})

import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { Course } from '@domain/project/course.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import type { Route } from '../routing/routes.ts'
import { courseHref, researchHref, treeHref } from '../routing/routes.ts'
import { Breadcrumbs } from './Breadcrumbs.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

it('names the research route and links back to the tree', () => {
  const route: Route = { entity: null, name: 'research', id: PROJECT }
  render(<Breadcrumbs route={route} session={null} course={null} />)

  expect(screen.getByText('research')).toBeInTheDocument()
  // Falls back to the id's short form because the research route does not
  // carry the course query CourseView does -- the same fallback the course
  // crumb uses when the name has not loaded yet.
  expect(screen.getByText(PROJECT.slice(0, 8))).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'sessions' })).toHaveAttribute('href', treeHref())
})

it('prefers the loaded project name over the id on the research crumb', () => {
  const route: Route = { entity: null, name: 'research', id: PROJECT }
  const course = { projectName: 'Spaced repetition' } as Course
  render(<Breadcrumbs route={route} session={null} course={course} />)

  expect(screen.getByText('Spaced repetition')).toBeInTheDocument()
})

it('research href round-trips to the route the breadcrumb was built for', () => {
  expect(researchHref(PROJECT)).toBe(`#/p/${PROJECT}/research`)
})

it("links a session to its project's two pages", () => {
  // The course and research pages link to each other, and neither could be
  // reached from a transcript -- so watching a worker was a one-way trip, out
  // through the session tree and back in. This is the way back.
  const route: Route = { name: 'session', id: SessionId('s1'), at: ScrubPoint.head(), path: null }
  const session = { projectId: PROJECT, events: [] } as unknown as SessionProjection

  render(<Breadcrumbs route={route} session={session} course={null} />)

  expect(screen.getByRole('link', { name: 'course' })).toHaveAttribute('href', courseHref(PROJECT))
  expect(screen.getByRole('link', { name: 'research' })).toHaveAttribute(
    'href',
    researchHref(PROJECT),
  )
})

it('leaves the project links off a session that belongs to no project', () => {
  const route: Route = { name: 'session', id: SessionId('s1'), at: ScrubPoint.head(), path: null }
  const session = { projectId: null, events: [] } as unknown as SessionProjection

  render(<Breadcrumbs route={route} session={session} course={null} />)

  expect(screen.queryByRole('link', { name: 'research' })).not.toBeInTheDocument()
  expect(screen.queryByRole('link', { name: 'course' })).not.toBeInTheDocument()
})

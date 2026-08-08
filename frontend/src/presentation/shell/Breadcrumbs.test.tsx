import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { Course } from '@domain/project/course.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import type { Route } from '../routing/routes.ts'
import { researchHref, treeHref } from '../routing/routes.ts'
import { Breadcrumbs } from './Breadcrumbs.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

it('names the research route and links back to the tree', () => {
  const route: Route = { name: 'research', id: PROJECT }
  render(<Breadcrumbs route={route} session={null} course={null} />)

  expect(screen.getByText('research')).toBeInTheDocument()
  // Falls back to the id's short form because the research route does not
  // carry the course query CourseView does -- the same fallback the course
  // crumb uses when the name has not loaded yet.
  expect(screen.getByText(PROJECT.slice(0, 8))).toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'sessions' })).toHaveAttribute('href', treeHref())
})

it('prefers the loaded project name over the id on the research crumb', () => {
  const route: Route = { name: 'research', id: PROJECT }
  const course = { projectName: 'Spaced repetition' } as Course
  render(<Breadcrumbs route={route} session={null} course={course} />)

  expect(screen.getByText('Spaced repetition')).toBeInTheDocument()
})

it('research href round-trips to the route the breadcrumb was built for', () => {
  expect(researchHref(PROJECT)).toBe(`#/p/${PROJECT}/research`)
})

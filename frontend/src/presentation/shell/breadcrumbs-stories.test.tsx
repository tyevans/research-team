import { composeStories } from '@storybook/react-vite'
import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import * as stories from './Breadcrumbs.stories.tsx'

/** The trail's three shapes stay three shapes.
 *
 * `Breadcrumbs` branches on the route's `name` and returns from three
 * different places. A regression in one branch is invisible from the other
 * two, and the component has no state, so nothing else in the suite exercises
 * all three.
 *
 * The assertions are about *links*, not about text. A crumb that renders the
 * right word and is not a link is the defect worth catching -- it looks
 * correct in a screenshot and cannot be clicked.
 *
 * **Proved red** by making the project crumb a `<span>` unconditionally: the
 * facet test fails, and the no-facet test stays green, which is the pair
 * working as intended.
 */
const {
  Home,
  AProjectWithAName,
  AProjectWithAFacet,
  AProjectWithoutAName,
  AForkedSession,
  ASessionWithoutAProject,
} = composeStories(stories)

it('gives the landing page no link, because there is nowhere above it', () => {
  render(<Home />)
  expect(screen.queryAllByRole('link')).toHaveLength(0)
  expect(screen.getByText('projects')).toBeInTheDocument()
})

/** The pair. With nothing selected the project crumb has nowhere to go, so it
 *  is plain text; with a facet selected it becomes a link back to itself
 *  unselected. Each half alone passes on a build that links everything or
 *  nothing. */
it('does not link the project crumb when nothing is selected', () => {
  render(<AProjectWithAName />)
  expect(screen.queryByRole('link', { name: 'ancient-rome' })).not.toBeInTheDocument()
  expect(screen.getByText('ancient-rome')).toBeInTheDocument()
})

it('links the project crumb once a facet is selected', () => {
  render(<AProjectWithAFacet />)
  expect(screen.getByRole('link', { name: 'ancient-rome' })).toBeInTheDocument()
  // The facet, not the id: a crumb is for getting back, and the id is already
  // on the page that drew it.
  expect(screen.getByText('entity')).toBeInTheDocument()
  expect(screen.queryByText('e-42')).not.toBeInTheDocument()
})

/** A missing name falls back to the id rather than to nothing. A trail with a
 *  gap in it is worse than a trail with an id in it. */
it('falls back to a short id when the course has not loaded', () => {
  render(<AProjectWithoutAName />)
  expect(screen.getByText('11111111')).toBeInTheDocument()
})

/** The claim the component's docstring is about: a fork's origin is
 *  navigation, so it is a link in the trail rather than a fact in a panel. */
it('puts a fork’s origin in the trail, as a link, with its divergence point', () => {
  render(<AForkedSession />)
  expect(screen.getByRole('link', { name: /b2c93f17 @42/ })).toBeInTheDocument()
})

/** `SessionProjection.projectId` admits null where `SessionSummary` does not,
 *  so the project link has to be able to be absent and the trail still has to
 *  read as one. */
it('drops the project link for a session that belongs to none', () => {
  render(<ASessionWithoutAProject />)
  expect(screen.queryByRole('link', { name: 'course' })).not.toBeInTheDocument()
  expect(screen.getByRole('link', { name: 'projects' })).toBeInTheDocument()
})

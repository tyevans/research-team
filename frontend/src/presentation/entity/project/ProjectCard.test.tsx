import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { ProjectRollup } from '@domain/project/landing.ts'
import type { Project } from '@domain/project/project.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { ProjectCard, projectSessionsId } from './ProjectCard.tsx'

/** The `Card` density, and the props-only rule at its hardest case.
 *
 * `ProjectList.tsx` used to draw its own card and called `useProjectActivity`
 * inside it, so the card fetched once per drawn row — which is why the listing
 * costs two requests per row and why "a live project sorts first" was recorded
 * as not built. It renders this component now, and the assertions here are
 * mostly about what this component *cannot* do.
 *
 * Every test here but the last predates the wiring and none of them was
 * touched by it: they would all pass with `ProjectList` reverted, which is the
 * point — the card's contract is what the view had to fit itself to, not the
 * reverse. The last one is new and would *not* pass reverted; it is here
 * rather than in `TreeView.test.tsx` because the id is the card's half of a
 * contract with a slot, and a card handed no toggle at all still owes it.
 * The behaviour the landing page adds on top is asserted in
 * `TreeView.test.tsx`, where a container and a query client exist.
 */

const aProject = (over: Partial<Project> = {}): Project => ({
  id: ProjectId('11111111-1111-1111-1111-111111111111'),
  name: 'apollo',
  activeSessionId: null,
  tipAtEvent: 0,
  workflow: null,
  stage: null,
  ...over,
})

const aRollup = (over: Partial<ProjectRollup> = {}): ProjectRollup => ({
  project: aProject(),
  sessions: [],
  sessionCount: 3,
  fileCount: 12,
  lastActivity: '2026-01-01T10:00:00Z',
  ...over,
})

it('names the project through the shared reference', () => {
  render(<ProjectCard rollup={aRollup()} href="/project/1111" />)
  expect(screen.getByRole('link', { name: 'apollo' })).toHaveAttribute('href', '/project/1111')
})

it('says who holds it, by short id, without being told the holder’s name', () => {
  render(
    <ProjectCard
      rollup={aRollup({
        project: aProject({
          activeSessionId: SessionId('7d41e0aa-2222-3333-4444-555555555555'),
        }),
      })}
    />,
  )

  // The rule `EntityRef` makes real: name it if you already know the name,
  // never fetch in order to name it. A session has no name on the wire, so the
  // honest answer is the short id — and the card cannot go and look one up.
  expect(screen.getByText('held by')).toBeInTheDocument()
  expect(screen.getByText('7d41e0aa')).toBeInTheDocument()
})

it('says free when nothing holds it', () => {
  render(<ProjectCard rollup={aRollup()} />)
  expect(screen.getByText('free')).toBeInTheDocument()
  expect(screen.queryByText('held by')).toBeNull()
})

it('counts sessions and files, singular and plural', () => {
  const { rerender } = render(<ProjectCard rollup={aRollup()} />)
  expect(screen.getByText('3 sessions')).toBeInTheDocument()
  expect(screen.getByText('12 files')).toBeInTheDocument()

  rerender(<ProjectCard rollup={aRollup({ sessionCount: 1, fileCount: 1 })} />)
  expect(screen.getByText('1 session')).toBeInTheDocument()
  expect(screen.getByText('1 file')).toBeInTheDocument()
})

it('does not claim a last-active time', () => {
  render(<ProjectCard rollup={aRollup()} />)

  // `lastActivity` is the newest session *start*, not the last turn (L-§9.8),
  // so a card rendering it as "last active" would be making a claim the data
  // does not support. A view that wants to show it owns the wording.
  expect(screen.queryByText(/last active/i)).toBeNull()
})

it('renders no actions when it was given none, rather than empty chrome', () => {
  const { container } = render(<ProjectCard rollup={aRollup()} />)
  expect(container.querySelector('.ent-project-actions')).toBeNull()
})

it('renders the verbs the view supplies', () => {
  render(
    <ProjectCard rollup={aRollup()} slots={{ primary: <button type="button">Open</button> }} />,
  )

  // The card does not decide between "open" and "take over": the view owns
  // that branch because it owns what taking over means.
  expect(screen.getByRole('button', { name: 'Open' })).toBeInTheDocument()
})

it('keeps its disclosure closed until told otherwise, and owned externally', () => {
  const sessions = <p>the fork forest</p>
  const { rerender } = render(<ProjectCard rollup={aRollup()} slots={{ sessions }} />)

  // Closed by default: a card expanding its sessions inline meant "one
  // project's history pushed every other project off the screen".
  expect(screen.queryByText('the fork forest')).toBeNull()

  // Open state is a prop, never internal: DOM-owned state is lost on unmount,
  // and this list has to survive the refetch that arrives while it is open.
  rerender(<ProjectCard rollup={aRollup()} open slots={{ sessions }} />)
  expect(screen.getByText('the fork forest')).toBeVisible()
})

it('names the region it hides, so a supplied toggle has something to point at', () => {
  // `hidden` rather than absent, which is the only reason the toggle's
  // `aria-controls` says anything: the toggle is a slot, so the view writes
  // that attribute, and an IDREF resolving to nothing announces exactly as
  // much as no IDREF at all -- silently, while every other test passes. The
  // moment a reader needs to hear "this button opens a list of sessions" is
  // before they have opened it, which is precisely when the region would not
  // have existed.
  const { container } = render(
    <ProjectCard rollup={aRollup()} slots={{ sessions: <p>the fork forest</p> }} />,
  )

  const region = container.querySelector('.ent-project-sessions')!
  expect(region).toHaveAttribute('id', projectSessionsId(aProject().id))
  expect(region).not.toBeVisible()
  // Shut, so its contents are not mounted at all. This card is drawn once per
  // row in a virtualized list, and a whole session forest per collapsed
  // project is the cost that made expanding by default untenable.
  expect(region).toBeEmptyDOMElement()
})

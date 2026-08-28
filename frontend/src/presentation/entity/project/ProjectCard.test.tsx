import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import type { ProjectRollup } from '@domain/project/landing.ts'
import type { Project } from '@domain/project/project.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { ProjectCard } from './ProjectCard.tsx'

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

/** **This asserted `held by 7d41e0aa`, and now asserts its absence.**
 *
 * Written as the refusal rather than deleted. The card drew `held by 3f2a…`
 * for a held project and the word `free` for one that was not, and both are
 * gone: which session holds a project is a fact about where the next write
 * goes, and a reader of an index neither picks it nor acts on it.
 *
 * The holder is still *given* to this component — it is on the rollup's
 * project, which is why the fixture below still sets it — and it is still read
 * by `currentSession` to choose the previewed session and by `ProjectList` as
 * the delete call's `force` flag. This test is about the drawing only, and it
 * is paired with `TreeView.test.tsx`'s assertion on that `force` argument,
 * which is the half that would rot silently now that nothing on screen shows
 * the fact.
 */
it('does not name the session holding it', () => {
  render(
    <ProjectCard
      rollup={aRollup({
        project: aProject({
          activeSessionId: SessionId('7d41e0aa-2222-3333-4444-555555555555'),
        }),
      })}
    />,
  )

  expect(screen.queryByText('held by')).toBeNull()
  expect(screen.queryByText('7d41e0aa')).toBeNull()
})

it('does not label an unheld project either', () => {
  // The word `free` was the other half of the same vocabulary. Its job was to
  // tell a reader that the row's one button would work, and the row now offers
  // one verb that works in both states.
  render(<ProjectCard rollup={aRollup()} />)
  expect(screen.queryByText('free')).toBeNull()
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

it('points its toggle at the region it hides, while that region is hidden', () => {
  // The same claim as before, asserted through the attribute rather than
  // through an exported id helper: `projectSessionsId` was exported because
  // the *view* wrote `aria-controls` and had to compute the same string the
  // card computed. The card writes both ends now, so the assertion can be the
  // one that matters -- the IDREF resolves -- rather than the one that was
  // available -- two call sites agree on a string.
  //
  // `hidden` rather than absent is what makes this possible at all: an IDREF
  // to an element that does not exist announces exactly as much as no IDREF at
  // all, silently, at precisely the moment a reader needs to hear what the
  // button opens -- before they have opened it.
  //
  // **Proved red** by rendering the region only while `open`: `getElementById`
  // is handed a real id and answers null.
  render(
    <ProjectCard
      rollup={aRollup()}
      slots={{ toggle: 'all 3 sessions', sessions: <p>the fork forest</p> }}
    />,
  )

  const toggle = screen.getByRole('button', { name: /all 3 sessions/ })
  expect(toggle).toHaveAttribute('aria-expanded', 'false')
  const region = document.getElementById(toggle.getAttribute('aria-controls') ?? '')
  expect(region).not.toBeNull()
  expect(region).not.toBeVisible()
  // Shut, so its contents are not mounted at all. This card is drawn once per
  // row in a virtualized list, and a whole session forest per collapsed
  // project is the cost that made expanding by default untenable.
  expect(region).toBeEmptyDOMElement()
})

/** The toggle reports through the prop rather than deciding for itself.
 *
 *  `open` is owned externally -- a card's session list survives the refetch
 *  that arrives while it is open -- so the card must ask rather than decide.
 *  The second assertion is the one that would catch a card growing its own
 *  `useState`: it stays shut, because the prop did not move. */
it('asks to be opened rather than opening itself', async () => {
  const onOpenChange = vi.fn()
  const user = userEvent.setup()
  render(
    <ProjectCard
      rollup={aRollup()}
      onOpenChange={onOpenChange}
      slots={{ toggle: 'all 3 sessions', sessions: <p>the fork forest</p> }}
    />,
  )

  await user.click(screen.getByRole('button', { name: /all 3 sessions/ }))
  expect(onOpenChange).toHaveBeenCalledWith(true)
  // Still shut: the prop did not change, so neither did the card.
  expect(screen.queryByText('the fork forest')).toBeNull()
})

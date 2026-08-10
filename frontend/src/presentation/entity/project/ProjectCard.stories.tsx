import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ProjectRollup } from '@domain/project/landing.ts'
import type { Project } from '@domain/project/project.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { EntityStatus } from '../EntityStatus.tsx'
import { ProjectCard } from './ProjectCard.tsx'

/** The `Card` density, and the one component in this slice that could not be
 *  extracted — it had to be prised apart.
 *
 * `ProjectList.tsx` is 542 lines and its `ProjectRow` calls
 * `useProjectActivity` **inside the card**, so the listing costs two requests
 * per drawn row and "a live project sorts first" was recorded as not built
 * precisely because liveness cost a request per project. Everything that
 * fetched is a slot here, which is what makes these stories possible at all:
 * a card that fetched could not be rendered on a gallery page without a mock,
 * and a story about a mock is a story about the mock.
 *
 * The distinction from `Row` is a contract rather than a look: a row's height
 * is a function of its kind so a virtualizer can estimate it, and **a card
 * must be measured**. `Expanded` is the story that shows why they cannot be
 * the same component.
 */
const meta: Meta = {
  title: 'entity/ProjectCard',
}

export default meta

type Story = StoryObj

const project = (over: Partial<Project> = {}): Project => ({
  id: ProjectId('3f2a1b9c-1111-2222-3333-444444444444'),
  name: 'apollo',
  activeSessionId: null,
  tipAtEvent: 128,
  workflow: null,
  stage: null,
  ...over,
})

const rollup = (over: Partial<ProjectRollup> = {}): ProjectRollup => ({
  project: project(),
  sessions: [],
  sessionCount: 3,
  fileCount: 12,
  lastActivity: '2026-01-01T10:00:00Z',
  ...over,
})

const Frame = ({ children }: { children: React.ReactNode }) => (
  <div style={{ width: '420px', padding: 'var(--space-3)' }}>{children}</div>
)

/** A free project: one honest verb. */
export const Free: Story = {
  render: () => (
    <Frame>
      <ProjectCard
        rollup={rollup()}
        href="#project"
        slots={{ primary: <button type="button">Open</button> }}
      />
    </Frame>
  ),
}

/** A held project: two honest choices instead of one that fails. The card does
 *  not decide between them — the view does, because the view owns what taking
 *  over means. The holder is named by short id, because a session has no name
 *  and the card may not go and look for one. */
export const Held: Story = {
  render: () => (
    <Frame>
      <ProjectCard
        rollup={rollup({
          project: project({ activeSessionId: SessionId('7d41e0aa-1111-2222-3333-444444444444') }),
        })}
        href="#project"
        slots={{
          primary: <button type="button">Resume 7d41e0aa</button>,
          overflow: [
            <button key="take" type="button">
              New session
            </button>,
          ],
        }}
      />
    </Frame>
  ),
}

/** With what is running, supplied by the view. §2.7(c) proposes
 *  `/api/projects` rows carry `activity`, at which point this stops being a
 *  slot and becomes ordinary data — and the card stops being the reason the
 *  listing makes N requests. */
export const WithActivity: Story = {
  render: () => (
    <Frame>
      <ProjectCard
        rollup={rollup()}
        href="#project"
        slots={{
          activity: <EntityStatus status="running" detail="synthesising 2 topics" />,
          primary: <button type="button">Open</button>,
        }}
      />
    </Frame>
  ),
}

/** No verbs at all. The card renders no action chrome rather than an empty
 *  row of it. */
export const Bare: Story = {
  render: () => (
    <Frame>
      <ProjectCard rollup={rollup()} />
    </Frame>
  ),
}

/** Singulars. Worth a story because "1 sessions" is the kind of thing that
 *  ships and stays. */
export const OneOfEverything: Story = {
  render: () => (
    <Frame>
      <ProjectCard rollup={rollup({ sessionCount: 1, fileCount: 1 })} href="#project" />
    </Frame>
  ),
}

/** Expanded — and this is the story that shows why `Card` and `Row` are
 *  different components. The card's height is now a function of its contents,
 *  so a list of these has to measure every one. A card that expanded inline in
 *  a fixed-height list is what pushed "one project's history … off the
 *  screen". */
export const Expanded: Story = {
  render: () => (
    <Frame>
      <ProjectCard
        rollup={rollup()}
        href="#project"
        open
        slots={{
          toggle: <button type="button">▾</button>,
          primary: <button type="button">Open</button>,
          sessions: (
            <ul style={{ margin: 0, paddingLeft: 'var(--space-5)' }}>
              <li>7d41e0aa — 12 turns</li>
              <li>a1b2c3d4 — forked @ 34</li>
              <li>e5f6a7b8 — 3 turns</li>
            </ul>
          ),
        }}
      />
    </Frame>
  ),
}

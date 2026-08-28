import type { Meta, StoryObj } from '@storybook/react-vite'

import type { ProjectRollup } from '@domain/project/landing.ts'
import type { Project } from '@domain/project/project.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

/* `Button`, not a bare `<button>`, and the tones and sizes are copied from
   `ProjectList.tsx` -- `small` throughout, `accent` on the verb that starts
   work. A story exists to show what ships; a bare button in a slot shows
   something that does not. Since `tokens.css` gained its reset a bare button
   renders as unbordered text, so these stories were demonstrating
   primary-against-overflow with two pieces of prose. */
import { Button, Chip } from '../../common/primitives.tsx'
import { EntityStatus } from '../EntityStatus.tsx'
import { ProjectCard } from './ProjectCard.tsx'

/** The `Card` density, and the one component in this slice that could not be
 *  extracted — it had to be prised apart.
 *
 * `ProjectList.tsx` used to draw its own card and called `useProjectActivity`
 * **inside it**, so the listing costs two requests per drawn row and "a live
 * project sorts first" was recorded as not built
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

/** A free project: one verb. */
export const Free: Story = {
  render: () => (
    <Frame>
      <ProjectCard
        rollup={rollup()}
        href="#project"
        slots={{
          primary: (
            <Button small tone="accent">
              Continue
            </Button>
          ),
        }}
      />
    </Frame>
  ),
}

/** A held project, drawn **identically** — which is the whole story.
 *
 *  It used to draw `held by 7d41e0aa` in the head and offer `Resume 7d41e0aa`
 *  beside `New session`, so a reader had to resolve a lock before acting. The
 *  card no longer knows the difference is worth showing: the fixture below
 *  still sets `activeSessionId`, and the only place it now goes is
 *  `currentSession`'s choice of which session to preview and the delete call's
 *  `force` flag, neither of which is drawing.
 *
 *  Kept beside `Free` for exactly that reason — put the two stories side by
 *  side and a card that starts drawing the holder again is visible at a
 *  glance. A story that is the same as its neighbour is the point here, not an
 *  oversight. */
export const Held: Story = {
  render: () => (
    <Frame>
      <ProjectCard
        rollup={rollup({
          project: project({ activeSessionId: SessionId('7d41e0aa-1111-2222-3333-444444444444') }),
        })}
        href="#project"
        slots={{
          primary: (
            <Button small tone="accent">
              Continue
            </Button>
          ),
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
          primary: (
            <Button small tone="accent">
              Continue
            </Button>
          ),
        }}
      />
    </Frame>
  ),
}

/** Every slot filled, as the landing page fills them.
 *
 * Worth a story because this migration's whole risk is drift: `ProjectRow` and
 * this card were written independently as two drawings of one thing, and the
 * differences between them were only findable by rendering both. This is the
 * one that ships, so it is the one to look at when a change to `entity.css`
 * moves something. `badges`, `meta` and `preview` exist for exactly the three
 * things `ProjectRow` had and this card did not.
 *
 * `badges` is filled here with a plain chip rather than left null, which is
 * what the landing page passes today. The one real filler was the workflow
 * chip, deleted with the workflow system, and a slot demonstrated only by its
 * own absence is a slot nobody can see is still wired.
 */
export const AsTheLandingPageDrawsIt: Story = {
  render: () => (
    <Frame>
      <ProjectCard
        rollup={rollup({
          project: project({
            activeSessionId: SessionId('7d41e0aa-1111-2222-3333-444444444444'),
          }),
        })}
        href="#project"
        slots={{
          badges: <Chip>4 areas</Chip>,
          activity: <EntityStatus status="running" detail="synthesising 2 topics" />,
          // One span, and it used to be two. The second was the project's
          // short id under a tooltip carrying the full one -- a tab stop per
          // row, on a virtualized list, for an identifier that names a project
          // named in full six pixels above.
          meta: <span>2 days ago</span>,
          primary: (
            <Button small tone="accent">
              Continue
            </Button>
          ),
          // One `⋯`, and it used to be four buttons and a flex spacer:
          // `New session`, a gap, `Project` and `Ask`. `Project` is gone
          // because the card *is* that link now, `New session` went with the
          // take-over verb, and `Ask` moved into the menu.
          overflow: [
            <Button small key="more">
              ⋯
            </Button>,
          ],
          preview: <p style={{ margin: 0 }}>the current session sits here</p>,
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
          // A label rather than a control: the card owns the button, the caret
          // and the three ARIA attributes.
          toggle: 'sessions (3)',
          primary: (
            <Button small tone="accent">
              Continue
            </Button>
          ),
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

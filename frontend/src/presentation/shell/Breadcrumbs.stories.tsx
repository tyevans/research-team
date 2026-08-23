import type { Meta, StoryObj } from '@storybook/react-vite'

import type { SessionProjection } from '@domain/session/session.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { course, PROJECT } from '../course/course-fixtures.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { Breadcrumbs } from './Breadcrumbs.tsx'

/** The trail, which is the console's only answer to "where am I".
 *
 * It has three shapes, and they are genuinely different rather than variations
 * — a project route, a session route, and everything else. The stories are
 * arranged that way because a reader debugging a wrong crumb needs to know
 * which of the three branches they are in before anything else.
 *
 * Two claims the component argues in prose and had nowhere to show:
 *
 * - **A fork's origin is part of the trail, not a detail in a panel.** A
 *   forked session's most useful fact is what it came from and where it
 *   diverged, and that is a navigation question. `AForkedSession` is that.
 * - **A session names its project by id, deliberately.** A transcript knows
 *   which project it belongs to and not what that project is called, and
 *   fetching a name to label a link would make every session load wait on a
 *   request it otherwise does not need. So the session crumbs show `course`
 *   and a short id where the project route shows a name — and that asymmetry
 *   is a decision, not a gap. `AProjectWithAName` beside `ASession` is where
 *   it is visible.
 */
const meta: Meta = {
  title: 'shell/Breadcrumbs',
}

export default meta

type Story = StoryObj

const SESSION = SessionId('7d41e0aa-1111-4111-8111-444444444444')
const PARENT = SessionId('b2c93f17-1111-4111-8111-555555555555')

const projection = (over: Partial<SessionProjection> = {}): SessionProjection => ({
  id: SESSION,
  projectId: PROJECT,
  holdsProject: true,
  knowledgeAttached: true,
  modelName: 'claude-opus-5',
  systemPrompt: null,
  turnIndex: 2,
  failedTurns: 0,
  forkedFrom: null,
  forkedAt: null,
  eventCount: 260,
  compactedThrough: null,
  compactionSummary: null,
  at: null,
  files: [],
  messages: [],
  ...over,
})

const Frame = ({ heading, children }: { heading: string; children: React.ReactNode }) => (
  <section style={{ padding: 'var(--space-3)' }}>
    <h3 style={{ font: 'inherit', color: 'var(--fg-faint)', margin: '0 0 var(--space-2)' }}>
      {heading}
    </h3>
    {children}
  </section>
)

/** The landing page. One dead word, because there is nowhere above it. */
export const Home: Story = {
  render: () => (
    <Frame heading="home">
      <Breadcrumbs route={{ name: 'home' }} session={null} course={null} />
    </Frame>
  ),
}

/** A project with nothing selected. The project's own crumb is *not* a link
 *  here — there is nowhere for it to go that is not this page. */
export const AProjectWithAName: Story = {
  render: () => (
    <Frame heading="a project, nothing selected">
      <Breadcrumbs
        route={{ name: 'project', id: PROJECT, selection: null }}
        session={null}
        course={course({ projectName: 'ancient-rome' })}
      />
    </Frame>
  ),
}

/** A facet selected. **Now the project crumb becomes a link**, because there
 *  is somewhere for it to go — the same project with nothing selected, which
 *  is the step a reader wants after following a link into one topic.
 *
 *  The facet is shown, not the id: a crumb is for getting back, and the id is
 *  already on the page that drew it. */
export const AProjectWithAFacet: Story = {
  render: () => (
    <Frame heading="a facet selected — the project crumb is now a link">
      <Breadcrumbs
        route={{ name: 'project', id: PROJECT, selection: { facet: 'entity', id: 'e-42' } }}
        session={null}
        course={course({ projectName: 'ancient-rome' })}
      />
    </Frame>
  ),
}

/** A project whose name has not loaded. Falls back to the short id rather
 *  than drawing an empty crumb — a trail with a gap in it is worse than a
 *  trail with an id in it. */
export const AProjectWithoutAName: Story = {
  render: () => (
    <Frame heading="no course loaded yet">
      <Breadcrumbs
        route={{ name: 'project', id: PROJECT, selection: null }}
        session={null}
        course={null}
      />
    </Frame>
  ),
}

/** A transcript. Note what is *not* here: a project name.
 *
 *  Compare with `AProjectWithAName`. The asymmetry is argued in the component
 *  and is a decision about request cost, not an oversight. */
export const ASession: Story = {
  render: () => (
    <Frame heading="a session inside a project">
      <Breadcrumbs
        route={{ name: 'session', id: SESSION, at: ScrubPoint.head(), path: null }}
        session={projection()}
        course={null}
      />
    </Frame>
  ),
}

/** **The fork origin, in the trail.** Where it came from and at which event,
 *  as a link.
 *
 *  This is the story the component's docstring is about. A forked session's
 *  most useful fact is its parent and its divergence point, and putting that
 *  in a panel means a reader has to know to open one. */
export const AForkedSession: Story = {
  render: () => (
    <Frame heading="forked, with its origin">
      <Breadcrumbs
        route={{ name: 'session', id: SESSION, at: ScrubPoint.head(), path: null }}
        session={projection({ forkedFrom: PARENT, forkedAt: 42 })}
        course={null}
      />
    </Frame>
  ),
}

/** A session belonging to no project.
 *
 *  `SessionProjection.projectId` admits `null` where `SessionSummary` does
 *  not, because it folds a state that exists before `SessionStarted` does. So
 *  the project link has to be able to be absent, and the trail still has to
 *  read as a trail. */
export const ASessionWithoutAProject: Story = {
  render: () => (
    <Frame heading="no project">
      <Breadcrumbs
        route={{ name: 'session', id: SESSION, at: ScrubPoint.head(), path: null }}
        session={projection({ projectId: null })}
        course={null}
      />
    </Frame>
  ),
}

/** All three shapes together, which is the only way the asymmetry between
 *  them is visible. */
export const EveryShape: Story = {
  render: () => (
    <>
      <Frame heading="home">
        <Breadcrumbs route={{ name: 'home' }} session={null} course={null} />
      </Frame>
      <Frame heading="project">
        <Breadcrumbs
          route={{ name: 'project', id: ProjectId(PROJECT), selection: { facet: 'doc', id: null } }}
          session={null}
          course={course({ projectName: 'ancient-rome' })}
        />
      </Frame>
      <Frame heading="session">
        <Breadcrumbs
          route={{ name: 'session', id: SESSION, at: ScrubPoint.head(), path: null }}
          session={projection({ forkedFrom: PARENT, forkedAt: 42 })}
          course={null}
        />
      </Frame>
    </>
  ),
}

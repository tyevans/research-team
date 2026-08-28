import { useState } from 'react'

import type { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { Drawer } from '../common/Drawer.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { useProject } from '../project/use-project.ts'
import type { Route } from '../routing/routes.ts'
import { AutonomyPanel } from './AutonomyPanel.tsx'

const HEADING = 'What the agent may do without asking'

/** The way in to the autonomy policy, from every route.
 *
 * A lock in the chrome rather than a band in the project page's queue header,
 * and the argument is `Shell.tsx`'s own test for what belongs in that bar: the
 * policy is not a property of the page you happen to be on. One object serves
 * every session in the process, so a panel that could only be reached from one
 * project's page was a global setting filed under a local screen -- and filed
 * where a reader scrolling to the queue met it on the way, which is the
 * opposite of what a rarely-touched setting earns.
 *
 * It is a dialog rather than a fold for the same reason it is in the chrome:
 * twenty-four controls that a person opens on purpose, a few times, and closes.
 * `Drawer` brings the keyboard contract with it -- focus in on open and back on
 * close, Escape closes, Tab cannot walk out into the page behind -- which is
 * the whole reason this does not hand-roll a modal.
 *
 * **The tooltip is not the only place the name is said.** It carries the same
 * sentence as the dialog's heading, and the button also has that sentence as
 * its accessible name: a tooltip is a hover affordance, and a lock glyph with
 * nothing else is exactly the unlabelled-icon defect the console records
 * elsewhere (S-D2). A screen reader and a keyboard both get the sentence
 * without the tooltip ever opening.
 */
export const AutonomyLock = ({ route }: { route: Route }) =>
  // Two components rather than one with a conditional hook, which React does
  // not allow: only the project route can resolve a holding session, and that
  // resolution is a query.
  route.name === 'project' ? (
    <LockForProject projectId={route.id} />
  ) : (
    <Lock sessionId={route.name === 'session' ? route.id : null} />
  )

/** The project page's holder is where a write from this lock is recorded.
 *
 * `useProject` is already mounted by `ProjectView` on this route, so this is a
 * second reader of one query rather than a second request. Off the project
 * route there is no holder to find and the panel renders read-only, saying so
 * -- see `NO_SESSION`, which is the honest answer rather than a disabled lock.
 */
const LockForProject = ({ projectId }: { projectId: ProjectId }) => {
  const { holdingSessionId } = useProject(projectId)
  return <Lock sessionId={holdingSessionId} />
}

const Lock = ({ sessionId }: { sessionId: SessionId | null }) => {
  const [open, setOpen] = useState(false)

  return (
    <>
      <Tooltip asChild explanation={HEADING}>
        <button
          type="button"
          className="btn btn-ghost btn-sm"
          aria-label={HEADING}
          aria-expanded={open}
          onClick={() => setOpen(true)}
        >
          <LockGlyph />
        </button>
      </Tooltip>

      {open ? (
        <Drawer heading={HEADING} label={HEADING} onClose={() => setOpen(false)}>
          <AutonomyPanel sessionId={sessionId} />
        </Drawer>
      ) : null}
    </>
  )
}

/** Drawn rather than written, because the console has no icon set and a glyph
 *  from one would be the only one. `currentColor` so it inherits `.btn`'s
 *  hover and disabled colours instead of declaring its own, and `aria-hidden`
 *  because the button already carries the sentence. */
const LockGlyph = () => (
  <svg
    width="12"
    height="12"
    viewBox="0 0 12 12"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.2"
    aria-hidden="true"
  >
    <rect x="2" y="5.5" width="8" height="5.5" rx="1" />
    <path d="M4 5.5V3.75a2 2 0 0 1 4 0V5.5" />
  </svg>
)

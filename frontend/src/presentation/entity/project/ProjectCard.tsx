import clsx from 'clsx'
import type { ReactNode } from 'react'

import type { ProjectRollup } from '@domain/project/landing.ts'
import { projectHeadOf, sessionHeadOf } from '@domain/entity/heads.ts'
import { isHeld } from '@domain/project/project.ts'

import { EntityRef } from '../EntityRef.tsx'

/** The `Card` density: a variable-height member of a list, carrying its own
 *  actions and possibly a disclosure.
 *
 * **The distinction from `Row` is a contract, not decoration.** A row's height
 * is a function of its kind, so a virtualizer can estimate it; a card **must
 * be measured**. `docs/design/landing-page.md` §8 records "rows are
 * fixed-height, which is what makes this cheap" ceasing to be true "the moment
 * a row carried a disclosure", and records the supersession that followed — a
 * card expanding its sessions inline meant "one project's history pushed every
 * other project off the screen". Naming the two densities separately names a
 * contract a virtualizer can rely on and one it cannot, which is the whole
 * reason they are separate components rather than a `density` prop.
 *
 * **This is the density that proves the props-only rule.** `ProjectList.tsx`
 * is 542 lines, and its `ProjectRow` calls `useProjectActivity` inside the
 * card — so the card fetches, once per drawn row, which is why L-R1 prices the
 * current listing at two requests per row and why L-F7's "a live project sorts
 * first" was recorded as not built. Everything that fetched is a slot or a
 * prop here. The card cannot fetch because it has nothing to fetch with.
 *
 * The virtualizer facts L-F8 records — `getItemKey` by id, `scrollMargin`
 * re-measured with no dependency array, every row measured — deliberately do
 * **not** move into this component. They are properties of the *list*, and a
 * card that owned them could not be put in a list that was not virtualized.
 */
export const ProjectCard = ({
  rollup,
  href,
  open = false,
  selected = false,
  slots = {},
}: {
  rollup: ProjectRollup
  href?: string | undefined
  /** Whether the disclosure is expanded. Owned externally, never by this
   *  component: state that lives in the DOM is lost on unmount, and a card's
   *  sessions list survives the refetch that arrives while it is open. */
  open?: boolean
  selected?: boolean
  slots?: Partial<{
    /** What is running, when the caller knows. A slot rather than a prop with
     *  a hook behind it: §2.7(c) proposes `/api/projects` rows carry
     *  `activity`, at which point this becomes ordinary data — and until then
     *  the fetch stays in the view where it can be batched, rather than one
     *  request per card. */
    activity: ReactNode
    /** The verb this card leads with. The view owns it because it owns the
     *  branch: a held project offers two honest choices — open the holder, or
     *  end it and take over — where a free one offers "open". A card deciding
     *  that itself would have to know what taking over means. */
    primary: ReactNode
    overflow: readonly ReactNode[]
    /** The disclosure's contents, rendered only when `open`. */
    sessions: ReactNode
    /** The control that toggles the disclosure. Supplied rather than rendered
     *  here so the card does not have to own a second interaction contract;
     *  phase 2's `Disclosure` is what this becomes. */
    toggle: ReactNode
  }>
}) => {
  const { project, sessionCount, fileCount } = rollup

  return (
    <div className={clsx('ent-project-card', selected && 'is-selected')} data-project={project.id}>
      <div className="ent-project-head">
        {slots.toggle}
        <EntityRef head={projectHeadOf(project)} href={href} className="ent-project-name" />

        {/* The holder decides what the card can offer, so it is on the card
            rather than looked up when a button is pressed. `EntityRef` is what
            makes `held by 3f2a…` one component instead of the seven spellings
            this fact currently has. */}
        {isHeld(project) ? (
          <EntityRef
            head={sessionHeadOf(project.activeSessionId!)}
            prefix="held by"
            className="ent-project-holder"
          />
        ) : (
          <span className="ent-project-free">free</span>
        )}

        {slots.activity}
      </div>

      <div className="ent-project-stats">
        {/* Counted things, each saying what it counts. `fileCount` is the sum
            of per-session live-file counts rather than distinct paths --
            sessions share a filesystem -- which the domain type says in a
            comment and which this card must not overstate. */}
        <span>
          {sessionCount} {sessionCount === 1 ? 'session' : 'sessions'}
        </span>
        <span>
          {fileCount} {fileCount === 1 ? 'file' : 'files'}
        </span>
        {/* `lastActivity` is deliberately absent from this component. It is the
            newest session *start*, not the last turn, so rendering it as "last
            active" would be a claim the data does not support (L-§9.8). A view
            that wants to show it can, with wording it owns. */}
      </div>

      {(slots.primary ?? slots.overflow) === undefined ? null : (
        <div className="ent-project-actions">
          {slots.primary}
          {slots.overflow}
        </div>
      )}

      {open ? <div className="ent-project-sessions">{slots.sessions}</div> : null}
    </div>
  )
}

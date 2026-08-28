import clsx from 'clsx'
import type { ReactNode } from 'react'

import type { ProjectRollup } from '@domain/project/landing.ts'
import { projectHeadOf, sessionHeadOf } from '@domain/entity/heads.ts'
import { isHeld } from '@domain/project/project.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { EntityRef } from '../EntityRef.tsx'

/** The id of the region a card's `toggle` opens, derived rather than generated.
 *
 * `useId()` is the reflex here and cannot work: the toggle is a *slot*, built
 * by the view, so the card has no way to hand a generated id to the element
 * that has to point at it without becoming a render-prop. Deriving it from the
 * project id means both sides compute the same string from the same fact, and
 * a project appears once in a list — so the ids are unique on the page for the
 * same reason the React keys are.
 *
 * Exported because a view that supplies `toggle` **must** use it. A toggle
 * with no `aria-controls` announces no relationship to the region it opens,
 * and nothing on screen says one is missing: it is the class of loss that
 * ships green.
 */
export const projectSessionsId = (id: ProjectId): string => `project-sessions-${id}`

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
 * used to draw its own card, and that card called `useProjectActivity` inside
 * itself — so it fetched, once per drawn row, which is why L-R1 priced the
 * listing at two requests per row and why L-F7's "a live project sorts first"
 * was recorded as not built. Everything that fetched is a slot or a prop here.
 * The card cannot fetch because it has nothing to fetch with. `ProjectList`
 * now renders this component, so that is the landing page's only drawing of a
 * project and there is no second one to drift from it.
 *
 * Note what did *not* change by moving: the listing still makes the same two
 * requests per drawn row, because the hook simply moved up into `ProjectRows`.
 * What changed is that the requests are now visible at the level that could
 * batch them — §2.7(c)'s `activity` on `/api/projects` is a one-line change
 * here and was previously a component rewrite.
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
    /** Whatever else this card's view wants said about the project itself,
     *  between its name and who holds it. Every caller passes `null` today: the
     *  one filler was the landing page's workflow chip, deleted with the
     *  workflow system. Kept rather than removed with it, because the argument
     *  for a slot never depended on that chip -- which facts about a project
     *  are worth a badge is an editorial decision belonging to the page that
     *  writes the words, and a card that rendered them would be deciding for
     *  every future list. The cost is a slot with nothing in it, and it is
     *  visible in `ProjectCard.stories.tsx`'s slots story rather than only
     *  here. */
    badges: ReactNode
    /** The verb this card leads with. The view owns it because it owns the
     *  branch: a held project offers two honest choices — open the holder, or
     *  end it and take over — where a free one offers "open". A card deciding
     *  that itself would have to know what taking over means. */
    primary: ReactNode
    overflow: readonly ReactNode[]
    /** Extra counted or identifying things, appended to the stats line. This
     *  is where `lastActivity` goes: the comment below says a card must not
     *  render it as "last active", and a slot is how a view that has honest
     *  wording for it gets to use that wording without this component
     *  acquiring an opinion. */
    meta: ReactNode
    /** What stands in for the sessions while the disclosure is shut. The
     *  landing page shows the one session a returning reader is looking for
     *  rather than none; a card with nothing to preview passes nothing and
     *  the summary is simply absent. Separate from `sessions` because the two
     *  are never both right: this is the summary *of* that list. */
    preview: ReactNode
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

        {slots.badges}

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
            that wants to show it can, with wording it owns — through
            `slots.meta`, which is where the landing page's relative time and
            short id go. */}
        {slots.meta}
      </div>

      {(slots.primary ?? slots.overflow) === undefined ? null : (
        <div className="ent-project-actions">
          {slots.primary}
          {slots.overflow}
        </div>
      )}

      {/* The summary gives way to the list rather than sitting above it: the
          previewed session is *in* that list, and showing it twice reads as a
          duplicated row rather than as a summary of what is below.

          **The region is in the document while it is shut**, `hidden` rather
          than absent, and that is the whole reason `aria-controls` on the
          toggle means anything: an IDREF to an element that does not exist yet
          is an IDREF to nothing, and the moment a reader most needs to be told
          "this button opens a list of sessions" is *before* they have opened
          it. `Disclosure` has always had this shape; the card had to grow it.

          Its *contents* are still mounted only when open, which is the other
          half of `Disclosure`'s shape and matters more here than there: this
          card is drawn once per row in a virtualized list, and a whole
          `SessionForest` per collapsed project is the cost that made expanding
          by default untenable in the first place. */}
      {slots.sessions === undefined ? null : (
        <div className="ent-project-sessions" id={projectSessionsId(project.id)} hidden={!open}>
          {open ? slots.sessions : null}
        </div>
      )}
      {open ? null : slots.preview}
    </div>
  )
}

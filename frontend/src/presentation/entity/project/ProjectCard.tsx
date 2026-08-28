import clsx from 'clsx'
import type { ReactNode } from 'react'

import type { ProjectRollup } from '@domain/project/landing.ts'
import { projectHeadOf } from '@domain/entity/heads.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../../common/primitives.tsx'
import { EntityRef } from '../EntityRef.tsx'

/** The id of the region the card's toggle opens, derived rather than generated.
 *
 * `useId()` is the reflex and cannot be used: the id has to be computable by
 * `ProjectCard.test.tsx` in order to be asserted at all, and deriving it from
 * the project id means the button and the region compute the same string from
 * the same fact. A project appears once in a list, so the ids are unique on the
 * page for the same reason the React keys are.
 *
 * **No longer exported, and that is the change.** It was, because a *view*
 * supplied the toggle and therefore had to write `aria-controls` itself. The
 * card owns the button now, so both ends of the IDREF are three lines apart in
 * one file and there is nothing for a second spelling to drift from.
 */
const sessionsRegionId = (id: ProjectId): string => `project-sessions-${id}`

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
 * **This is the density that proves the props-only rule.** Everything that
 * fetches is a slot or a prop here. The card cannot fetch because it has
 * nothing to fetch with. `ProjectList` renders this component, so that is the
 * landing page's only drawing of a project and there is no second one to drift
 * from it.
 *
 * **The whole card opens the project, and that is one link rather than a
 * click handler on a div.** `href` was optional and the landing page never
 * passed it, so the largest, most obvious target on every row — the project's
 * name — was an inert `<span>`, and the way to a project page was a small
 * secondary button four controls along. The name is the anchor and its
 * `::after` is stretched over the card (`entity.css`), so the padding and the
 * stat line are part of the same target. Everything genuinely interactive
 * inside the card is raised above that overlay by the same stylesheet, which
 * is a stacking fact and therefore a browser measurement:
 * `ProjectCard.browser.test.tsx` holds it. jsdom would report the overlay and
 * a missing overlay identically.
 *
 * The cost is real and is not hidden: text under the overlay (the stat line)
 * cannot be selected with a drag, because the drag lands on a link. That is
 * the accepted half of the stretched-link trade, and it is why the overlay
 * covers *metadata* rather than the session preview, whose first message is
 * the one string on a card somebody might want to copy.
 *
 * **The holder is not drawn here any more.** `held by 3f2a…` / `free` stood in
 * the head and is gone: which session holds a project is a fact about where
 * the next write goes, not something a reader of an index picks or needs. The
 * fact itself is *not* gone — `rollup.project.activeSessionId` is still what
 * `currentSession` reads to choose the previewed session, and still what the
 * view passes as the delete call's `force` flag. Removing the drawing without
 * removing the data is deliberate: this repository has shipped "background
 * concern" as "silently absent" before, so the load-bearing use is pinned by
 * an assertion (`TreeView.test.tsx`, the delete-forces-a-held-project case)
 * rather than by this paragraph.
 */
export const ProjectCard = ({
  rollup,
  href,
  open = false,
  onOpenChange,
  selected = false,
  slots = {},
}: {
  rollup: ProjectRollup
  href?: string | undefined
  /** Whether the disclosure is expanded. Owned externally, never by this
   *  component: state that lives in the DOM is lost on unmount, and a card's
   *  sessions list survives the refetch that arrives while it is open. */
  open?: boolean
  /** Toggling, which used to be the *view's* job and its bug to have.
   *
   * Before this, `toggle` was a slot the view filled with a button carrying
   * its own `onClick`, `aria-expanded` and `aria-controls` — three attributes
   * reproduced by hand at the call site, pointing at an id the view derived
   * through an exported helper so that the two spellings could not drift. The
   * card's own comment called that out: an IDREF that resolves to nothing
   * announces exactly as much as no IDREF at all, silently. The card writes
   * all three now and the slot is only a label.
   *
   * **`@radix-ui/react-collapsible` was tried for this and backed out**, which
   * is worth the paragraph because it is the obvious move and it is wrong
   * here. Radix omits `aria-controls` from the trigger while the collapsible
   * is *closed* (`aria-controls: context.open ? contentId : undefined`) — the
   * exact moment this card argues the relationship most needs announcing — and
   * its `forceMount` escape hatch, which is how you keep the region in the
   * document, also sets `isOpen = context.open || isPresent`, so the closed
   * region never receives `hidden` and draws as an empty box in every row of a
   * virtualized list. Measured in jsdom on 2026-08-27, not reasoned: the
   * rendered trigger carried `aria-expanded="false"` and no `aria-controls`,
   * and the region carried neither `hidden` nor content. Keeping both
   * properties would have meant writing the two attributes back on top of the
   * library, which is worse than either alone. Twelve lines below are what the
   * dependency would have replaced. */
  onOpenChange?: (open: boolean) => void
  selected?: boolean
  slots?: Partial<{
    /** What is running, when the caller knows. A slot rather than a prop with
     *  a hook behind it: the fetch stays in the view where it can be batched,
     *  rather than one request per card. */
    activity: ReactNode
    /** Whatever else this card's view wants said about the project itself,
     *  between its name and what is running. Every caller passes `null` today;
     *  which facts about a project are worth a badge is an editorial decision
     *  belonging to the page that writes the words, and a card that rendered
     *  them would be deciding for every future list. Visible in
     *  `ProjectCard.stories.tsx`'s slots story rather than only here. */
    badges: ReactNode
    /** The verb this card leads with. The view owns it because it owns what
     *  the verb *does*: the landing page's single `Continue` resolves to a
     *  navigation or to a write depending on state the card cannot see. */
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
    /** The *label* on the control that toggles the disclosure — no longer the
     *  control itself. See `onOpenChange`. */
    toggle: ReactNode
  }>
}) => {
  const { project, sessionCount, fileCount } = rollup

  return (
    <div className={clsx('ent-project-card', selected && 'is-selected')} data-project={project.id}>
      {/* **The name is first in the head, and that is a stacking requirement
          rather than a layout preference.** The stretched link is the name's
          `::after`, and everything that has to stay clickable through it is
          raised by `position: relative` *alone* — no `z-index`, because a
          positioned element with `z-index: auto` paints above an earlier
          positioned one in document order, and because `stacking.test.ts`
          forbids a literal `z-index` outside the roles `tokens.css` declares.
          So "after the anchor in the DOM" is what does the raising, and the
          disclosure — which was the one head item drawn before the name — moved
          to the end of the line to get it.

          The move is an improvement on its own terms and would not be reverted
          if the constraint went: the name is what a list is scanned for and it
          now starts the row, where a caret and a session count used to. But the
          reason it is *safe* is the ordering, so nothing here may be reordered
          without re-running `ProjectCard.browser.test.tsx`. */}
      <div className="ent-project-head">
        <EntityRef head={projectHeadOf(project)} href={href} className="ent-project-name" />

        {slots.badges}
        {slots.activity}

        {slots.toggle === undefined || slots.toggle === null ? null : (
          /* Both ARIA attributes on the *same* element, deliberately: split
             across two the DOM reads correct and a screen reader announces a
             button that expands nothing. */
          <Button
            small
            tone="quiet"
            className="ent-project-toggle"
            aria-expanded={open}
            aria-controls={sessionsRegionId(project.id)}
            onClick={() => onOpenChange?.(!open)}
          >
            <span className="disc-caret" aria-hidden="true">
              {open ? '▾' : '▸'}
            </span>
            {slots.toggle}
          </Button>
        )}
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
            `slots.meta`. */}
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
          than absent, and that is the whole reason the toggle's
          `aria-controls` means anything: an IDREF to an element that does not
          exist yet is an IDREF to nothing, and the moment a reader most needs
          to be told "this button opens a list of sessions" is *before* they
          have opened it.

          Its *contents* are still mounted only when open, which matters more
          here than it looks: this card is drawn once per row in a virtualized
          list, and a whole `SessionForest` per collapsed project is the cost
          that made expanding by default untenable in the first place. */}
      {slots.sessions === undefined ? null : (
        <div className="ent-project-sessions" id={sessionsRegionId(project.id)} hidden={!open}>
          {open ? slots.sessions : null}
        </div>
      )}
      {open || slots.preview === undefined ? null : (
        <div className="ent-project-preview">{slots.preview}</div>
      )}
    </div>
  )
}

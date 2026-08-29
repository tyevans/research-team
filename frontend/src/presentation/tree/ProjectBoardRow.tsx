import { useState } from 'react'

import type { Scale } from '@domain/project/board.ts'
import type { ProjectListing } from '@domain/project/project.ts'

import { Menu, MenuItem, MenuTrigger } from '../common/Menu.tsx'
import { Button } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
import { relativeTime } from '../formatting/format.ts'
import { projectHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { ActivityChip } from './ProjectActivity.tsx'
import { ProjectPipeline } from './ProjectPipeline.tsx'

/** One project on the board.
 *
 * **The whole row is the link, and the name carries it.** The stretched-link
 * pattern the old `ProjectCard` established is kept — the anchor's `::after`
 * covers the row, so the padding and the pipeline are part of the same target,
 * and ⌘-click works. What changed is what sits under the overlay: it used to
 * cover a stat line and a session preview, and it now covers the pipeline,
 * which is a set of bars nobody wants to select. That is a straight
 * improvement on the accepted half of the trade, which was that text under the
 * overlay cannot be dragged.
 *
 * **The disclosure is gone.** Every row could expand a fork forest, and the
 * card's own comment recorded why that was already uncomfortable: sessions
 * accumulate far faster than projects, so one project's history pushed every
 * other project off the screen, and the expanded height defeated the
 * virtualizer's estimate. The sessions are still reachable — they are what the
 * project page opens with — and an index is not where a fork tree belongs.
 * Dropping it makes every row exactly one height, which is what lets
 * `ProjectBoard` estimate instead of measure.
 *
 * `ProjectCard` and its story and tests are **deleted** rather than left
 * unused. It was built around a session preview and a disclosure, neither of
 * which this page has, and its own docstring claimed to be "the landing page's
 * only drawing of a project" — a component with no caller and a false
 * docstring is the `.view-head` hazard `tree.css` records at length, one layer
 * up.
 */
export const ProjectBoardRow = ({
  listing,
  scale,
  activity,
  onDelete,
  onContinue,
  busy,
}: {
  listing: ProjectListing
  scale: Scale
  /** What is running here, or null. Passed rather than fetched: one query
   *  serves the whole board, and a hook per row would be N subscribers this
   *  component would have to justify. `ProjectBoard` owns the read, which is
   *  what makes this component props-only and testable with no query client. */
  activity: string | null
  onDelete: () => void
  onContinue: () => void
  busy: boolean
}) => {
  const { summary } = listing

  return (
    // `isolate` creates a stacking context so the stretched link's overlay
    // cannot escape this row and cover the one below it — the overlay is
    // positioned against the nearest positioned ancestor, and this row is the
    // only candidate.
    //
    // `group` is what lets the name respond to a hover anywhere on the row;
    // without it the name would only highlight when the pointer was on the
    // eight characters of text rather than on the target the reader is
    // actually over.
    <article
      className="group relative isolate rounded-md border border-line bg-bg-panel px-4 py-3 hover:border-line-strong hover:bg-bg-hover"
      data-project={listing.id}
      data-board-row
    >
      <div className="mb-3 flex items-center gap-3">
        {/* First in the head, and that is a stacking requirement rather than a
            preference — the same one the old card documented. The stretched
            link is this anchor's `::after`, and everything that must stay
            clickable through it is raised back above the overlay by
            `relative` alone: no `z-index`, because a positioned element with
            `z-index: auto` paints above an earlier positioned sibling in
            document order, and `stacking.test.ts` forbids a literal `z-index`
            outside the roles `tokens.css` declares. "After the anchor in the
            DOM" is what does the raising, so nothing in this head may be
            reordered without re-running `project-board.browser.test.tsx`. */}
        <a
          className="min-w-0 truncate text-lg font-semibold text-fg no-underline group-hover:text-accent after:absolute after:inset-0 after:rounded-md after:content-['']"
          href={projectHref(listing.id)}
        >
          {listing.name}
        </a>
        <ActivityChip label={activity} />
        {/* `ml-auto` on the first thing that belongs at the trailing edge. The
            time and the actions are a group on the right; the name and the
            activity chip are a group on the left. */}
        <div className="ml-auto font-mono text-xs whitespace-nowrap text-fg-faint" data-board-when>
          {summary.lastActivity ? relativeTime(summary.lastActivity) : 'never opened'}
        </div>
        <div className="relative flex items-center gap-2">
          <Tooltip
            asChild
            explanation="Pick up this project's conversation, starting one if none is open"
          >
            <Button small tone="accent" disabled={busy} onClick={onContinue}>
              Continue
            </Button>
          </Tooltip>
          <RowMenu listing={listing} onDelete={onDelete} busy={busy} />
        </div>
      </div>
      <ProjectPipeline summary={summary} scale={scale} />
    </article>
  )
}

/** The per-project overflow, and the obvious place for a settings entry.
 *
 * Split into its own component only because it owns the one piece of state a
 * row has; the row itself is otherwise a pure function of its props.
 *
 * This is where W-C1's project settings belongs when it lands — it is the one
 * control on the row that already means "things you can do to this project"
 * rather than "read this project". Left with the two verbs it has today rather
 * than stubbed with a disabled item: a control that does nothing is worse than
 * one that is not there yet.
 *
 * `Ask` is here because `App.tsx` intercepts the `ask` facet above
 * `ProjectView`, so it cannot be reached by opening the project and clicking a
 * tab the way the graph and the documents can. An entrance here is the
 * difference between a page a reader can find and one only a typed URL
 * reaches — the one thing kept verbatim from the row this replaces, because
 * the whole history of that row was destinations quietly losing their
 * entrances.
 */
const RowMenu = ({
  listing,
  onDelete,
  busy,
}: {
  listing: ProjectListing
  onDelete: () => void
  busy: boolean
}) => {
  const [open, setOpen] = useState(false)
  return (
    <Menu
      label={`More actions for ${listing.name}`}
      open={open}
      onOpenChange={setOpen}
      trigger={<MenuTrigger aria-label={`More actions for ${listing.name}`} />}
    >
      <MenuItem onSelect={() => navigate(projectHref(listing.id, { facet: 'ask', id: null }))}>
        Ask
      </MenuItem>
      <MenuItem tone="danger" disabled={busy} onSelect={onDelete}>
        Delete
      </MenuItem>
    </Menu>
  )
}

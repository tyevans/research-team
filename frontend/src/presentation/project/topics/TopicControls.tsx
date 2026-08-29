import { useState } from 'react'

import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { Glyph } from '../../common/Glyph.tsx'
import { Tooltip } from '../../common/Tooltip.tsx'
import { projectHref } from '../../routing/routes.ts'
import { TopicsDrawer, TOPICS_HEADING } from './TopicsDrawer.tsx'

const ASK = 'Ask this project'
const DIALOGUE = 'Be asked about this project'

/** Everything a project's topics are reached by, as three glyphs in the
 *  console's chrome.
 *
 * **It was a rail, and the rail is gone.** QUEUE was a quarter-width sidebar
 * on every project page, holding a search box, four filter tabs and the topic
 * rows -- and it was there whether or not the reader had come to look at
 * topics at all. `docs/design/topic-actions-on-the-row.md` §1 measures what
 * the *header* above that list cost; what this change measures is the list
 * itself, which took a quarter of every project page permanently in exchange
 * for being useful on the visits that were about a question. The rows, the
 * filter and the search box are in the drawer now, behind the same door as
 * seeding; MATERIAL takes the whole surface.
 *
 * **In the chrome rather than on the page, and that is what makes the rail
 * removable.** These three are properties of the project rather than of the
 * tab you happen to have open, which is the test `Shell.tsx` states for this
 * slot -- and it is the test the two ask links have needed all along. This
 * pane has lost an inbound link to `#/p/<id>/ask` twice and to `#/p/<id>/
 * dialogue` once, both times because the one component drawing them stopped
 * being rendered. In the chrome they are drawn on every project route,
 * including the two (`ask`, `dialogue`) that `App.tsx` intercepts above
 * `ProjectView` entirely -- so a reader can leave a dialogue by the same
 * control they entered it with, which was not true before.
 *
 * **Every control carries its sentence twice.** A `Tooltip` for the mouse and
 * an `aria-label` with the same words, so a keyboard and a screen reader both
 * get it without the tooltip ever opening. An icon with only a tooltip is
 * S-D2, the unlabelled-icon defect this console already records, and
 * `AutonomyLock` -- which sits two controls to the right -- is the worked
 * example this follows.
 */
export const TopicControls = ({
  projectId,
  openTopic,
  onOpenTopic,
}: {
  projectId: ProjectId
  /** Which topic the route has open, or `null`. **It also forces the drawer
   *  open**, which is the whole reason it is threaded up here rather than left
   *  inside the drawer: `#/p/<id>/topic/<tid>` is a link a person sends, and
   *  the topic it names now lives behind a door. A route that opened nothing
   *  visible would be the linkable-URL-that-renders-the-default-page defect
   *  `use-topic-queue.ts` records against the old `useState`, arriving a second
   *  time through a drawer instead of through state. */
  openTopic: TopicId | null
  onOpenTopic: (topicId: TopicId | null) => void
}) => {
  const [open, setOpen] = useState(false)

  // Either reason opens it. Closing has to answer both: `setOpen(false)` alone
  // would leave a `topic` selection in the address bar re-opening the drawer on
  // the next render, so the close clears the selection too.
  const showing = open || openTopic !== null

  return (
    <>
      <TopicControlBar
        askHref={projectHref(projectId, { facet: 'ask', id: null })}
        dialogueHref={projectHref(projectId, { facet: 'dialogue', id: null })}
        topicsOpen={showing}
        onOpenTopics={() => setOpen(true)}
      />
      {showing ? (
        <TopicsDrawer
          projectId={projectId}
          openTopic={openTopic}
          onOpenTopic={onOpenTopic}
          onClose={() => {
            setOpen(false)
            onOpenTopic(null)
          }}
        />
      ) : null}
    </>
  )
}

/** The three controls, from props, so the arrangement has a story.
 *
 * Split from `TopicControls` for the reason `TopicQueue` is split from
 * `TopicList`: a component that owns drawer state cannot be put in a workbench
 * without a container and an overlay host behind it. This one can, so the
 * arrangement of three glyphs is something a story can show.
 */
export const TopicControlBar = ({
  askHref,
  dialogueHref,
  topicsOpen,
  onOpenTopics,
}: {
  askHref: string
  dialogueHref: string
  /** Drives `aria-expanded`, so the button says whether the drawer it opens is
   *  already open rather than offering to open it twice. */
  topicsOpen: boolean
  onOpenTopics: () => void
}) => (
  // `flex-none` for the reason every other control in `.chrome-right` is:
  // three buttons at `.btn-ghost.btn-sm` are ~28px each, and the breadcrumb to
  // their left is the element that gives up width on a narrow viewport. A
  // toolbar that shrank would clip a glyph instead.
  <div className="flex flex-none items-center gap-[2px]">
    <Tooltip asChild explanation={TOPICS_HEADING}>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        aria-label={TOPICS_HEADING}
        aria-expanded={topicsOpen}
        onClick={onOpenTopics}
      >
        <SlidersGlyph />
      </button>
    </Tooltip>

    <Tooltip asChild explanation={DIALOGUE}>
      <a className="btn btn-ghost btn-sm no-underline" aria-label={DIALOGUE} href={dialogueHref}>
        <AskGlyph incoming />
      </a>
    </Tooltip>

    <Tooltip asChild explanation={ASK}>
      <a className="btn btn-ghost btn-sm no-underline" aria-label={ASK} href={askHref}>
        <AskGlyph />
      </a>
    </Tooltip>
  </div>
)

/** Sliders rather than the `⚙` the design sketches. A gear at 12px is six
 * indistinguishable teeth, and the drawer this opens is not "settings" -- it
 * is the queue itself plus what configures it, which two adjustable rows say
 * better than a cog does.
 */
export const SlidersGlyph = () => (
  <Glyph>
    <path d="M2 5h9M2 11h9" />
    <circle cx="5" cy="5" r="1.6" />
    <circle cx="9.5" cy="11" r="1.6" />
  </Glyph>
)

/** One bubble, mirrored, and the mirroring is the whole distinction.
 *
 * The two ask routes differ in *direction* and in nothing else -- the
 * component this replaces already argued that, when it refused to fold them
 * into one link with a mode switch: "the direction is what differs, and a
 * reader choosing between 'I have a question' and 'ask me questions' is
 * choosing between two activities, not two settings." Two unrelated glyphs
 * would have said they were unrelated things.
 *
 * Neither reading is left to the picture: both controls carry their sentence
 * as an `aria-label` and as a tooltip, so a reader who takes the tail to mean
 * the opposite of what it means loses nothing.
 */
export const AskGlyph = ({ incoming = false }: { incoming?: boolean }) => (
  <Glyph>
    <g transform={incoming ? 'translate(16 0) scale(-1 1)' : undefined}>
      <rect x="1.5" y="2" width="13" height="8.5" rx="2" />
      <path d="M4.5 10.5v3l3-3" />
      <path d="M6.1 5.1a2 2 0 0 1 3.9.6c0 1.3-1.9 1.4-1.9 2.6" />
      <circle cx="8.1" cy="9.1" r="0.35" fill="currentColor" stroke="none" />
    </g>
  </Glyph>
)

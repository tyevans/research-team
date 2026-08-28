import { type ReactNode, useState } from 'react'

import type { ProjectId } from '@domain/shared/identifier.ts'

import { Tooltip } from '../../common/Tooltip.tsx'
import { projectHref } from '../../routing/routes.ts'
import { TopicsDrawer, TOPICS_HEADING } from './TopicsDrawer.tsx'

const ASK = 'Ask this project'
const DIALOGUE = 'Be asked about this project'

/** The controls that act on the whole queue, as one line above it.
 *
 * It was four stacked bands: two full-width bordered links, a card for the
 * autonomous run, and a card for seeding. Roughly 320px of header above the
 * first topic in a 320px rail, which put the rows -- the only thing on this
 * page a person acts on repeatedly -- below the fold on a short viewport.
 * `docs/design/topic-actions-on-the-row.md` §1 measures it and §2 draws what
 * replaced it.
 *
 * The four had nothing in common except that each was, at some point, the
 * newest thing added to the pane. The docstring this one replaces claimed they
 * were ordered by "how often does somebody touch this", and that ordering was
 * false in both directions: the two ask links leave the page and were first,
 * seeding is touched once per project and was last.
 *
 * **Both ask routes are still reachable, and that is not decoration.** The
 * previous docstring records this pane losing an inbound link twice -- once
 * when deleting `CourseView` and `ResearchView` took the last door to `#/p/
 * <id>/ask`, and again one plan later when `facet: 'dialogue'` shipped with
 * zero `projectHref` call sites. Both were one-way doors that nothing failed
 * on, because no test asserted a route was reachable. `App.test.tsx` holds
 * both links by accessible name, and `QueueHeader.test.tsx` holds the pair
 * against this component directly.
 *
 * **Every control carries its sentence twice.** A `Tooltip` for the mouse and
 * an `aria-label` with the same words, so a keyboard and a screen reader both
 * get it without the tooltip ever opening. An icon with only a tooltip is
 * S-D2, the unlabelled-icon defect this console already records, and
 * `AutonomyLock` is the worked example this follows.
 *
 * **Rendered inside the queue's own toolbar line, not above it.** It is handed
 * to `TopicList` as a node and lands beside the search box, which is why this
 * is a bare flex row with no border and no padding of its own -- the line it
 * sits on belongs to `TopicQueue`. Putting it back above would restore the
 * separate band this slice exists to remove.
 */
export const QueueHeader = ({ projectId }: { projectId: ProjectId }) => {
  const [open, setOpen] = useState(false)

  return (
    <>
      <QueueToolbar
        askHref={projectHref(projectId, { facet: 'ask', id: null })}
        dialogueHref={projectHref(projectId, { facet: 'dialogue', id: null })}
        topicsOpen={open}
        onOpenTopics={() => setOpen(true)}
      />
      {open ? <TopicsDrawer projectId={projectId} onClose={() => setOpen(false)} /> : null}
    </>
  )
}

/** The three controls, from props, so the arrangement has a story.
 *
 * Split from `QueueHeader` for the reason `TopicQueue` is split from
 * `TopicList`: the toolbar's whole content is a width question on a 294px
 * line, and a component that owns drawer state cannot be put in a workbench
 * without a container and an overlay host behind it. This one can.
 */
export const QueueToolbar = ({
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
  // `flex-none` so the search box beside it takes the slack: three buttons at
  // `.btn-ghost.btn-sm` are ~28px each, and a toolbar that shrank would clip a
  // glyph before the field it shares the line with gave up a pixel.
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

/** Drawn rather than written, for `AutonomyLock`'s reason: the console has no
 *  icon set, and a glyph borrowed from one would be the only borrowed glyph in
 *  it. `currentColor` so all three inherit `.btn-ghost`'s hover and disabled
 *  colours instead of declaring their own, and `aria-hidden` because the
 *  control already carries the sentence.
 *
 * A `viewBox` of 16 rendered at 12, unlike the lock's 12-at-12: the question
 * mark inside the bubble below needs room to be a question mark rather than a
 * smudge, and stroke widths scale with the box.
 *
 * Sliders rather than the `⚙` the design sketches. A gear at 12px is six
 * indistinguishable teeth, and the drawer this opens is not "settings" -- it
 * holds what *configures* the queue, which two adjustable rows say better than
 * a cog does.
 */
const SlidersGlyph = () => (
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
const AskGlyph = ({ incoming = false }: { incoming?: boolean }) => (
  <Glyph>
    <g transform={incoming ? 'translate(16 0) scale(-1 1)' : undefined}>
      <rect x="1.5" y="2" width="13" height="8.5" rx="2" />
      <path d="M4.5 10.5v3l3-3" />
      <path d="M6.1 5.1a2 2 0 0 1 3.9.6c0 1.3-1.9 1.4-1.9 2.6" />
      <circle cx="8.1" cy="9.1" r="0.35" fill="currentColor" stroke="none" />
    </g>
  </Glyph>
)

const Glyph = ({ children }: { children: ReactNode }) => (
  <svg
    width="12"
    height="12"
    viewBox="0 0 16 16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.3"
    strokeLinecap="round"
    strokeLinejoin="round"
    aria-hidden="true"
  >
    {children}
  </svg>
)

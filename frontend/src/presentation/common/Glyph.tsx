import type { ReactNode } from 'react'

/** The console's icon frame, and why it is drawn rather than imported.
 *
 * `AutonomyLock` set the policy and `QueueHeader` followed it: this console has
 * no icon set, and a glyph borrowed from one would be the only borrowed glyph
 * in it — a dependency, a build step and a second visual language, for six
 * pictures.
 *
 * `currentColor` so every glyph inherits `.btn-ghost`'s hover and disabled
 * colours instead of declaring its own, and `aria-hidden` because the control
 * around it carries the sentence. An icon whose only name is its picture is
 * S-D2, the unlabelled-icon defect this console already records.
 *
 * A `viewBox` of 16 rendered at 12, which is `QueueHeader`'s measurement and
 * not a fresh choice: the question mark inside the ask bubble needs room to be
 * a question mark rather than a smudge, and stroke widths scale with the box.
 *
 * Lifted out of `QueueHeader` when the topic row grew glyphs of its own. Two
 * spellings of one frame is how a toolbar and the row beneath it come to draw
 * at two different weights without anyone having chosen that.
 */
export const Glyph = ({ children }: { children: ReactNode }) => (
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

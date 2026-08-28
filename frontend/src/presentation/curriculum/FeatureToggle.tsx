import type { CourseCandidate } from '@domain/knowledge/catalog.ts'
import { titleCase } from '@domain/knowledge/title-case.ts'

import { Button } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'

/** Feature or unfeature one candidate, as a single toggle.
 *
 * **It replaces two buttons that were not a toggle.** The catalog rendered
 * `Feature` or `Unfeature` -- different labels, different tones, in a `<div>`
 * stacked *under* the card -- so the control that changes one bit of state was
 * two controls with nothing declaring them the same one. A screen reader was
 * told a button appeared and another disappeared; there was no `aria-pressed`
 * anywhere, and the pressed state was carried entirely by which word was
 * printed.
 *
 * `aria-pressed` also buys the visual state for free and without a new colour:
 * `shell.css`'s `.btn[aria-pressed='true']:not(.btn-accent)` already draws a
 * pressed button in accent border and accent text, which is this console's
 * existing house treatment for "you chose this one". Reusing it rather than
 * writing a tone is the whole reason the toggle is a `Button` and not a bare
 * `<button>` with utilities.
 *
 * **The label is the candidate's own title, not "Feature".** A shelf of twelve
 * cards each offering "Feature" is a screen-reader reading with no way to tell
 * which card the cursor is on -- the same argument `MenuTrigger` makes for
 * requiring its `aria-label`. The visible text stays short; `aria-label`
 * carries the long form, and the `Tooltip` carries the sentence explaining what
 * featuring does, which nothing on the old pair said anywhere.
 */
export const FeatureToggle = ({
  candidate,
  onFeature,
  onUnfeature,
}: {
  candidate: CourseCandidate
  onFeature: (candidate: CourseCandidate) => void
  onUnfeature: (slug: string) => void
}) => {
  const featured = candidate.featuredRank !== null
  const name = titleCase(candidate.title)
  return (
    <Tooltip
      explanation={
        featured
          ? 'Featured courses lead the catalog. Unfeaturing returns this one to its category.'
          : 'Featuring puts this course at the front of the catalog, after the ones already there.'
      }
      asChild
    >
      <Button
        small
        tone="quiet"
        aria-pressed={featured}
        aria-label={featured ? `Unfeature ${name}` : `Feature ${name}`}
        onClick={() => (featured ? onUnfeature(candidate.slug) : onFeature(candidate))}
      >
        {/* The star is decorative and the word is the label. A glyph alone
            would be a control whose meaning is a convention the reader has to
            already hold, and this console has no other starred anything. */}
        <span aria-hidden="true">{featured ? '★' : '☆'}</span> {featured ? 'Featured' : 'Feature'}
      </Button>
    </Tooltip>
  )
}

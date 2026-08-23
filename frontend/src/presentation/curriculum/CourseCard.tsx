import clsx from 'clsx'

import type { CourseCandidate } from '@domain/knowledge/catalog.ts'
import { blurbAge } from '@domain/knowledge/catalog.ts'

/** One course candidate, drawn as a card, in one of three densities.
 *
 * `size` is a computed style -- padding, image height, font scale -- and is
 * asserted only in `course-card-sizing.browser.test.tsx`, which measures the
 * rendered widths. jsdom lays nothing out, so a test here that compared class
 * names between sizes would prove nothing about what the cascade did with
 * them; this file gives each size its own class and stops there.
 *
 * A plain `<button>` rather than a link with a click handler: the catalog
 * opens a candidate into an in-page detail view (Task 13), not a navigation,
 * and a button is what a screen reader announces correctly for that.
 */
export const CourseCard = ({
  candidate,
  size,
  onOpen,
}: {
  candidate: CourseCandidate
  size: 'hero' | 'highlight' | 'filed'
  onOpen: (slug: string) => void
}) => {
  const featured = candidate.featuredRank !== null
  const stale = blurbAge(candidate) === 'stale'

  return (
    <button
      type="button"
      onClick={() => onOpen(candidate.slug)}
      // `border-0` zeroes the three sides a directional width would otherwise
      // leave at the browser's ~3px default (no Tailwind preflight here); see
      // CLAUDE.md's border-solid entry. Never paired with a plain `border`.
      className={clsx(
        'crs-card',
        `crs-card-${size}`,
        'rounded-lg flex flex-col items-stretch overflow-hidden border-0 border-t-2 border-solid text-left',
        'border-line bg-bg-panel',
        // Width is the one property distinguishing the three densities in
        // this pass -- the browser test measures exactly this and nothing in
        // jsdom can, so a class name change here with no matching width
        // change would still pass every other test. Arbitrary `w-[…]` values
        // rather than `w-80`/`w-56`/`w-40`: the default theme is deliberately
        // not imported (`theme.css`), so the numbered spacing scale those
        // utilities read from does not exist here and they generate nothing.
        size === 'hero' && 'w-[320px]',
        size === 'highlight' && 'w-[224px]',
        size === 'filed' && 'w-[160px]',
        featured && 'border-accent',
        'focus-visible:lay-ring-inward',
      )}
    >
      <img
        src={candidate.art.url}
        alt={candidate.art.alt}
        className="crs-card-art w-full object-cover"
      />
      <div className="flex flex-col gap-1 px-3 py-2">
        {featured && (
          // Text, not colour alone -- a border tint says nothing to a screen
          // reader, and `featuredRank` is the fact this line reports.
          <span className="crs-card-featured font-semibold tracking-wide text-xs text-accent uppercase">
            Featured
          </span>
        )}
        <span className="crs-card-title font-semibold text-fg">{candidate.title}</span>
        {candidate.blurb !== null && (
          <p className="crs-card-blurb text-fg-muted text-sm">
            {candidate.blurb.text}
            {stale && (
              <span className="crs-card-stale text-fg-muted ml-1 text-xs italic">
                (out of date)
              </span>
            )}
          </p>
        )}
      </div>
    </button>
  )
}

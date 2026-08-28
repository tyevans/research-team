import { formatDistanceToNow } from 'date-fns'

import type { CourseCandidate } from '@domain/knowledge/catalog.ts'
import { blurbAge } from '@domain/knowledge/catalog.ts'
import { titleCase } from '@domain/knowledge/title-case.ts'

import { Button, Chip } from '../common/primitives.tsx'
import { FeatureToggle } from './FeatureToggle.tsx'

/** The one candidate the catalog leads with, drawn as a banner.
 *
 * **Why one card gets to be twelve times the size of the others.** A shelf of
 * equal cards has no entry point: every catalog surface a person actually uses
 * -- a bookshop table, a streaming front page, a journal cover -- answers "where
 * do I start" before it answers "what is there". This page previously had a
 * section called Hero whose cards were 320px against the highlights' 224px,
 * which is a hierarchy nobody perceives; either the top item leads or the
 * heading is decorative.
 *
 * What fills it is chosen in `arrangeCatalog` and not here: the first *curated*
 * candidate when somebody has curated, the most prominent otherwise.
 *
 * **The anchors are the reason this is worth the space.** `CourseCandidate`
 * carries its `anchors` -- the cluster's most central entities -- on every
 * request, and no catalog surface has ever rendered one. They are the single
 * most concrete statement of what a course would be *about*, far more so than a
 * generated blurb, and they are what makes the banner an argument rather than a
 * large picture.
 *
 * **`date-fns` for the age of the copy.** The console had two hand-rolled
 * date renderings on this screen (`toLocaleDateString`, and nothing at all for
 * blurb age) while `date-fns` sat installed and unused. "written 3 days ago"
 * is the form that tells a reader whether the copy predates the last extraction
 * run, which is the question staleness is really about.
 */
export const CatalogSpotlight = ({
  candidate,
  onOpen,
  onFeature,
  onUnfeature,
}: {
  candidate: CourseCandidate
  onOpen: (slug: string) => void
  onFeature: (candidate: CourseCandidate) => void
  onUnfeature: (slug: string) => void
}) => {
  const stale = blurbAge(candidate) === 'stale'
  const name = titleCase(candidate.title)

  return (
    <section
      aria-labelledby="crs-spotlight-title"
      className="crs-spotlight relative flex min-h-[240px] items-end overflow-hidden rounded-md border-0 border-t-2 border-solid border-accent bg-bg-panel"
    >
      {/* Full-bleed art behind the copy. `absolute inset-0` + `object-cover`
          rather than a background-image: a `<img>` keeps the alt text, and the
          alt text is the only thing a non-visual reader gets from generated
          art. */}
      <img
        src={candidate.art.url}
        alt={candidate.art.alt}
        className="crs-spotlight-art absolute inset-0 h-full w-full object-cover"
      />
      {/* Two scrims, not one. The vertical gradient keeps the lower half dark
          enough for body text; the flat wash keeps the whole frame from
          competing with the rest of the page, because generated art arrives at
          whatever brightness the model chose and one of them will be a white
          marble statue. Measured only by eye -- there is no contrast assertion
          over an image, which is exactly why the wash is heavier than it looks
          like it needs to be. */}
      <div
        aria-hidden="true"
        className="absolute inset-0 bg-[linear-gradient(to_top,rgba(11,13,16,0.96)_0%,rgba(11,13,16,0.78)_45%,rgba(11,13,16,0.35)_100%)]"
      />

      <div className="relative flex min-w-0 flex-col gap-2 p-5">
        <div className="flex flex-wrap items-center gap-2">
          <span className="tracking-wide text-xs font-semibold text-accent uppercase">
            {candidate.featuredRank !== null ? 'Featured' : 'Most prominent'}
          </span>
          {stale && <span className="text-xs text-fg-dim">copy is out of date</span>}
        </div>

        <h2 id="crs-spotlight-title" className="crs-spotlight-title m-0 text-2xl text-fg">
          {name}
        </h2>

        {candidate.blurb !== null && (
          <p className="crs-spotlight-blurb m-0 max-w-[62ch] text-md text-fg-dim">
            {candidate.blurb.text}
          </p>
        )}

        {candidate.anchors.length > 0 && (
          <ul className="crs-spotlight-anchors m-0 flex list-none flex-wrap gap-1 p-0">
            {/* Six, not all of them. A cluster can carry dozens of anchors and
                a banner that wraps to five rows of chips stops being a banner;
                six is what fits one row at the narrowest layout this pane is
                given. The count is not hidden -- `ProminenceMeter` on the cards
                and the entity count below both report the whole size. */}
            {candidate.anchors.slice(0, 6).map((anchor) => (
              <li key={anchor.entityId}>
                <Chip>{anchor.name}</Chip>
              </li>
            ))}
          </ul>
        )}

        <p className="m-0 font-mono text-xs text-fg-faint">
          {candidate.size} {candidate.size === 1 ? 'entity' : 'entities'}
          {candidate.blurb !== null && (
            <> · copy written {writtenAgo(candidate.blurb.generatedAt)}</>
          )}
        </p>

        <div className="mt-1 flex flex-wrap items-center gap-2">
          <Button tone="accent" onClick={() => onOpen(candidate.slug)}>
            Open {name}
          </Button>
          <FeatureToggle candidate={candidate} onFeature={onFeature} onUnfeature={onUnfeature} />
        </div>
      </div>
    </section>
  )
}

/** "3 days ago", or the raw value when the server sends something
 *  unparseable.
 *
 * `date-fns` throws a `RangeError` on an invalid date rather than returning
 * "Invalid Date", so an unparseable `generatedAt` would take the whole catalog
 * down with a stack trace and no clue which candidate did it. Guarded here
 * rather than trusted: this field crosses a wire, and the repository's own
 * history has a case of a timestamp field arriving in a shape the client did
 * not expect (`membershipHash`, in `catalog.ts`'s docstring).
 */
const writtenAgo = (iso: string): string => {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  return formatDistanceToNow(at, { addSuffix: true })
}

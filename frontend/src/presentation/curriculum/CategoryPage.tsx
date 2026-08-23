import type { Category, CourseCandidate } from '@domain/knowledge/catalog.ts'

import { Button } from '../common/primitives.tsx'
import { CourseCard } from './CourseCard.tsx'

/** One category, filed candidates and all -- what `#/p/<id>/catalog/<key>`
 *  opens into.
 *
 * `category.candidates` can be empty even for a `key` the catalog knows about:
 * every candidate a category ever held may have been promoted to hero or
 * highlights, which is a real state (`Catalog.categories` still carries the
 * label so this page has something to call itself) rather than a missing one.
 */
export const CategoryPage = ({
  category,
  onOpen,
  onBack,
  onFeature,
  onUnfeature,
}: {
  category: Category
  onOpen: (slug: string) => void
  onBack: () => void
  onFeature: (candidate: CourseCandidate) => void
  onUnfeature: (slug: string) => void
}) => (
  <div className="flex flex-col gap-3 p-3">
    <div className="flex items-center gap-2">
      <Button small onClick={onBack}>
        Back to catalog
      </Button>
      <h2 className="font-semibold text-lg text-fg">{category.label}</h2>
    </div>
    {category.candidates.length === 0 ? (
      <p className="text-fg-muted text-sm">
        Every candidate filed here has been promoted to the front page.
      </p>
    ) : (
      <div className="flex flex-wrap gap-3">
        {category.candidates.map((candidate) => (
          <div key={candidate.slug} className="flex flex-col items-stretch gap-1">
            <CourseCard candidate={candidate} size="filed" onOpen={onOpen} />
            {candidate.featuredRank === null ? (
              <Button small onClick={() => onFeature(candidate)}>
                Feature
              </Button>
            ) : (
              <Button small tone="quiet" onClick={() => onUnfeature(candidate.slug)}>
                Unfeature
              </Button>
            )}
          </div>
        ))}
      </div>
    )}
  </div>
)

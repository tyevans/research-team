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
 *
 * **The front page no longer sends anybody here.** Its category filter narrows
 * in place, which is what a browsing surface should do with a filter -- losing
 * every other card behind a click was the old page's worst navigation. This
 * route survives because links to it exist and were correct when written; it is
 * a deep link, not a step in a flow. If that stops being true, this component
 * and its route go together.
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
  <div className="flex min-h-0 flex-col gap-3 overflow-y-auto p-3">
    <div className="flex items-center gap-2">
      <Button small onClick={onBack}>
        Back to catalog
      </Button>
      <h2 className="m-0 text-lg font-semibold text-fg">{category.label}</h2>
      <span className="font-mono text-xs text-fg-faint">{category.candidates.length}</span>
    </div>
    {category.candidates.length === 0 ? (
      <p className="text-sm text-fg-dim">
        Every candidate filed here has been promoted to the front page.
      </p>
    ) : (
      <div className="flex flex-wrap items-start gap-3">
        {category.candidates.map((candidate) => (
          <CourseCard
            key={candidate.slug}
            candidate={candidate}
            size="filed"
            onOpen={onOpen}
            onFeature={onFeature}
            onUnfeature={onUnfeature}
          />
        ))}
      </div>
    )}
  </div>
)

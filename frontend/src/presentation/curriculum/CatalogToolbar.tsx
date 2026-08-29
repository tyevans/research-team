import clsx from 'clsx'
import { useId } from 'react'

import { Choices } from '../common/Choices.tsx'
import { Button } from '../common/primitives.tsx'
import type { CatalogQuery, CatalogSort } from './catalog-view.ts'
import { isNarrowed } from './catalog-view.ts'

/** Search, sort and category filter for the catalog.
 *
 * **This is the capability the page did not have.** Every field it reads --
 * title, blurb, category, anchor names, `prominence`, `size`,
 * `blurb.generatedAt` -- was already on the wire and already in memory, and the
 * page rendered a wall of cards in one server-chosen order with no way to ask
 * it anything. A curator looking for the area they half-remember an entity from
 * had to read every card.
 *
 * **`Choices` rather than a `<select>` for the sort.** A `<select>` collapses
 * four options to one line of text and hides the other three behind a popup a
 * reader has to open to learn the question has answers; the whole point of a
 * sort control on a browsing surface is that the alternatives are visible.
 * `Choices` is also the console's existing answer to "one question, a fixed set
 * of answers", and it brings the radio-group keyboard contract with it -- see
 * its own docstring on why that is not the eight lines it looks like.
 *
 * **The category filter is buttons rather than a second `Choices`.** It has a
 * variable number of options including "everything", it changes as the catalog
 * re-clusters, and a radiogroup whose members appear and disappear underneath a
 * roving tabindex is a keyboard trap waiting to be reported. Toggle buttons
 * carrying `aria-pressed` say the same thing with no roving state to lose.
 */

const SORTS: readonly { id: CatalogSort; label: string; explanation: string }[] = [
  {
    id: 'prominence',
    label: 'Prominent',
    explanation: "The server's own ranking: how central this cluster is to the project.",
  },
  { id: 'size', label: 'Largest', explanation: 'Most entities in the cluster first.' },
  { id: 'title', label: 'A–Z', explanation: 'Alphabetical by title.' },
  {
    id: 'fresh',
    label: 'Newest copy',
    explanation: 'Most recently written blurb first. Candidates with no copy come last.',
  },
]

export const CatalogToolbar = ({
  query,
  onQuery,
  categories,
  matched,
  total,
}: {
  query: CatalogQuery
  onQuery: (query: CatalogQuery) => void
  categories: readonly { readonly key: string; readonly label: string }[]
  matched: number
  total: number
}) => {
  const searchId = useId()
  const narrowed = isNarrowed(query)

  return (
    <div className="crs-toolbar flex flex-col gap-3">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex min-w-[220px] flex-1 flex-col gap-1">
          {/* A real `<label>`, not a placeholder. A placeholder disappears the
              moment anything is typed, so a reader who looks away loses the
              only statement of what the field is for -- and it is announced by
              nothing when the field is empty in some readers. */}
          <label htmlFor={searchId} className="text-xs font-semibold text-fg-dim uppercase">
            Search the catalog
          </label>
          <input
            id={searchId}
            type="search"
            value={query.text}
            onChange={(event) => onQuery({ ...query, text: event.target.value })}
            placeholder="a title, a blurb, or an entity you remember"
            className="rounded-md border border-solid border-line bg-bg-panel px-3 py-1 text-fg"
          />
        </div>
        <Choices
          label="How to order the catalog"
          options={SORTS}
          value={query.sort}
          onValueChange={(sort) => onQuery({ ...query, sort })}
        />
      </div>

      {categories.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            small
            tone="quiet"
            aria-pressed={query.category === null}
            onClick={() => onQuery({ ...query, category: null })}
          >
            Everything
          </Button>
          {categories.map((category) => (
            <Button
              key={category.key}
              small
              tone="quiet"
              aria-pressed={query.category === category.key}
              onClick={() =>
                onQuery({
                  ...query,
                  category: query.category === category.key ? null : category.key,
                })
              }
            >
              {category.label}
            </Button>
          ))}
        </div>
      )}

      {/* `role="status"` so a screen reader hears the count change as the
          reader types, rather than discovering it by wandering into the list.
          Rendered unconditionally so the live region exists before it has
          anything to say -- a region inserted at the same moment as its first
          message is a region most readers never announce. */}
      <p role="status" className={clsx('m-0 text-xs', narrowed ? 'text-fg-dim' : 'text-fg-faint')}>
        {narrowed
          ? `${matched} of ${total} ${total === 1 ? 'course' : 'courses'} match.`
          : `${total} ${total === 1 ? 'course' : 'courses'} in this catalog.`}
      </p>
    </div>
  )
}

import { useRef } from 'react'
import clsx from 'clsx'

import { documentLabel, isDropped, type DocumentSummary } from '@domain/research/document.ts'
import type { SourceId } from '@domain/shared/identifier.ts'

import { EmptyState } from '../common/primitives.tsx'
import { VirtualList } from '../common/VirtualList.tsx'

const ROW_HEIGHT = 52

/** Every source this project has stored, virtualized so a corpus of hundreds
 *  of papers costs the same to render as one of ten.
 *
 * Presentational: it is handed the corpus and the filter and renders them.
 * The virtualizer stays here rather than moving to the hook, and that is the
 * line this split draws — a virtualizer is *layout*, it needs the scroll
 * element this component owns a ref to, and nothing about it reaches the
 * network. Fetching is what a presentational component may not do.
 *
 * Dropped documents stay in the list rather than being filtered out -- the
 * corpus keeps them as an audit trail, and hiding them here would misreport
 * what the project holds. They render with their reason and a visual mark
 * instead.
 */
export const DocumentBrowser = ({
  documents,
  total,
  filter,
  onFilterChange,
  onOpen,
}: {
  /** Already filtered. Filtering is a `useMemo` in the hook rather than a
   *  table library: the whole point of trying `react-virtual` first is that a
   *  plain list is all a document browser needs. */
  documents: readonly DocumentSummary[]
  /** How many the corpus holds before filtering, which is what tells "nothing
   *  stored" apart from "nothing matches". The old component could only render
   *  the first, because it returned early on it before the filter existed. */
  total: number
  filter: string
  onFilterChange: (filter: string) => void
  onOpen: (sourceId: SourceId) => void
}) => {
  const scrollRef = useRef<HTMLDivElement>(null)

  if (total === 0) {
    return (
      <EmptyState heading="No documents" detail="Nothing has been stored in this corpus yet." />
    )
  }

  return (
    <div className="document-browser">
      <input
        type="search"
        className="input document-filter"
        placeholder="Filter documents"
        value={filter}
        onChange={(event) => onFilterChange(event.target.value)}
        aria-label="Filter documents"
      />
      {documents.length === 0 ? (
        <EmptyState
          heading="No documents match"
          detail="Nothing in this corpus matches that filter."
        />
      ) : (
        <div ref={scrollRef} className="document-list-scroll">
          <VirtualList
            items={documents}
            scrollRef={scrollRef}
            className="document-list"
            getKey={(row) => row.sourceId}
            estimate={() => ROW_HEIGHT}
            overscan={8}
          >
            {(row, position) => (
              <DocumentRow
                document={row}
                index={position.index}
                top={position.top}
                measure={position.measure}
                onOpen={() => onOpen(row.sourceId)}
              />
            )}
          </VirtualList>
        </div>
      )}
    </div>
  )
}

const DocumentRow = ({
  document,
  index,
  top,
  measure,
  onOpen,
}: {
  document: DocumentSummary
  /** The virtualizer reads this back off the DOM node to know which row it
   *  just measured, so it has to be on the element `measure` is given. */
  index: number
  top: number
  measure: (element: HTMLElement | null) => void
  onOpen: () => void
}) => (
  <li
    ref={measure}
    data-index={index}
    className={clsx('document-row', isDropped(document) && 'document-dropped')}
    // Positioned by transform rather than `top`, and with no height at all:
    // the row is now as tall as its content, and `translateY` is what the
    // virtualizer's own measurement expects to find -- a `top` offset would be
    // counted twice once a row reports a height different from the estimate.
    style={{
      position: 'absolute',
      top: 0,
      left: 0,
      right: 0,
      transform: `translateY(${String(top)}px)`,
    }}
  >
    <button type="button" className="document-row-open" onClick={onOpen}>
      <span className="document-row-title">{documentLabel(document)}</span>
      <span className="document-row-meta">{document.charCount} chars</span>
      {isDropped(document) ? (
        <span className="document-row-dropped-reason">Dropped: {document.droppedReason}</span>
      ) : null}
    </button>
  </li>
)

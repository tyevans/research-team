import { useRef } from 'react'
import clsx from 'clsx'

import { documentLabel, isDropped, type DocumentSummary } from '@domain/research/document.ts'
import type { SourceId } from '@domain/shared/identifier.ts'

import { EmptyState } from '../common/primitives.tsx'
import { VirtualList } from '../common/VirtualList.tsx'

const ROW_HEIGHT = 52

/** The scroller's inward focus ring, and the reason it is `-2px` rather than
 *  the global `+1px`.
 *
 * Chromium makes a scroll container focusable with no `tabIndex` at all, so
 * this element is a real tab stop as soon as the corpus is longer than the
 * pane. `tokens.css`'s global `:focus-visible` draws 2px at `outline-offset:
 * 1px` — three pixels *outside* the border box — which lands on the far side of
 * this element's own 1px border and is then clipped by whatever the region
 * around it does with overflow. Measured at 1440x900 before the fix that put
 * this rule in `research.css`: `-3..343 x -3..203` against a border box of
 * `0..340 x 0..200`. `DocumentBrowser.browser.test.tsx` is the measurement and
 * still is; only the spelling moved from a stylesheet to a utility.
 *
 * `outline-offset-[-2px]` in brackets rather than `-outline-offset-2`: the
 * negative-prefix form exists in Tailwind and the arbitrary one cannot be
 * misread, which matters for a value whose sign is the whole point. */
const RING_INWARD =
  'focus-visible:outline-2 focus-visible:outline-accent focus-visible:outline-offset-[-2px]'

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
    <div className="flex h-full flex-col gap-[8px]">
      {/* `input` stays a class: it is the shared field style, declared in
          `tree.css` and `composer.css` for every text field in the console, and
          it is not this slice's to dissolve. */}
      <input
        type="search"
        className="input w-full"
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
        // `flex-auto` and not `flex-1`: `flex-1` is `1 1 0%`, and the rule this
        // replaces was `flex: 1 1 auto`. The difference shows only when the
        // filter box above shares the column, which is always.
        //
        // `data-document-scroll` rather than a class hook, because the thing
        // being identified here is "the element the virtualizer scrolls" and
        // the browser test needs to find it after the class names became
        // dressing that any refactor may reshuffle.
        <div
          ref={scrollRef}
          data-document-scroll
          className={clsx(
            'min-h-0 flex-auto overflow-y-auto rounded-md border border-solid border-line',
            RING_INWARD,
          )}
        >
          <VirtualList
            items={documents}
            scrollRef={scrollRef}
            className="m-0 list-none p-0"
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
    data-document-row
    // `data-dropped` carries the state and the left edge draws it. The same
    // loud edge `.topic-blocked` uses: a dropped document cannot be read back,
    // and that fact should be visible without opening the row.
    //
    // `border-0` first and then *two* edges, which is the case the single-side
    // rule is easiest to get wrong in: `border-solid` styles all four sides, so
    // without the zero the top and right would draw at the browser's `medium`
    // (~3px) while only the bottom and left were meant to. The colours are per
    // edge for the same reason `Findings` splits its map out — one
    // `border-<colour>` utility and one `border-l-<colour>` utility on the same
    // element are both `@layer utilities` and their order is Tailwind's, not
    // the attribute's.
    data-dropped={isDropped(document)}
    className={clsx(
      'border-0 border-b border-solid border-b-line-soft',
      isDropped(document) && 'border-l-2 border-l-k-failure',
    )}
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
    {/* No height of its own: the row's height comes from this button's content
        and is measured off it, so a fixed height here would be the same lie the
        virtualizer's fixed row estimate was.

        `[font:inherit]` is arbitrary because the `font` shorthand has no
        utility, and a `<button>` that does not inherit it renders in the user
        agent's 13.33px sans — this build imports no preflight, so nothing else
        resets it.

        The inward ring is the measured fix `research.css` carried: this button
        is `w-full` inside a scroller with no padding, so its border box *is*
        the scroller's padding box horizontally, and `overflow` clips there.
        Every row in the list lost its sides to the global outward ring; the
        first, which is the one a reader meets, kept only a 2px line along its
        bottom. Hover already paints the whole row, so the ring is what
        separates "focused" from "pointed at" and cannot be traded away. */}
    <button
      type="button"
      onClick={onOpen}
      className={clsx(
        'flex w-full cursor-pointer flex-col items-start gap-[2px] border-0 bg-transparent px-3 pt-[7px] pb-[8px] text-left text-inherit [font:inherit] hover:bg-bg-panel-2',
        RING_INWARD,
      )}
    >
      <span className="text-sm">{documentLabel(document)}</span>
      <span className="font-mono text-xs text-fg-dim">{document.charCount} chars</span>
      {isDropped(document) ? (
        <span className="text-xs text-k-failure">Dropped: {document.droppedReason}</span>
      ) : null}
    </button>
  </li>
)

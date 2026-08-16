import { useRef } from 'react'
import clsx from 'clsx'

import {
  documentLabel,
  formatBytes,
  isDropped,
  type SourceSummary,
} from '@domain/research/document.ts'
import {
  canExtract,
  documentExtraction,
  type DocumentExtraction,
  type ExtractionQueueBoard,
} from '@domain/research/extraction-queue.ts'
import type { SourceId } from '@domain/shared/identifier.ts'

import { Button, EmptyState } from '../common/primitives.tsx'
import { Tooltip } from '../common/Tooltip.tsx'
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
 * **It was three utilities and it never applied.** This constant shipped as
 * `focus-visible:outline-2 focus-visible:outline-accent
 * focus-visible:outline-offset-[-2px]`, and `tokens.css`'s global
 * `:focus-visible` is *unlayered* -- which beats a declaration in `@layer
 * utilities` regardless of specificity. So `outline-offset` computed as `1px`
 * on every row this dressed, the ring stayed three pixels outside the border
 * box exactly as before the fix, and the browser test below went red the first
 * time anybody ran it -- which was slice 3b, because 3a's report records that
 * no suite was run locally and CI would be first. Found there and fixed here.
 *
 * `.lay-ring-inward` in `layout.css` is the same declarations somewhere they
 * can win, and carries the measurement and the argument against `!`. */
const RING_INWARD = 'lay-ring-inward'

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
  queue,
  extractableCount,
  queueSize,
  busy,
  cancelling,
  onExtract,
  onExtractAll,
  onCancelExtraction,
  onAdd,
}: {
  /** Already filtered. Filtering is a `useMemo` in the hook rather than a
   *  table library: the whole point of trying `react-virtual` first is that a
   *  plain list is all a document browser needs. */
  documents: readonly SourceSummary[]
  /** How many the corpus holds before filtering, which is what tells "nothing
   *  stored" apart from "nothing matches". The old component could only render
   *  the first, because it returned early on it before the filter existed. */
  total: number
  filter: string
  onFilterChange: (filter: string) => void
  onOpen: (sourceId: SourceId) => void
  /** What the project is extracting right now. The rows read their own state
   *  out of it via `documentExtraction`, rather than being handed a per-row
   *  flag: the states are exclusive and deriving them in one place is what
   *  stops a row drawing "queued" beside "extracted". */
  queue: ExtractionQueueBoard
  /** How many the "extract all" press would take on, over the whole corpus and
   *  not the filtered view -- the server computes the set itself and does not
   *  know what the reader has filtered to. */
  extractableCount: number
  /** Running plus waiting: what a stop control would actually stop. */
  queueSize: number
  /** A press is in flight. Both extract controls go quiet together, because
   *  they queue into the same place and letting one run while the other is
   *  pending invites two presses for one intention. */
  busy: boolean
  cancelling: boolean
  onExtract: (sourceId: SourceId) => void
  onExtractAll: () => void
  onCancelExtraction: () => void
  onAdd: () => void
}) => {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Not gated on `total`, deliberately: everything below this point sits
  // behind the `total === 0` guard because it has nothing to act on over an
  // empty corpus (nothing to filter, nothing to extract) -- but "Add" is the
  // one control an empty corpus makes *more* relevant, not less. Placed
  // before the guard so it survives the early return that follows.
  const addControl = (
    <Tooltip asChild explanation="Store a document you have, rather than one an agent found">
      <Button small tone="quiet" onClick={onAdd}>
        Add
      </Button>
    </Tooltip>
  )

  if (total === 0) {
    return (
      <div className="flex h-full flex-col gap-[8px]">
        <div className="flex items-center justify-end">{addControl}</div>
        <EmptyState heading="No documents" detail="Nothing has been stored in this corpus yet." />
      </div>
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
      {/* One extract-all and one stop for the whole project, matching
          `TopicQueue`'s bar: the queue is per project on the server, so a
          per-row stop would offer an action it cannot honour. It sits after
          the `total === 0` guard above, because a control that would extract
          nothing over a corpus holding nothing is a control with nothing to
          do. */}
      <div className="flex items-center justify-between gap-[8px] font-mono text-xs text-fg-dim">
        <span>
          {queueSize > 0
            ? `${String(queueSize)} extracting or queued`
            : `${String(extractableCount)} not extracted`}
        </span>
        <span className="flex items-center gap-[6px]">
          {queueSize > 0 ? (
            <Tooltip asChild explanation="Stop the running extraction and drop everything queued">
              <Button small tone="quiet" disabled={cancelling} onClick={onCancelExtraction}>
                Stop
              </Button>
            </Tooltip>
          ) : null}
          {/* `aria-disabled` rather than `disabled`, for the reason
              `TopicQueue` writes out at length: this button spends most of its
              life off, the tooltip is the only answer to "why", and a
              `disabled` element takes neither focus nor pointer events so the
              tooltip could never open. The press is guarded in the handler
              instead, which is the cost -- nothing but that guard stops the
              click. */}
          <Tooltip
            asChild
            explanation={
              extractableCount === 0
                ? 'Every document in this corpus is already extracted or queued'
                : 'Queue every document that has not been folded into the graph yet'
            }
          >
            <Button
              small
              tone="quiet"
              aria-disabled={busy || extractableCount === 0}
              onClick={() => {
                if (busy || extractableCount === 0) return
                onExtractAll()
              }}
            >
              Extract all ({extractableCount})
            </Button>
          </Tooltip>
          {addControl}
        </span>
      </div>
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
                extraction={documentExtraction(row, queue)}
                busy={busy}
                onOpen={() => onOpen(row.sourceId)}
                onExtract={() => onExtract(row.sourceId)}
              />
            )}
          </VirtualList>
        </div>
      )}
    </div>
  )
}

/** What each extraction state says on the row, and what its control offers.
 *
 * A table rather than a chain of ternaries in the markup, because the states
 * are exclusive and the failure mode of spelling them inline is drawing two.
 * `null` for `note` where the button already says it: an "Extract" button
 * beside the words "not extracted" is the same fact twice on a 340px row.
 */
const EXTRACTION_NOTE: Record<DocumentExtraction['kind'], string | null> = {
  dropped: null,
  // Nothing said on a media row: it is not "not extracted yet", it is not the
  // kind of thing extraction applies to, and a note saying so on every media
  // row would be a permanent apology in a 340px rail.
  unextractable: null,
  running: 'Extracting…',
  queued: 'Queued for extraction',
  // The detail rides beside this rather than replacing it -- see the row.
  failed: 'Extraction failed',
  extracted: 'Extracted',
  idle: null,
}

const DocumentRow = ({
  document,
  index,
  top,
  measure,
  extraction,
  busy,
  onOpen,
  onExtract,
}: {
  document: SourceSummary
  /** The virtualizer reads this back off the DOM node to know which row it
   *  just measured, so it has to be on the element `measure` is given. */
  index: number
  top: number
  measure: (element: HTMLElement | null) => void
  extraction: DocumentExtraction
  busy: boolean
  onOpen: () => void
  onExtract: () => void
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
    data-extraction={extraction.kind}
    className={clsx(
      // `flex` and not the bare block it was: the row is the open button plus
      // a sibling action now, because a button cannot nest inside a button and
      // the open control fills the row. `items-stretch` so the action's hit
      // area is the full height of a two-line title rather than a target that
      // shrinks as the title grows.
      'flex items-stretch border-0 border-b border-solid border-b-line-soft',
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
    {/* `data-document-open` because "the control that opens this document" is
        now one of two buttons in the row, and both the browser test's ring
        measurement and any future query need to name it rather than take the
        first `<button>` they find. `min-w-0` so a long title wraps instead of
        pushing the action off the 340px rail -- a flex item's default
        `min-width: auto` refuses to shrink below its content. */}
    <button
      type="button"
      data-document-open
      onClick={onOpen}
      className={clsx(
        'flex min-w-0 flex-auto cursor-pointer flex-col items-start gap-[2px] border-0 bg-transparent px-3 pt-[7px] pb-[8px] text-left text-inherit [font:inherit] hover:bg-bg-panel-2',
        RING_INWARD,
      )}
    >
      <span className="text-sm">{documentLabel(document)}</span>
      {/* Switched on `kind` rather than reading a widened row: "0 chars" under
          a video reads as an empty document, which is a plausible-looking
          wrong answer and worse than a blank. The size comes first because it
          is what tells two recordings apart at a glance; the mimetype is the
          smaller fact and rides behind it. */}
      <span className="font-mono text-xs text-fg-dim">
        {document.kind === 'media'
          ? `${formatBytes(document.byteCount)} · ${document.mediaType}`
          : `${String(document.charCount)} chars`}
      </span>
      {isDropped(document) ? (
        <span className="text-xs text-k-failure">Dropped: {document.droppedReason}</span>
      ) : null}
      {EXTRACTION_NOTE[extraction.kind] ? (
        <span
          className={clsx(
            'font-mono text-xs',
            extraction.kind === 'failed' ? 'text-k-failure' : 'text-fg-dim',
          )}
        >
          {EXTRACTION_NOTE[extraction.kind]}
          {/* The failure's own account of itself. Nothing durable records that
              an extraction was even requested, so this string exists only in
              the queue's memory and is gone on a restart -- dropping it here
              would leave the reader told that a document is not extracted and
              never told why. */}
          {extraction.kind === 'failed' && extraction.detail ? `: ${extraction.detail}` : ''}
        </span>
      ) : null}
    </button>
    <ExtractAction document={document} extraction={extraction} busy={busy} onExtract={onExtract} />
  </li>
)

/** The per-row extract control, or nothing at all.
 *
 * Nothing at all for a dropped document, rather than an off button: the server
 * excludes dropped documents from extract-all, so an off control here would be
 * a promise that pressing it might one day work. The states that *can* still
 * become extractable -- a failure, an untouched document -- keep a live button;
 * the ones that cannot right now keep a focusable `aria-disabled` one, so the
 * tooltip explaining why is reachable by something other than a mouse.
 */
const ExtractAction = ({
  document,
  extraction,
  busy,
  onExtract,
}: {
  document: SourceSummary
  extraction: DocumentExtraction
  busy: boolean
  onExtract: () => void
}) => {
  // Nothing at all for media too, and for the same reason as dropped: the
  // server's extract-all excludes it, so an `aria-disabled` button here would
  // be a promise that pressing it might one day work.
  if (extraction.kind === 'dropped' || extraction.kind === 'unextractable') return null
  const off = busy || !canExtract(extraction)
  return (
    <span className="flex shrink-0 items-center pr-3 pl-[6px]">
      <Tooltip asChild explanation={explain(extraction, documentLabel(document))}>
        <Button
          small
          tone="quiet"
          aria-disabled={off}
          onClick={() => {
            if (off) return
            onExtract()
          }}
        >
          {extraction.kind === 'failed' ? 'Retry' : 'Extract'}
        </Button>
      </Tooltip>
    </span>
  )
}

const explain = (extraction: DocumentExtraction, label: string): string => {
  switch (extraction.kind) {
    case 'running':
      return `${label} is being extracted now`
    case 'queued':
      return `${label} is already waiting to be extracted`
    case 'extracted':
      return `${label} has already been folded into the graph`
    case 'failed':
      return `Try extracting ${label} again`
    default:
      return `Fold ${label} into this project's graph`
  }
}

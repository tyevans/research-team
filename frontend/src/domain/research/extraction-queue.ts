import type { SourceId } from '../shared/identifier.ts'
import { isDropped, type DocumentSummary } from './document.ts'

/** How one document's most recent extraction went.
 *
 * `detail` is only ever set on a failure, and it is the *only* account of that
 * failure anywhere: nothing durable records that an extraction was requested,
 * so a failed one appends nothing to any stream. See `finished()` in
 * `extraction_queue.py`. Losing it here means the reader is told a document
 * is not extracted and never told why.
 *
 * `entities`/`relationships` are the other way round -- present on a success,
 * absent on a failure -- and are reported rather than stored, so a reader can
 * tell "extracted, found nothing" from "extracted, found the graph".
 */
export interface ExtractionOutcome {
  readonly sourceId: SourceId
  readonly status: 'done' | 'failed'
  readonly detail: string | null
  readonly entities: number | null
  readonly relationships: number | null
}

/** The whole project's extraction queue, as `/sources/extraction-queue`
 *  answers it: one running item at most, the rest waiting, and the last
 *  outcome per document.
 *
 * Deliberately the same three-list shape as `DispatchBoard`, because it is the
 * same kind of thing read the same way -- one catch-up route rather than a
 * frame per document. The queue publishes no frames of its own at all (see
 * `get_extraction_queue`), which is why this read exists and why it is the
 * only way to learn that something is *waiting*.
 */
export interface ExtractionQueueBoard {
  readonly running: SourceId | null
  readonly queued: readonly SourceId[]
  readonly finished: readonly ExtractionOutcome[]
}

export const emptyExtractionQueue: ExtractionQueueBoard = {
  running: null,
  queued: [],
  finished: [],
}

/** What a document row should say about extraction, and whether it may offer
 *  it.
 *
 * One value rather than a handful of booleans on the row, because the states
 * are exclusive and a row that computed them separately would eventually draw
 * two at once -- "queued" beside "extracted" is the shape of that mistake.
 */
export type DocumentExtraction =
  /** Dropped documents are never offered extraction, matching the server:
   *  extract-all excludes them, so a control here would offer an action the
   *  bulk path has already decided against. */
  | { readonly kind: 'dropped' }
  | { readonly kind: 'running' }
  | { readonly kind: 'queued' }
  | { readonly kind: 'failed'; readonly detail: string | null }
  | { readonly kind: 'extracted' }
  | { readonly kind: 'idle' }

/** Whether this row's control should be pressable. Derived rather than stored,
 *  so "may I press it" and "what does it say" cannot disagree. */
export const canExtract = (state: DocumentExtraction): boolean =>
  state.kind === 'idle' || state.kind === 'failed'

/** The order of these tests is the design, and each one is load-bearing.
 *
 * Dropped first: it is a property of the document rather than of the queue,
 * and a dropped document that somehow reached the queue still must not offer
 * the control. Running and queued next, so a *re*-extraction of an already
 * extracted document reports what is happening now rather than how it stood
 * before -- the same last-write-wins rule `byTopic` documents for dispatches.
 * Failure before success, because a failure is the more recent account and is
 * the one with no other record of itself.
 *
 * A `done` outcome counts as extracted even when the row still says otherwise:
 * `extracted` comes from the corpus projection and the queue answers from
 * memory, so between an extraction finishing and its projection catching up
 * the flag is stale by a moment. Trusting only the flag would offer "Extract"
 * on a document that had just been extracted.
 */
export const documentExtraction = (
  document: DocumentSummary,
  board: ExtractionQueueBoard,
): DocumentExtraction => {
  if (isDropped(document)) return { kind: 'dropped' }
  if (board.running === document.sourceId) return { kind: 'running' }
  if (board.queued.includes(document.sourceId)) return { kind: 'queued' }
  const outcome = board.finished.find((row) => row.sourceId === document.sourceId)
  if (outcome?.status === 'failed') return { kind: 'failed', detail: outcome.detail }
  if (document.extracted || outcome?.status === 'done') return { kind: 'extracted' }
  return { kind: 'idle' }
}

/** How many documents "extract all unextracted" would actually take on.
 *
 * Counted here rather than read from the server so the header can say a number
 * before anything is pressed. It is an estimate of the server's own set and is
 * allowed to differ: the server recomputes at press time, and the honest
 * report afterwards is the count the 202 returns, not this one.
 */
export const unextractedCount = (
  documents: readonly DocumentSummary[],
  board: ExtractionQueueBoard,
): number => documents.filter((document) => canExtract(documentExtraction(document, board))).length

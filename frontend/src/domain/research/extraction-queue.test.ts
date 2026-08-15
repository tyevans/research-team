import { expect, it } from 'vitest'

import type { DocumentSummary } from './document.ts'
import { SourceId } from '../shared/identifier.ts'
import {
  canExtract,
  documentExtraction,
  emptyExtractionQueue,
  unextractedCount,
  type ExtractionQueueBoard,
} from './extraction-queue.ts'

const doc = (over: Partial<DocumentSummary> = {}): DocumentSummary => ({
  sourceId: SourceId('s1'),
  charCount: 10,
  sha256: 'deadbeef',
  uri: null,
  title: null,
  publishedAt: null,
  note: null,
  droppedReason: null,
  extracted: false,
  ...over,
})

const board = (over: Partial<ExtractionQueueBoard> = {}): ExtractionQueueBoard => ({
  ...emptyExtractionQueue,
  ...over,
})

it('never offers extraction on a dropped document, whatever the queue says', () => {
  // Dropped wins over every queue state, including one the document should not
  // be in: the server excludes dropped documents from extract-all, so an
  // offer here would be an action the bulk path has already decided against.
  const dropped = doc({ droppedReason: 'paywalled' })
  expect(documentExtraction(dropped, board({ running: SourceId('s1') })).kind).toBe('dropped')
  expect(canExtract(documentExtraction(dropped, emptyExtractionQueue))).toBe(false)
})

/** The precedence the row's report turns on, and the only place it is pinned.
 *
 * A re-extraction of an already extracted document reports what is happening
 * now rather than how it stood before — the same last-write-wins rule
 * `byTopic` documents for dispatches. Reverting `documentExtraction` to test
 * `document.extracted` before the queue fails here and nowhere else, which is
 * why this is a test rather than only a comment. */
it('reports a running re-extraction rather than the older success', () => {
  const extracted = doc({ extracted: true })
  expect(documentExtraction(extracted, board({ running: SourceId('s1') })).kind).toBe('running')
  expect(documentExtraction(extracted, board({ queued: [SourceId('s1')] })).kind).toBe('queued')
})

it('reports a failure over an older success, and carries its detail', () => {
  // The failure is the more recent account and is the one with no other record
  // of itself anywhere -- nothing durable notes that an extraction was even
  // requested. Losing it here means the reader is never told why.
  const state = documentExtraction(
    doc({ extracted: true }),
    board({
      finished: [
        {
          sourceId: SourceId('s1'),
          status: 'failed',
          detail: 'context length exceeded',
          entities: null,
          relationships: null,
        },
      ],
    }),
  )
  expect(state).toEqual({ kind: 'failed', detail: 'context length exceeded' })
  // Retryable: a failure is exactly the state a second press can change.
  expect(canExtract(state)).toBe(true)
})

it('counts a just-finished document as extracted before its projection catches up', () => {
  // `extracted` comes from the corpus projection and the queue answers from
  // memory, so between an extraction finishing and the projection catching up
  // the flag is stale by a moment. Trusting only the flag would offer
  // "Extract" on a document that had just been extracted.
  const rows = [doc({ sourceId: SourceId('s1') }), doc({ sourceId: SourceId('s2') })]
  const withDone = board({
    finished: [
      {
        sourceId: SourceId('s1'),
        status: 'done',
        detail: null,
        entities: 4,
        relationships: 2,
      },
    ],
  })
  expect(documentExtraction(rows[0]!, withDone).kind).toBe('extracted')
  expect(unextractedCount(rows, withDone)).toBe(1)
})

it('leaves nothing to extract when everything is extracted, queued or dropped', () => {
  const rows = [
    doc({ sourceId: SourceId('s1'), extracted: true }),
    doc({ sourceId: SourceId('s2') }),
    doc({ sourceId: SourceId('s3'), droppedReason: 'superseded' }),
  ]
  expect(unextractedCount(rows, board({ queued: [SourceId('s2')] }))).toBe(0)
})

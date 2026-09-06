import { expect, it } from 'vitest'

import { derivedSources, type MediaSummary, type TextSummary } from './document.ts'
import { SourceId } from '../shared/identifier.ts'
import {
  canExtract,
  canPerceive,
  documentExtraction,
  emptyExtractionQueue,
  mediaPerception,
  unextractedCount,
  unperceivedCount,
  type ExtractionQueueBoard,
} from './extraction-queue.ts'

const doc = (over: Partial<TextSummary> = {}): TextSummary => ({
  sourceId: SourceId('s1'),
  kind: 'text',
  charCount: 10,
  derivedFrom: null,
  degradations: [],
  sha256: 'deadbeef',
  uri: null,
  title: null,
  publishedAt: null,
  note: null,
  fetchedAt: null,
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

it('never offers extraction on media, and does not count it as unextracted', () => {
  // The server's `_unextracted` counts `kind == "text"` rows only, so a media
  // row left `idle` here would put a pressable "Extract" on a row extract-all
  // has already decided against, and inflate the count on the button beside
  // it. Removing the `kind === 'media'` test in `documentExtraction` fails
  // both assertions.
  const video = {
    sourceId: SourceId('m1'),
    kind: 'media',
    mediaType: 'video/mp4',
    byteCount: 12,
    sha256: 'deadbeef',
    uri: null,
    title: null,
    publishedAt: null,
    note: null,
    fetchedAt: null,
    droppedReason: null,
    extracted: false,
  } as const

  const state = documentExtraction(video, emptyExtractionQueue)
  expect(state.kind).toBe('unextractable')
  expect(canExtract(state)).toBe(false)
  expect(unextractedCount([video, doc({ sourceId: SourceId('s1') })], emptyExtractionQueue)).toBe(1)
})

const video = (over: Partial<MediaSummary> = {}): MediaSummary => ({
  sourceId: SourceId('m1'),
  kind: 'media',
  mediaType: 'video/mp4',
  byteCount: 12,
  sha256: 'deadbeef',
  uri: null,
  title: null,
  publishedAt: null,
  note: null,
  fetchedAt: null,
  droppedReason: null,
  extracted: false,
  ...over,
})

/** A medium in the shared queue, which is the whole of B94's third state.
 *
 * `perceive` enqueues under the medium's own id and extraction enqueues under
 * the derived one, so one board answers both questions without collision --
 * and this is the only place that split is pinned. Deleting the
 * `board.running` test in `mediaPerception` fails the first assertion; making
 * it consult the derived id instead fails the last.
 */
it('reads a transcription off the queue under the medium’s own id', () => {
  expect(mediaPerception(video(), board({ running: SourceId('m1') })).kind).toBe('transcribing')
  expect(mediaPerception(video(), board({ queued: [SourceId('m1')] })).kind).toBe('queued')
  expect(mediaPerception(video(), emptyExtractionQueue).kind).toBe('idle')

  // The derived text source queueing for *extraction* is a different row's
  // state and must not surface on the medium: this is the collision the id
  // split exists to prevent.
  expect(mediaPerception(video(), board({ running: SourceId('m1#perceived') })).kind).toBe('idle')
})

/** Running and queued beat any past outcome, matching `documentExtraction`: a
 *  medium being transcribed again reports what is happening now rather than
 *  how the last attempt went. Fails if the `finished` lookup is moved above
 *  the queue tests. */
it('reports a running transcription over the last failed one', () => {
  const failed = {
    sourceId: SourceId('m1'),
    status: 'failed',
    detail: 'ffmpeg exited 1',
    entities: null,
    relationships: null,
  } as const

  expect(mediaPerception(video(), board({ finished: [failed] }))).toEqual({
    kind: 'failed',
    detail: 'ffmpeg exited 1',
  })
  expect(
    mediaPerception(video(), board({ running: SourceId('m1'), finished: [failed] })).kind,
  ).toBe('transcribing')
  // Pressable again only where a press would do something -- the same rule
  // `canExtract` states for the extract control.
  expect(canPerceive(mediaPerception(video(), board({ finished: [failed] })))).toBe(true)
  expect(canPerceive(mediaPerception(video(), board({ running: SourceId('m1') })))).toBe(false)
})

/** A text row's place in this queue is its extraction, and reporting it as a
 *  transcription would be the mirror of the mistake `documentExtraction`'s
 *  media test guards against. Fails if the `kind` check is dropped. */
it('says nothing about a text row, which is in this queue to be extracted', () => {
  expect(
    mediaPerception(doc({ sourceId: SourceId('s1') }), board({ running: SourceId('s1') })),
  ).toEqual({ kind: 'idle' })
})

it('leaves nothing to extract when everything is extracted, queued or dropped', () => {
  const rows = [
    doc({ sourceId: SourceId('s1'), extracted: true }),
    doc({ sourceId: SourceId('s2') }),
    doc({ sourceId: SourceId('s3'), droppedReason: 'superseded' }),
  ]
  expect(unextractedCount(rows, board({ queued: [SourceId('s2')] }))).toBe(0)
})

/** B94's batch count, and the three exclusions it has to make.
 *
 * Written as one case per exclusion in one test rather than three tests,
 * because what makes the count correct is that all three hold at once: a
 * corpus with a candidate, a dropped medium and a transcribed one is the only
 * arrangement that separates this implementation from the two plausible wrong
 * ones -- counting every medium, and counting every medium the board is not
 * holding.
 *
 * Each assertion fails on its own clause: drop the `isDropped` test and the
 * dropped medium counts; drop the `derived` test and the transcribed one does;
 * drop `canPerceive` and the queued one does.
 */
it('counts the media a transcribe-all would take on, and no others', () => {
  const candidate = video({ sourceId: SourceId('fresh') })
  const dropped = video({ sourceId: SourceId('dropped'), droppedReason: 'off topic' })
  const transcribed = video({ sourceId: SourceId('read') })
  const queued = video({ sourceId: SourceId('waiting') })
  const rows = [candidate, dropped, transcribed, queued, doc({ sourceId: SourceId('s1') })]
  // The map `derivedSources` builds over the whole corpus: one medium has a
  // transcript, and that is what takes it out of the set.
  const derived = new Map([['read', SourceId('read#perceived')]])

  expect(unperceivedCount(rows, derived, board({ queued: [SourceId('waiting')] }))).toBe(1)

  // And with nothing excluded by the board, the two live candidates are the
  // fresh one and the one that was merely waiting.
  expect(unperceivedCount(rows, derived, emptyExtractionQueue)).toBe(2)
  // A text document is never a candidate, whatever the board says.
  expect(
    unperceivedCount([doc({ sourceId: SourceId('s1') })], new Map(), emptyExtractionQueue),
  ).toBe(0)
})

/** **A dropped transcript still counts its medium as transcribed.**
 *
 * The subtle half of `MediaPerceiver.unperceived`'s rule, and the one a future
 * reader is most likely to "fix": re-reading such a medium supersedes the
 * derived source, which erases its `dropped_reason` and returns the text to
 * chunking and extraction -- undoing an exclusion nobody asked to undo.
 *
 * `derivedSources` already builds the map that way, over dropped rows
 * included; this asserts the count consumes it rather than re-deriving a
 * narrower set of its own.
 */
it('does not offer to re-transcribe a medium whose transcript was dropped', () => {
  const medium = video({ sourceId: SourceId('m9') })
  const derived = derivedSources([
    medium,
    doc({ sourceId: SourceId('m9#perceived'), derivedFrom: 'm9', droppedReason: 'noisy' }),
  ])

  expect(unperceivedCount([medium], derived, emptyExtractionQueue)).toBe(0)
})

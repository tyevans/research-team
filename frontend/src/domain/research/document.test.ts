import { expect, it } from 'vitest'

import { SourceId } from '../shared/identifier.ts'
import { documentLabel, formatBytes, type MediaSummary } from './document.ts'

const media = (over: Partial<MediaSummary> = {}): MediaSummary => ({
  sourceId: SourceId('m1'),
  kind: 'media',
  mediaType: 'video/mp4',
  byteCount: 12_500_000,
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

// Decimal units, matching what an operating system reports for the same file:
// a 12.5 MB recording called "11.9 MiB" here would look like a different one.
// The bytes-under-1000 case is the only one with no decimal, because "0.5 kB"
// for 500 bytes is less precise than the number itself.
it.each([
  [0, '0 B'],
  [999, '999 B'],
  [1000, '1.0 kB'],
  [12_500_000, '12.5 MB'],
  [1_000_000_000, '1.0 GB'],
  // Past the last unit it keeps counting in that unit rather than falling off
  // the end of the table -- the alternative is `undefined` in a row.
  [5_000_000_000_000_000, '5000.0 TB'],
])('formats %i bytes as %s', (bytes, expected) => {
  expect(formatBytes(bytes)).toBe(expected)
})

it('labels a media source the same way it labels a document', () => {
  // Deriving the label twice is how the list and the reader end up disagreeing
  // about what a titleless source is called -- and a media source is titleless
  // exactly as often as a text one. Fails if `documentLabel` is narrowed back
  // to text.
  expect(documentLabel(media({ title: 'The keynote' }))).toBe('The keynote')
  expect(documentLabel(media())).toBe('m1')
})

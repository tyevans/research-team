import { expect, it } from 'vitest'

import { passageStart } from './snippet.ts'

it('drops the partial line a chunk boundary cut mid-sentence', () => {
  const chunk = 'anded down by the pontifices, which Livy treats as\n## Prodigies\n\nMajor omens.'
  expect(passageStart(chunk)).toBe('## Prodigies\n\nMajor omens.')
})

it('falls through to a sentence boundary when the chunk has no line break', () => {
  // The case the newline rule cannot serve: prose long enough to fill a chunk
  // without a single break, which is the ordinary shape of a scraped article
  // body once the markdown has been flattened.
  const chunk = 'aught by Cornell. Livy presents these as signs of failure in Roman religio.'
  expect(passageStart(chunk)).toBe('Livy presents these as signs of failure in Roman religio.')
})

it('keeps a chunk that has no boundary at all rather than blanking it', () => {
  // Would fail with the input returned as `''`: showing a partial sentence is
  // a poor result, showing an empty mention is a broken one.
  const chunk = 'a single unbroken clause with nowhere to cut'
  expect(passageStart(chunk)).toBe(chunk)
})

it('keeps a chunk whose only newline is trailing', () => {
  // The newline rule matches here and leaves nothing behind, so it must fall
  // through rather than win. Passes with the emptiness guard removed only if
  // the sentence rule happens to fire, which it does not for this input.
  expect(passageStart('nothing after this newline\n')).toBe('nothing after this newline\n')
})

it('keeps a chunk whose only sentence end is final', () => {
  expect(passageStart('one whole sentence and no more. ')).toBe('one whole sentence and no more. ')
})

it('returns the empty string unchanged', () => {
  expect(passageStart('')).toBe('')
})

it('prefers the newline even when a sentence ends earlier', () => {
  // Order matters and is not incidental: chunk text is markdown, so a newline
  // is a block boundary and lands on something that renders as a unit, where
  // the earlier sentence end would cut into the middle of one.
  const chunk = 'tail of a sentence. And more of the same line\nA new block begins here.'
  expect(passageStart(chunk)).toBe('A new block begins here.')
})

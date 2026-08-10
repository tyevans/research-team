import { expect, it } from 'vitest'

import { statusLabel, statusTone } from './status.ts'

/** The vocabulary rules, which are the only part of this contract that is
 *  genuinely domain logic rather than markup.
 *
 *  All of these are cheap and none is decorative: each one either replaces a
 *  rule written three times in the views, or encodes a distinction a report
 *  says the console currently gets wrong.
 */

it('shows no underscores to a person', () => {
  expect(statusLabel('not_pursuing')).toBe('not pursuing')
})

it('replaces every underscore, not only the first', () => {
  // The three call sites this replaces all use `.replace('_', ' ')`, which
  // with a string pattern replaces one occurrence. No status shipped today has
  // two underscores, so the bug is currently invisible — which is exactly why
  // it survives. `awaiting_human_review` is what it looks like when it stops
  // being invisible.
  expect(statusLabel('awaiting_human_review')).toBe('awaiting human review')
})

it('leaves a single-word status alone', () => {
  expect(statusLabel('open')).toBe('open')
})

it('spells a gate as a pause rather than as an identifier', () => {
  // C-F46. "human gate" is the machine's word; a reader needs to know the run
  // is waiting for them.
  expect(statusLabel('human_gate')).toBe('needs a person')
})

it('gives the done tone to queue_empty and to no other ending', () => {
  // C-F26/C-F27: six run endings, and five of them stopped for a reason
  // somebody has to look at. A green tick on `budget_exhausted` tells a reader
  // the work finished when it ran out of money.
  expect(statusTone('queue_empty')).toBe('good')
  expect(statusTone('budget_exhausted')).toBe('bad')
  expect(statusTone('stalled')).toBe('bad')
  expect(statusTone('error')).toBe('bad')
})

it('files a human gate as held rather than as a failure', () => {
  // C-F46 again, from the tone side: the system is doing what it was told.
  expect(statusTone('human_gate')).toBe('held')
  expect(statusTone('human_gate')).not.toBe('bad')
})

it('has no opinion about a status it has never heard of', () => {
  // Neither throwing nor painting it red. A backend that grew a status this
  // build does not know should not crash a queue, and should not be reported
  // as broken either — `neutral` is the honest answer.
  expect(statusTone('a_status_from_a_newer_backend')).toBe('neutral')
  expect(statusLabel('a_status_from_a_newer_backend')).toBe('a status from a newer backend')
})

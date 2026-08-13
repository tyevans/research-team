/** Folding a stream of ask events into a transcript.
 *
 * Streaming order is where this goes subtly wrong, so the order cases are the
 * ones worth having: a delta before its turn exists, an answer that arrives
 * after deltas already rendered the same words, an error mid-stream.
 */
import { expect, it } from 'vitest'

import { applyEvent, asked, type AskTranscript } from './conversation.ts'

const open = (question = 'what did we find?'): AskTranscript => asked([], question)

it('opens an unsettled turn holding the question', () => {
  const [turn] = open()

  expect(turn.question).toBe('what did we find?')
  expect(turn.answer).toBe('')
  expect(turn.settled).toBe(false)
})

it('accumulates deltas into the open turn', () => {
  let transcript = open()

  transcript = applyEvent(transcript, { type: 'delta', messageId: 'm1', text: 'two ' })
  transcript = applyEvent(transcript, { type: 'delta', messageId: 'm1', text: 'papers' })

  expect(transcript[0].answer).toBe('two papers')
})

it('replaces the accumulated deltas with the final answer rather than appending', () => {
  let transcript = open()
  transcript = applyEvent(transcript, { type: 'delta', messageId: 'm1', text: 'two papers' })

  transcript = applyEvent(transcript, { type: 'answer', text: 'two papers', citations: [] })

  // Appending would render the answer twice: the deltas are the same words.
  expect(transcript[0].answer).toBe('two papers')
  expect(transcript[0].settled).toBe(true)
})

it('keeps citations with the turn they belong to', () => {
  let transcript = open()

  transcript = applyEvent(transcript, {
    type: 'answer',
    text: 'two papers',
    citations: [{ kind: 'source', id: 's1' }],
  })

  expect(transcript[0].citations).toEqual([{ kind: 'source', id: 's1' }])
})

it('records activity in arrival order', () => {
  let transcript = open()

  transcript = applyEvent(transcript, {
    type: 'message', messageId: 'm1', kind: 'tool', payload: { name: 'read_source' }, isError: false,
  })

  expect(transcript[0].activity).toEqual([
    { messageId: 'm1', kind: 'tool', payload: { name: 'read_source' }, isError: false },
  ])
})

it('settles a turn on error and keeps the reason', () => {
  let transcript = open()

  transcript = applyEvent(transcript, { type: 'error', detail: 'model fell over' })

  expect(transcript[0].error).toBe('model fell over')
  expect(transcript[0].settled).toBe(true)
})

it('leaves a settled turn alone when a late event arrives', () => {
  let transcript = open()
  transcript = applyEvent(transcript, { type: 'answer', text: 'done', citations: [] })

  transcript = applyEvent(transcript, { type: 'delta', messageId: 'm1', text: 'late' })

  // A late delta belongs to nothing; writing it into the settled turn would
  // corrupt an answer the reader has already read.
  expect(transcript[0].answer).toBe('done')
})

it('ignores an event with no turn open at all', () => {
  const transcript = applyEvent([], { type: 'delta', messageId: 'm1', text: 'orphan' })

  expect(transcript).toEqual([])
})

it('appends a second turn without disturbing the first', () => {
  let transcript = open()
  transcript = applyEvent(transcript, { type: 'answer', text: 'two papers', citations: [] })

  transcript = asked(transcript, 'and the second?')

  expect(transcript).toHaveLength(2)
  expect(transcript[0].answer).toBe('two papers')
  expect(transcript[1].settled).toBe(false)
})

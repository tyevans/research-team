import { describe, expect, it } from 'vitest'

import { MessageId, SessionId } from '../shared/identifier.ts'
import {
  activityBody,
  activityEntries,
  emptyActivity,
  putActivity,
  type ActivityEntry,
} from './activity.ts'

const entry = (id: string, over: Partial<ActivityEntry> = {}): ActivityEntry => ({
  messageId: MessageId(id),
  sessionId: SessionId('s1'),
  kind: 'delta',
  text: null,
  payload: null,
  ...over,
})

describe('the activity buffer', () => {
  it('keeps arrival order', () => {
    let buffer = emptyActivity()
    buffer = putActivity(buffer, entry('b'))
    buffer = putActivity(buffer, entry('a'))
    expect(activityEntries(buffer).map((e) => e.messageId)).toEqual(['b', 'a'])
  })

  it('replaces rather than appends for the same message', () => {
    // Each frame's text is the full prose so far, not an increment — the
    // accumulation happens server-side, on the side that has to answer the
    // catch-up route anyway.
    let buffer = emptyActivity()
    buffer = putActivity(buffer, entry('a', { text: 'th' }))
    buffer = putActivity(buffer, entry('a', { text: 'thinking' }))

    expect(activityEntries(buffer)).toHaveLength(1)
    expect(activityEntries(buffer)[0]?.text).toBe('thinking')
  })

  it("keeps a message's position when a later frame replaces it", () => {
    let buffer = emptyActivity()
    buffer = putActivity(buffer, entry('a', { text: 'one' }))
    buffer = putActivity(buffer, entry('b', { text: 'two' }))
    buffer = putActivity(buffer, entry('a', { text: 'one, revised' }))
    expect(activityEntries(buffer).map((e) => e.messageId)).toEqual(['a', 'b'])
  })

  it('does not mutate the buffer it was given', () => {
    const before = putActivity(emptyActivity(), entry('a'))
    putActivity(before, entry('b'))
    expect(before.size).toBe(1)
  })
})

describe('activityBody', () => {
  it('prefers the delta accumulator', () => {
    expect(activityBody(entry('a', { text: 'so far…' }))).toBe('so far…')
  })

  it('reads a whole message out of the nesting it actually arrives in', () => {
    // A whole-message entry clears `text` and populates `payload`, whose
    // content sits under `data` — reading `payload.content` is always undefined.
    expect(
      activityBody(entry('a', { payload: { type: 'ai', data: { content: 'Done.' } } })),
    ).toBe('Done.')
  })

  it('summarises a tool-calling message the way the timeline row will', () => {
    expect(
      activityBody(
        entry('a', {
          payload: { data: { tool_calls: [{ name: 'Read' }, { name: 'Grep' }] } },
        }),
      ),
    ).toBe('→ Read, Grep')
  })

  it('names an unnamed call rather than rendering undefined', () => {
    expect(activityBody(entry('a', { payload: { data: { tool_calls: [{}] } } }))).toBe('→ ?')
  })

  it('is empty for a frame carrying neither', () => {
    expect(activityBody(entry('a'))).toBe('')
  })
})

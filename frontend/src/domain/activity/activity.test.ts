import { describe, expect, it } from 'vitest'

import { MessageId, SessionId } from '../shared/identifier.ts'
import {
  ACTIVITY_SUMMARY_LIMIT,
  activityBody,
  activityEntries,
  activityMessage,
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
    expect(activityBody(entry('a', { payload: { type: 'ai', data: { content: 'Done.' } } }))).toBe(
      'Done.',
    )
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

  it('says what each call acted on, not only which tool ran', () => {
    // The bubble previews the row the message is about to become, and that row
    // carries the argument too — a preview that dropped it would redraw the
    // moment the turn committed.
    expect(
      activityBody(
        entry('a', {
          payload: {
            data: {
              tool_calls: [
                { name: 'Read', args: { path: '/a.md', limit: 20 } },
                { name: 'Grep', args: { pattern: 'kettle' } },
              ],
            },
          },
        }),
      ),
    ).toBe('→ Read(path=/a.md  +1), Grep(pattern=kettle)')
  })

  it('cannot be widened without bound by an enormous argument', () => {
    // `remember` takes 20,000 characters of `text`. The bubble is prose-height,
    // not a scroll region; the full arguments live behind the transcript's
    // per-call disclosure.
    const calls = Array.from({ length: 12 }, () => ({
      name: 'remember',
      args: { text: 'x'.repeat(20_000) },
    }))
    const body = activityBody(entry('a', { payload: { data: { tool_calls: calls } } }))
    expect(body.length).toBeLessThanOrEqual(ACTIVITY_SUMMARY_LIMIT)
    expect(body.endsWith('…')).toBe(true)
  })

  it('names an unnamed call rather than rendering undefined', () => {
    expect(activityBody(entry('a', { payload: { data: { tool_calls: [{}] } } }))).toBe('→ ?')
  })

  it('is empty for a frame carrying neither', () => {
    expect(activityBody(entry('a'))).toBe('')
  })
})

describe('activityMessage', () => {
  it('lifts the artifact and the tool name out of the payload', () => {
    // A provisional entry and the message it becomes are the same langchain
    // payload, so one component can draw both. Two components that agree are
    // two components that will stop agreeing, and the drift would be visible
    // as every card in a turn changing at the instant it commits.
    const message = activityMessage(
      entry('a', {
        payload: {
          data: {
            name: 'search_sources',
            artifact: { shape: 'hit_list', version: 1 },
            content: '19 match(es)',
          },
        },
      }),
    )
    expect(message.name).toBe('search_sources')
    expect(message.artifact).toEqual({ shape: 'hit_list', version: 1 })
    expect(message.role).toBe('tool')
  })

  it('carries the fallback text as content for an entry with no artifact', () => {
    // Already flattened, so a bubble with no artifact renders exactly what it
    // renders today rather than whatever a second flattener would produce.
    const message = activityMessage(entry('a', { text: 'still writing' }))
    expect(message.content).toBe('still writing')
    expect(message.artifact).toBeNull()
  })

  it('reads an errored tool result', () => {
    const message = activityMessage(entry('a', { payload: { data: { status: 'error' } } }))
    expect(message.isError).toBe(true)
  })
})

import { describe, expect, it } from 'vitest'

import { decodeFrame } from './event-stream.ts'

const frame = (payload: unknown) => decodeFrame(JSON.stringify(payload))

/** Three channels ride one connection, and only one of them is the durable log.
 *
 * Getting this wrong is not a rendering bug: an approval frame mistaken for a
 * log entry inserts a phantom row, and a log frame mistaken for anything else
 * loses an event. */
describe('decodeFrame', () => {
  it('reads an ordinary log frame', () => {
    const decoded = frame({
      session_id: 's1',
      index: 12,
      type: 'FileWritten',
      occurred_at: '2026-01-01T00:00:00Z',
      summary: '/a.md',
      path: '/a.md',
    })
    expect(decoded).toMatchObject({
      kind: 'log',
      sessionId: 's1',
      entry: { index: 12, type: 'FileWritten', path: '/a.md' },
    })
  })

  it('reads an approval request as an approval, not as a log entry', () => {
    const decoded = frame({
      type: 'ApprovalRequested',
      id: 'a1',
      session_id: 's1',
      tool_name: 'fetch',
      args: { url: 'https://example.com' },
    })
    expect(decoded?.kind).toBe('approvalRequested')
  })

  it('reads a settlement, which carries only the two ids', () => {
    expect(frame({ type: 'ApprovalSettled', id: 'a1', session_id: 's1' })).toEqual({
      kind: 'approvalSettled',
      sessionId: 's1',
      approvalId: 'a1',
    })
  })

  it('reads provisional activity as its own channel', () => {
    const decoded = frame({
      type: 'TurnActivity',
      session_id: 's1',
      message_id: 'm1',
      kind: 'delta',
      text: 'thinking…',
    })
    expect(decoded).toMatchObject({ kind: 'activity', entry: { messageId: 'm1' } })
  })

  it('routes an extraction frame without decoding it', () => {
    // It has no index, so before it had a case of its own it fell through to
    // the log branch and was dropped for being unplaceable — the pane would
    // never have received a frame. The payload rides through unmapped: the
    // per-project store folds it, and only that store knows which project is
    // on screen.
    const decoded = frame({ type: 'Extraction', project_id: 'p1', source_id: 'notes' })
    expect(decoded).toMatchObject({ kind: 'extraction' })
  })

  it('drops a log frame with no index rather than guessing a position', () => {
    // Inserting a row at the wrong point is worse than dropping a frame a
    // reconnect will replay correctly.
    expect(
      frame({ session_id: 's1', type: 'FileWritten', occurred_at: '2026-01-01T00:00:00Z' }),
    ).toBeNull()
  })

  it('drops malformed json without taking the connection down', () => {
    expect(decodeFrame('{not json')).toBeNull()
    expect(decodeFrame('')).toBeNull()
  })

  it('drops a frame whose shape does not match its own type', () => {
    expect(frame({ type: 'ApprovalRequested' })).toBeNull()
    expect(frame({ type: 'TurnActivity', session_id: 's1' })).toBeNull()
  })

  it('carries a cancellation flag through, since it is not a failure', () => {
    const decoded = frame({
      session_id: 's1',
      index: 4,
      type: 'TurnFailed',
      occurred_at: '2026-01-01T00:00:00Z',
      cancelled: true,
    })
    expect(decoded).toMatchObject({ entry: { cancelled: true } })
  })
})

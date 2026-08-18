import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import type { InteractionEvent } from '@application/ports/interaction-log.ts'

import { FLUSH_AT, FLUSH_INTERVAL_MS, createEmitter } from './emitter.ts'

const INSTALL = '22222222-2222-2222-2222-222222222222'
const SESSION = '11111111-1111-1111-1111-111111111111'

const sink = () => {
  const sent: InteractionEvent[][] = []
  const beaconed: InteractionEvent[][] = []
  return {
    sent,
    beaconed,
    send: vi.fn(async (events: readonly InteractionEvent[]) => {
      sent.push([...events])
    }),
    sendOnUnload: vi.fn((events: readonly InteractionEvent[]) => {
      beaconed.push([...events])
    }),
  }
}

const emitter = (transport = sink(), clock = 1_000) =>
  createEmitter({
    sink: transport,
    now: () => clock,
    installId: INSTALL,
    browserSessionId: SESSION,
  })

beforeEach(() => vi.useFakeTimers())
afterEach(() => vi.useRealTimers())

it('holds an event rather than sending it immediately', () => {
  /** One POST per click would be noisy in the network panel this console is
   *  debugged in, and would lose ordering under concurrency. */
  const transport = sink()
  const log = emitter(transport)

  log.record('ViewEntered', { params: {} })

  expect(transport.send).not.toHaveBeenCalled()
  expect(log.pending()).toBe(1)
})

it('flushes on the timer', async () => {
  const transport = sink()
  const log = emitter(transport)
  log.record('ViewEntered', { params: {} })

  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS)

  expect(transport.sent).toHaveLength(1)
  expect(transport.sent[0]).toHaveLength(1)
  expect(log.pending()).toBe(0)
})

it('does not flush an empty buffer', async () => {
  const transport = sink()
  emitter(transport)

  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS * 3)

  expect(transport.send).not.toHaveBeenCalled()
})

it('flushes immediately once the buffer reaches its cap', async () => {
  const transport = sink()
  const log = emitter(transport)

  for (let n = 0; n < FLUSH_AT; n += 1) log.record('AttentionLost')
  await vi.advanceTimersByTimeAsync(0)

  expect(transport.sent).toHaveLength(1)
  expect(transport.sent[0]).toHaveLength(FLUSH_AT)
})

it('numbers events in the order they happened, not the order they are sent', async () => {
  /** seq is the ordering authority. Assigned at record time so that a
   *  reordered batch, a racing flush, or a moved system clock cannot disturb
   *  it. */
  const transport = sink()
  const log = emitter(transport)

  log.record('ViewEntered', { params: {} })
  log.record('EntityOpened', { entity_id: 'a', source: 'graph' })
  log.record('EntityOpened', { entity_id: 'b', source: 'search' })
  await log.flush()

  expect(transport.sent[0]?.map((event) => event.seq)).toEqual([1, 2, 3])
})

it('keeps numbering across flushes', async () => {
  const transport = sink()
  const log = emitter(transport)

  log.record('AttentionLost')
  await log.flush()
  log.record('AttentionRegained')
  await log.flush()

  expect(transport.sent[1]?.[0]?.seq).toBe(2)
})

it('stamps every event with the identity and the current context', async () => {
  const transport = sink()
  const log = emitter(transport)
  log.setContext({ view: 'project/timeline', projectId: 'p-1', sessionId: null })

  log.record('ViewEntered', { params: {} })
  await log.flush()

  const event = transport.sent[0]?.[0]
  expect(event).toMatchObject({
    kind: 'ViewEntered',
    install_id: INSTALL,
    browser_session_id: SESSION,
    view: 'project/timeline',
    project_id: 'p-1',
    session_id: null,
  })
})

it('carries the kind-specific payload through untouched', async () => {
  const transport = sink()
  const log = emitter(transport)

  log.record('SearchPerformed', { query_text: 'tetrarchy', result_count: 0 })
  await log.flush()

  expect(transport.sent[0]?.[0]?.payload).toEqual({
    query_text: 'tetrarchy',
    result_count: 0,
  })
})

it('empties the buffer before awaiting the send, so a slow flush cannot double-send', async () => {
  /** Fails with the buffer cleared after the await: the timer fires again
   *  while the first send is in flight and the same events go twice.
   *  Idempotent server-side on (browser_session_id, seq), so the symptom
   *  would be wasted requests rather than duplicate rows -- which is
   *  precisely the kind of defect nothing would report. */
  let release = () => {}
  const transport = {
    ...sink(),
    send: vi.fn(() => new Promise<void>((resolve) => (release = resolve))),
  }
  const log = emitter(transport)
  log.record('AttentionLost')

  const flushing = log.flush()
  expect(log.pending()).toBe(0)
  release()
  await flushing

  expect(transport.send).toHaveBeenCalledTimes(1)
})

it('beacons the buffer on unload rather than posting it', () => {
  /** A batch dropped at tab close removes the end of every session, which is
   *  where friction lives. */
  const transport = sink()
  const log = emitter(transport)
  log.record('ViewExited', { dwell_ms: 4_000, hidden_ms: 0 })

  log.flushOnUnload()

  expect(transport.sendOnUnload).toHaveBeenCalledTimes(1)
  expect(transport.beaconed[0]).toHaveLength(1)
  expect(transport.send).not.toHaveBeenCalled()
  expect(log.pending()).toBe(0)
})

it('stops flushing once stopped', async () => {
  const transport = sink()
  const log = emitter(transport)
  log.record('AttentionLost')

  log.stop()
  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS * 3)

  expect(transport.send).not.toHaveBeenCalled()
})

it('flushes again after being restarted', async () => {
  /** `stop()` was terminal: the interval was only ever created in
   *  `createEmitter`, so an emitter that outlived a stop -- which is exactly
   *  what a React effect cleanup plus StrictMode's remount produces -- never
   *  flushed on a timer again. Without `start()` this fails on the first
   *  assertion with 0 sends. */
  const transport = sink()
  const log = emitter(transport)
  log.stop()
  log.start()
  log.record('AttentionLost')
  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS)

  expect(transport.send).toHaveBeenCalledTimes(1)

  // Idempotent: the same effect body runs three times under StrictMode, and a
  // second interval would double every request for the rest of the page load.
  log.start()
  log.record('AttentionLost')
  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS)

  expect(transport.send).toHaveBeenCalledTimes(2)
})

it('survives a sink that rejects', async () => {
  /** A dropped batch must not become an unhandled rejection: main.tsx turns
   *  those into a toast, and telemetry failing is not the user's problem. */
  const transport = { ...sink(), send: vi.fn(() => Promise.reject(new Error('nope'))) }
  const log = emitter(transport)
  log.record('AttentionLost')

  await expect(log.flush()).resolves.toBeUndefined()
})

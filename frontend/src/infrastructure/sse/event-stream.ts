import type {
  EventStream,
  EventStreamListener,
  FeedFrame,
} from '@application/ports/event-stream.ts'
import { isEventIndex } from '@domain/session/event-index.ts'
import { ApprovalId, SessionId } from '@domain/shared/identifier.ts'

import {
  activityFrameDto,
  approvalRequestedFrameDto,
  approvalSettledFrameDto,
  frameEnvelopeDto,
  logFrameDto,
} from '../http/dto.ts'
import { toActivityEntry, toApproval, toLogEntry } from '../http/mappers.ts'

const INITIAL_BACKOFF_MS = 1_000
const MAX_BACKOFF_MS = 30_000
/** How long a connection has to stay up before it counts as healthy. A server
 *  that accepts and immediately drops would otherwise reset the backoff on
 *  every attempt, turning reconnection into a one-per-second reload loop. */
const STABLE_AFTER_MS = 5_000

/** The live feed, as an `EventSource` with reconnection.
 *
 * Reconnection is genuinely the browser's job here and not ours: every frame
 * carries its feed position as an SSE id, and `EventSource` replays the last
 * one in `Last-Event-ID` automatically, so the server resumes from where this
 * client left off and the gap arrives as ordinary events. What this class adds
 * is the backoff, and the one fact the browser cannot tell the application —
 * whether there *was* a cursor to resume from. A connection that dropped before
 * its first frame has none, the server cannot place it, and everything the
 * application holds has to be refetched.
 */
export class SseEventStream implements EventStream {
  private source: EventSource | null = null
  private listener: EventStreamListener | null = null
  private backoff = INITIAL_BACKOFF_MS
  private lastEventId: string | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private stableTimer: ReturnType<typeof setTimeout> | null = null
  private closed = false

  constructor(private readonly url: string = '/api/stream') {}

  connect(listener: EventStreamListener): void {
    this.listener = listener
    this.closed = false
    this.open()
  }

  disconnect(): void {
    this.closed = true
    this.clearTimers()
    this.source?.close()
    this.source = null
    this.listener = null
  }

  private open(): void {
    if (this.closed) return
    const listener = this.listener
    if (!listener) return

    if (typeof EventSource === 'undefined') {
      listener.onConnectionState('down')
      return
    }

    listener.onConnectionState('connecting')
    try {
      this.source = new EventSource(this.url)
    } catch {
      listener.onConnectionState('down')
      this.scheduleReconnect()
      return
    }

    this.source.onopen = () => {
      const reconnected = this.backoff !== INITIAL_BACKOFF_MS
      this.clearStableTimer()
      this.stableTimer = setTimeout(() => {
        this.backoff = INITIAL_BACKOFF_MS
      }, STABLE_AFTER_MS)
      listener.onConnectionState('open')
      if (reconnected) listener.onReconnect(this.lastEventId !== null)
    }

    this.source.onmessage = (message: MessageEvent<string>) => {
      if (message.lastEventId) this.lastEventId = message.lastEventId
      const frame = decodeFrame(message.data)
      if (frame) listener.onFrame(frame)
    }

    this.source.onerror = () => {
      this.source?.close()
      this.source = null
      this.clearStableTimer()
      listener.onConnectionState('down')
      this.scheduleReconnect()
    }
  }

  private scheduleReconnect(): void {
    if (this.closed) return
    const wait = this.backoff
    this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS)
    this.reconnectTimer = setTimeout(() => this.open(), wait)
  }

  private clearTimers(): void {
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer)
    this.reconnectTimer = null
    this.clearStableTimer()
  }

  private clearStableTimer(): void {
    if (this.stableTimer) clearTimeout(this.stableTimer)
    this.stableTimer = null
  }
}

/** A malformed frame is dropped rather than thrown: one bad frame must not take
 *  down a connection every other frame is arriving on correctly.
 *
 *  Dispatch is on `type` because that is genuinely what tells the channels
 *  apart. Approval and activity frames ride this connection and are *not* log
 *  entries -- they carry no feed position, which is why `Last-Event-ID` cannot
 *  replay them and why the application reconciles them separately. */
export const decodeFrame = (data: string): FeedFrame | null => {
  let payload: unknown
  try {
    payload = JSON.parse(data)
  } catch {
    return null
  }

  const envelope = frameEnvelopeDto.safeParse(payload)
  if (!envelope.success) return null

  switch (envelope.data.type) {
    case 'ApprovalRequested': {
      const frame = approvalRequestedFrameDto.safeParse(payload)
      return frame.success ? { kind: 'approvalRequested', approval: toApproval(frame.data) } : null
    }
    case 'ApprovalSettled': {
      const frame = approvalSettledFrameDto.safeParse(payload)
      return frame.success
        ? {
            kind: 'approvalSettled',
            sessionId: SessionId(frame.data.session_id),
            approvalId: ApprovalId(frame.data.id),
          }
        : null
    }
    case 'TurnActivity': {
      const frame = activityFrameDto.safeParse(payload)
      return frame.success ? { kind: 'activity', entry: toActivityEntry(frame.data) } : null
    }
    default: {
      // An ordinary log frame. One without a usable index cannot be placed, and
      // guessing a position would insert a row at the wrong point -- worse than
      // dropping a frame that a reconnect will replay correctly.
      const frame = logFrameDto.safeParse(payload)
      if (!frame.success || !isEventIndex(frame.data.index)) return null
      return {
        kind: 'log',
        sessionId: SessionId(frame.data.session_id),
        entry: toLogEntry(frame.data),
      }
    }
  }
}

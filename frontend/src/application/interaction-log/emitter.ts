/** The buffer between what the user did and the one POST that reports it.
 *
 * Written here rather than taken from a library, and the search that settled
 * that is worth recording: the batch-and-beacon machinery exists only inside
 * full analytics SDKs (PostHog, Snowplow, Rudderstack), each of which brings
 * its own event ontology and a server half this feature does not use. The
 * standalone prior art is patterns over `sendBeacon` and `pagehide`, not
 * packages. Taking one would have meant carrying a large dependency against
 * a bundle budget to use a few percent of it, and bending a vocabulary that
 * was designed deliberately to fit theirs.
 *
 * What is deliberately absent: any durable client-side queue. A crash loses
 * the last few seconds. Spilling to localStorage would spend real complexity
 * protecting data that is droppable by design -- the reason this log has its
 * own store -- and would make late arrival a permanent property that every
 * future reader of the log has to reason about.
 */

import type { InteractionEvent, InteractionSink } from '@application/ports/interaction-log.ts'

export const FLUSH_INTERVAL_MS = 5_000
/** Long enough that a busy minute is a handful of requests, short enough
 *  that a crash loses seconds rather than a session. */

export const FLUSH_AT = 50
/** Flush early at this many, so a burst does not sit in memory for the rest
 *  of the interval. The server accepts 200, leaving room for a page-hide
 *  flush racing a timer flush. */

interface Context {
  view: string
  projectId: string | null
  sessionId: string | null
}

export interface Emitter {
  record(kind: string, payload?: Readonly<Record<string, unknown>>): void
  setContext(context: Partial<Context>): void
  flush(): Promise<void>
  flushOnUnload(): void
  stop(): void
  pending(): number
}

export const createEmitter = ({
  sink,
  now,
  installId,
  browserSessionId,
}: {
  sink: InteractionSink
  now: () => number
  installId: string
  browserSessionId: string
}): Emitter => {
  let buffer: InteractionEvent[] = []
  let seq = 0
  let context: Context = { view: 'home', projectId: null, sessionId: null }
  let timer: ReturnType<typeof setInterval> | null = setInterval(() => {
    void flush()
  }, FLUSH_INTERVAL_MS)

  /** Empties the buffer *before* awaiting, so a flush still in flight when
   *  the timer fires again cannot send the same events twice. Server-side
   *  idempotency on (browser_session_id, seq) means the symptom would be
   *  wasted requests rather than duplicate rows -- a defect nothing reports. */
  const take = (): InteractionEvent[] => {
    const taken = buffer
    buffer = []
    return taken
  }

  const flush = async (): Promise<void> => {
    const batch = take()
    if (batch.length === 0) return
    try {
      await sink.send(batch)
    } catch {
      // Dropped. Never rethrown: `main.tsx` turns an unhandled rejection
      // into a toast, and telemetry failing is not the user's problem.
    }
  }

  return {
    record(kind, payload = {}) {
      seq += 1
      buffer.push({
        kind,
        browser_session_id: browserSessionId,
        install_id: installId,
        seq,
        view: context.view,
        occurred_at: new Date(now()).toISOString(),
        project_id: context.projectId,
        session_id: context.sessionId,
        payload,
      })
      if (buffer.length >= FLUSH_AT) void flush()
    },

    setContext(next) {
      context = { ...context, ...next }
    },

    flush,

    flushOnUnload() {
      const batch = take()
      if (batch.length === 0) return
      sink.sendOnUnload(batch)
    },

    stop() {
      if (timer !== null) {
        clearInterval(timer)
        timer = null
      }
    },

    pending() {
      return buffer.length
    },
  }
}

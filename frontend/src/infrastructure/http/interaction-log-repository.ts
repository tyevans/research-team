import type { InteractionEvent, InteractionSink } from '@application/ports/interaction-log.ts'

import * as dto from './dto.ts'
import { HttpClient } from './http-client.ts'

const PATH = '/api/interactions'

export class HttpInteractionSink implements InteractionSink {
  constructor(private readonly http: HttpClient) {}

  async send(events: readonly InteractionEvent[]) {
    if (events.length === 0) return
    try {
      await this.http.post(PATH, { events }, dto.interactionReceiptDto)
    } catch {
      // Swallowed deliberately, and this is the one place in this codebase
      // that swallows an ApiError. Collection is off by one env var, which
      // makes the route answer 503 -- and a console that broke because
      // telemetry was disabled would be a far worse defect than a lost
      // batch. The data is droppable by design; that is why it has its own
      // store.
    }
  }

  sendOnUnload(events: readonly InteractionEvent[]) {
    if (events.length === 0) return
    const url = this.http.url(PATH)
    const body = JSON.stringify({ events })

    // A Blob rather than a string so the Content-Type is application/json:
    // sendBeacon sends a bare string as text/plain, which FastAPI refuses.
    const payload = new Blob([body], { type: 'application/json' })

    if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
      navigator.sendBeacon(url, payload)
      return
    }

    // Not every browser has it. `keepalive` is the nearest equivalent: it
    // asks the browser to finish the request after the document goes away.
    // Weaker than a beacon and worth having anyway, because the alternative
    // loses every session's last view, which is where friction lives.
    void fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => undefined)
  }
}

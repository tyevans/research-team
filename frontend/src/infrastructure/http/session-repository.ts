import { z } from 'zod'

import type { SessionRepository } from '@application/ports/repositories.ts'
import type { EventIndex } from '@domain/session/event-index.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { ForkNode, SessionProjection, SessionSummary } from '@domain/session/session.ts'
import { SessionId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toForkNode, toLogEntry, toSession, toSessionSummary } from './mappers.ts'

export class HttpSessionRepository implements SessionRepository {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<readonly SessionSummary[]> {
    const rows = await this.http.get('/api/sessions', z.array(dto.sessionSummaryDto))
    return rows.map(toSessionSummary)
  }

  async tree(): Promise<readonly ForkNode[]> {
    const roots = await this.http.get('/api/tree', z.array(dto.forkNodeDto))
    return roots.map(toForkNode)
  }

  async create(systemPrompt?: string): Promise<SessionId> {
    const body = systemPrompt === undefined ? {} : { system_prompt: systemPrompt }
    const created = await this.http.post('/api/sessions', body, dto.idDto)
    return SessionId(created.id)
  }

  async read(id: SessionId, at: ScrubPoint): Promise<SessionProjection> {
    // HEAD and a scrubbed point are two routes answering one shape. Choosing
    // between them here rather than at the call site is what lets every caller
    // above take a ScrubPoint and stop caring.
    const path =
      at.kind === 'head'
        ? `/api/sessions/${seg(id)}`
        : `/api/sessions/${seg(id)}/at/${at.at}`
    return toSession(await this.http.get(path, dto.sessionDto))
  }

  async log(id: SessionId): Promise<readonly LogEntry[]> {
    const rows = await this.http.get(`/api/sessions/${seg(id)}/events`, z.array(dto.logEntryDto))
    return rows.map(toLogEntry)
  }

  async fork(id: SessionId, at: EventIndex): Promise<SessionId> {
    const forked = await this.http.post(`/api/sessions/${seg(id)}/forks`, { at }, dto.idDto)
    return SessionId(forked.id)
  }

  async release(id: SessionId): Promise<boolean> {
    const result = await this.http.post(
      `/api/sessions/${seg(id)}/release`,
      {},
      z.object({ released: z.boolean().default(false) }),
    )
    return result.released
  }
}

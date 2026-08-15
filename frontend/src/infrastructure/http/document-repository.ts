import { z } from 'zod'

import type { DocumentRange, DocumentRepository } from '@application/ports/repositories.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toDocumentSummary, toDocumentText, toExtractionQueueBoard } from './mappers.ts'

export class HttpDocumentRepository implements DocumentRepository {
  constructor(private readonly http: HttpClient) {}

  async list(projectId: ProjectId) {
    // `include_dropped=true` unconditionally: the browser is exactly the
    // caller `source_view`'s default excludes for, and this repository is
    // the browser's only way to reach the corpus, so it always asks for the
    // whole thing rather than exposing the flag as a second code path.
    const rows = await this.http.get(
      `/api/projects/${seg(projectId)}/sources${query({ include_dropped: 'true' })}`,
      z.array(dto.documentDto),
    )
    return rows.map(toDocumentSummary)
  }

  async read(projectId: ProjectId, sourceId: SourceId, range?: DocumentRange) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}` +
        query({ start: range?.start, end: range?.end }),
      dto.documentTextDto,
    )
    return toDocumentText(body)
  }

  async extract(projectId: ProjectId, sourceId: SourceId) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}/extract`,
      {},
      // Inline rather than a named schema in `dto.ts`, matching
      // `cancelDispatch`: one field, read once, and nothing else maps it.
      // `source_id` comes back too and is deliberately dropped -- the caller
      // asked about a source it already named.
      z.object({ queued: z.boolean() }),
    )
    return body.queued
  }

  async extractAll(projectId: ProjectId) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/extract`,
      {},
      // `source_ids` is dropped for the same reason: the header reports a
      // count, and a list of ids it would have to render is a second design.
      z.object({ queued: z.number() }),
    )
    return body.queued
  }

  async extractionQueue(projectId: ProjectId) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/sources/extraction-queue`,
      dto.extractionQueueDto,
    )
    return toExtractionQueueBoard(body)
  }

  async cancelExtraction(projectId: ProjectId) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/extraction-queue/cancel`,
      {},
      z.object({ cancelled: z.number() }),
    )
    return body.cancelled
  }
}

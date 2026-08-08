import { z } from 'zod'

import type { DocumentRange, DocumentRepository } from '@application/ports/repositories.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toDocumentSummary, toDocumentText } from './mappers.ts'

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
}

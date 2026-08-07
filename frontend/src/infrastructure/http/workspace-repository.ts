import { z } from 'zod'

import type { LessonRepository, WorkspaceRepository } from '@application/ports/repositories.ts'
import type { AttemptResponse, ItemProgress, Verdict } from '@domain/lesson/attempt.ts'
import type { ComponentAudience, LessonDocument } from '@domain/lesson/document.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FileRevision } from '@domain/workspace/workspace-file.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { ComponentId, SessionId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toFileRevision, toLessonDocument, toProgressMap, toVerdict } from './mappers.ts'

export class HttpWorkspaceRepository implements WorkspaceRepository {
  constructor(private readonly http: HttpClient) {}

  /** Contents are addressed by scrub point; the server folds the file for us. */
  readFile(id: SessionId, path: FilePath, at: ScrubPoint): Promise<string> {
    const params = query({ path: path.value, at: ScrubPoint.toNullable(at) })
    return this.http.get(`/api/sessions/${seg(id)}/files${params}`, dto.fileContentDto)
  }

  /** History is the whole log for a path, not a fold — a revision list that
   *  stopped at the scrub point would hide the very edits a reader scrubbed
   *  back to understand. */
  async history(id: SessionId, path: FilePath): Promise<readonly FileRevision[]> {
    const rows = await this.http.get(
      `/api/sessions/${seg(id)}/files/history${query({ path: path.value })}`,
      z.array(dto.fileRevisionDto),
    )
    return rows.map(toFileRevision)
  }
}

export class HttpLessonRepository implements LessonRepository {
  constructor(private readonly http: HttpClient) {}

  async parse(
    id: SessionId,
    path: FilePath,
    audience: ComponentAudience,
    at: ScrubPoint,
  ): Promise<LessonDocument> {
    // `view` is sent rather than filtered client-side because which fields come
    // back is the server's decision — that is the entire point of projecting
    // there — and the browser has no key to hide even if it tried.
    const params = query({ path: path.value, view: audience, at: ScrubPoint.toNullable(at) })
    return toLessonDocument(
      await this.http.get(`/api/sessions/${seg(id)}/files/parsed${params}`, dto.lessonDocumentDto),
    )
  }

  async progress(id: SessionId, path: FilePath): Promise<ReadonlyMap<ComponentId, ItemProgress>> {
    return toProgressMap(
      await this.http.get(
        `/api/sessions/${seg(id)}/progress${query({ path: path.value })}`,
        dto.progressDto,
      ),
    )
  }

  async submitAttempt(
    id: SessionId,
    input: {
      path: FilePath
      componentId: ComponentId
      response: AttemptResponse
      at: ScrubPoint
    },
  ): Promise<Verdict> {
    return toVerdict(
      await this.http.post(
        `/api/sessions/${seg(id)}/attempts`,
        {
          path: input.path.value,
          component_id: input.componentId,
          response: input.response,
          ...atBody(input.at),
        },
        dto.verdictDto,
      ),
    )
  }

  async saveChecklist(
    id: SessionId,
    input: { path: FilePath; componentId: ComponentId; checked: readonly number[]; at: ScrubPoint },
  ): Promise<void> {
    await this.http.post(
      `/api/sessions/${seg(id)}/progress/checklist`,
      {
        path: input.path.value,
        component_id: input.componentId,
        checked: [...input.checked],
        ...atBody(input.at),
      },
      dto.okDto,
    )
  }
}

/** `at` is omitted rather than sent as null when reading HEAD: the route treats
 *  an absent key as "live", and an explicit null is a different request. */
const atBody = (at: ScrubPoint): Record<string, number> =>
  at.kind === 'historical' ? { at: at.at } : {}

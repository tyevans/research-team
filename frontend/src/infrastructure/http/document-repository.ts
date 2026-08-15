import { z } from 'zod'

import type {
  DocumentDraft,
  DocumentEdit,
  DocumentRange,
  DocumentRepository,
  MediaDraft,
} from '@application/ports/repositories.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import {
  toDocumentText,
  toExtractionQueueBoard,
  toMediaSummary,
  toSourceSummary,
  toTextSummary,
} from './mappers.ts'

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
    return rows.map(toSourceSummary)
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

  async create(projectId: ProjectId, draft: DocumentDraft) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources`,
      // Built key by key rather than by mapping the whole draft, so an
      // undefined field is absent from the JSON instead of present as null --
      // which the server reads as "leave it alone" on the edit route, and the
      // two shapes are deliberately the same one.
      prune({
        source_id: draft.sourceId,
        text: draft.text,
        uri: draft.uri,
        title: draft.title,
        note: draft.note,
        published_at: draft.publishedAt,
      }),
      // The text shape, not the union, for the same reason as `uploadMedia`: this route
      // stores text and only text, so a caller does not have to re-narrow what
      // it just created -- and a media row coming back would be the server
      // having done something else entirely, which is worth a `ContractError`.
      dto.textSourceDto,
    )
    return toTextSummary(body)
  }

  async revise(projectId: ProjectId, sourceId: SourceId, edit: DocumentEdit) {
    const body = await this.http.patch(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}`,
      prune({
        text: edit.text,
        uri: edit.uri,
        title: edit.title,
        note: edit.note,
        published_at: edit.publishedAt,
      }),
      dto.documentDto,
    )
    return toSourceSummary(body)
  }

  async drop(projectId: ProjectId, sourceId: SourceId, reason: string) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}/drop`,
      { reason },
      dto.documentDto,
    )
    return toSourceSummary(body)
  }

  async restore(projectId: ProjectId, sourceId: SourceId) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}/restore`,
      {},
      dto.documentDto,
    )
    return toSourceSummary(body)
  }

  async uploadMedia(projectId: ProjectId, draft: MediaDraft) {
    const form = new FormData()
    form.set('file', draft.file)
    form.set('source_id', draft.sourceId)
    // Appended only when set, matching `prune` above and for the same reason:
    // FastAPI reads an absent form field as `None`, but an empty string as an
    // empty string -- so sending `title: ''` would store a title of "" where
    // omitting it stores nothing.
    if (draft.uri !== undefined) form.set('uri', draft.uri)
    if (draft.title !== undefined) form.set('title', draft.title)
    if (draft.note !== undefined) form.set('note', draft.note)
    if (draft.publishedAt !== undefined) form.set('published_at', draft.publishedAt)

    const body = await this.http.postForm(
      `/api/projects/${seg(projectId)}/sources/media`,
      form,
      // The media shape, not the union: this route stores media, so a text row
      // coming back would be the server having done something else entirely
      // and is worth a `ContractError` rather than a silent narrowing.
      dto.mediaSourceDto,
    )
    return toMediaSummary(body)
  }

  contentUrl(projectId: ProjectId, sourceId: SourceId) {
    return this.http.url(`/api/projects/${seg(projectId)}/sources/${seg(sourceId)}/content`)
  }
}

/** Drop the keys whose value is undefined.
 *
 * `JSON.stringify` already omits them, so this changes no request. It is here
 * for the tests, which assert on the object handed to the client rather than
 * on the serialized body, and would otherwise have to spell out every absent
 * field as `undefined` in every expectation.
 */
const prune = (body: Record<string, unknown>): Record<string, unknown> =>
  Object.fromEntries(Object.entries(body).filter(([, value]) => value !== undefined))

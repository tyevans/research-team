import { z } from 'zod'

import type {
  MediaCurationOutcome,
  MediaProposalRepository,
} from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toIgnoredMedia, toMediaProposalGroup } from './mappers.ts'

export class HttpMediaProposalRepository implements MediaProposalRepository {
  constructor(private readonly http: HttpClient) {}

  async list(projectId: ProjectId) {
    const rows = await this.http.get(
      `/api/projects/${seg(projectId)}/media-proposals`,
      z.array(dto.mediaProposalGroupDto),
    )
    return rows.map(toMediaProposalGroup)
  }

  async accept(projectId: ProjectId, proposalId: string) {
    // Inline one-field-plus-status schema, matching `document-repository.ts`'s
    // `extract`: read once, nothing else maps it, and `status` is dropped --
    // the caller already knows what it just did, and the row's *real* status
    // (still `accepted` until the worker finishes, or `stored`/`failed` after)
    // only ever comes from the next `list`.
    await this.http.post(
      `/api/projects/${seg(projectId)}/media-proposals/${seg(proposalId)}/accept`,
      {},
      z.object({ proposal_id: z.string(), status: z.string() }),
    )
  }

  async reject(projectId: ProjectId, proposalId: string, note?: string) {
    // `note` omitted rather than sent as `''`: the body model defaults to
    // `""` server-side, so an absent key and an explicit empty string reach
    // the same place, and omitting keeps a request with nothing to say
    // indistinguishable from one that never mentioned the field.
    await this.http.post(
      `/api/projects/${seg(projectId)}/media-proposals/${seg(proposalId)}/reject`,
      note === undefined ? {} : { note },
      z.object({ proposal_id: z.string(), status: z.string() }),
    )
  }

  async ignore(projectId: ProjectId, proposalId: string, grain: 'asset' | 'host') {
    await this.http.post(
      `/api/projects/${seg(projectId)}/media-proposals/${seg(proposalId)}/ignore`,
      { grain },
      z.object({ proposal_id: z.string(), grain: z.string() }),
    )
  }

  async ignored(projectId: ProjectId) {
    const body = await this.http.get(`/api/projects/${seg(projectId)}/ignored`, dto.ignoredMediaDto)
    return toIgnoredMedia(body)
  }

  async run(projectId: ProjectId, topicId: string): Promise<MediaCurationOutcome> {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/topics/${seg(topicId)}/media-proposals`,
      {},
      dto.mediaCurationOutcomeDto,
    )
    return {
      needs: body.needs,
      candidates: body.candidates,
      ignored: body.ignored,
      rejectedParses: body.rejected_parses,
      searchedEmpty: body.searched_empty,
      judgedOut: body.judged_out,
    }
  }

  async unignore(projectId: ProjectId, grain: 'asset' | 'host', key: string) {
    // `seg(key)` percent-encodes the `/` an asset key carries -- the server's
    // `{key:path}` converter is what makes that safe to send, matching the
    // route's own comment: a host key never contains one, and a `:path`
    // converter accepts a literal `/` from an unencoded caller just as well,
    // so encoding here costs nothing for the host case and is required for
    // the asset one.
    await this.http.delete(
      `/api/projects/${seg(projectId)}/ignored/${grain}/${seg(key)}`,
      z.object({ grain: z.string(), key: z.string() }),
    )
  }
}

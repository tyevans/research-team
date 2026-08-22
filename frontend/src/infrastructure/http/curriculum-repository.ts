import type { CurriculumRepository } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toAuthoringRun, toAuthoringStatus, toCurriculum, toLearningArea } from './mappers.ts'

export class HttpCurriculumRepository implements CurriculumRepository {
  constructor(private readonly http: HttpClient) {}

  async curriculum(projectId: ProjectId) {
    return toCurriculum(
      await this.http.get(`/api/projects/${seg(projectId)}/curriculum`, dto.curriculumDto),
    )
  }

  async area(projectId: ProjectId, slug: string) {
    return toLearningArea(
      await this.http.get(
        // `seg` on the slug as well as the id. The slug is server-derived and
        // already restricted to `[a-z0-9-]`, so this encodes nothing today --
        // it is here because the rule this repository learned the hard way is
        // that uvicorn decodes the path before routing, and a segment that is
        // sometimes escaped and sometimes not is the arrangement where that
        // bites.
        `/api/projects/${seg(projectId)}/curriculum/areas/${seg(slug)}`,
        dto.learningAreaDto,
      ),
    )
  }

  async refreshEmbeddings(projectId: ProjectId) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/embeddings`,
      {},
      dto.embeddingRefreshDto,
    )
    return body.embedded
  }

  async path(projectId: ProjectId, slug: string) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/curriculum/paths/${seg(slug)}`,
      dto.learningPathDto,
    )
    return {
      slug: body.slug,
      title: body.title,
      destination: body.destination,
      areaSlugs: body.areas,
      edges: body.edges,
    }
  }

  async authoringStatus(projectId: ProjectId) {
    return toAuthoringStatus(
      await this.http.get(
        `/api/projects/${seg(projectId)}/curriculum/author`,
        dto.authoringStatusDto,
      ),
    )
  }

  async author(projectId: ProjectId, request: { area?: string; lessons?: number }) {
    return toAuthoringRun(
      await this.http.post(
        `/api/projects/${seg(projectId)}/curriculum/author`,
        request,
        dto.authoringFrameDto,
      ),
    )
  }
}

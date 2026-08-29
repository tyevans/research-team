import type {
  ArtSweepProgress,
  BlurbSweepProgress,
  CourseRepository,
  RealizeResult,
} from '@application/ports/repositories.ts'
import type { CourseDetail, CourseText } from '@domain/knowledge/course.ts'
import { SessionId, type ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toAuthoringRun, toCourseDetail, toCourseText } from './mappers.ts'

export class HttpCourseRepository implements CourseRepository {
  constructor(private readonly http: HttpClient) {}

  async course(projectId: ProjectId, slug: string): Promise<CourseDetail> {
    return toCourseDetail(
      await this.http.get(
        `/api/projects/${seg(projectId)}/catalog/${seg(slug)}`,
        dto.courseDetailDto,
      ),
    )
  }

  async courseText(projectId: ProjectId, slug: string): Promise<CourseText> {
    return toCourseText(
      await this.http.get(
        `/api/projects/${seg(projectId)}/catalog/${seg(slug)}/unit`,
        dto.courseTextDto,
      ),
    )
  }

  async realize(projectId: ProjectId, slug: string): Promise<RealizeResult> {
    const raw = await this.http.post(
      `/api/projects/${seg(projectId)}/catalog/${seg(slug)}/realize`,
      {},
      dto.realizeCourseDto,
    )
    return {
      realized: raw.realized,
      authoring: raw.authoring === null ? null : toAuthoringRun(raw.authoring),
      reason: raw.reason,
      heldBy: raw.heldBy === null ? null : SessionId(raw.heldBy),
    }
  }

  async abandon(projectId: ProjectId, slug: string): Promise<void> {
    await this.http.post(
      `/api/projects/${seg(projectId)}/catalog/${seg(slug)}/abandon`,
      {},
      dto.abandonCourseDto,
    )
  }

  async startBlurbSweep(projectId: ProjectId): Promise<BlurbSweepProgress> {
    return await this.http.post(
      `/api/projects/${seg(projectId)}/catalog/blurbs`,
      {},
      dto.blurbSweepProgressDto,
    )
  }

  async fetchBlurbSweep(projectId: ProjectId): Promise<BlurbSweepProgress> {
    return await this.http.get(
      `/api/projects/${seg(projectId)}/catalog/blurbs`,
      dto.blurbSweepProgressDto,
    )
  }

  async startArtSweep(
    projectId: ProjectId,
    options?: { force?: boolean },
  ): Promise<ArtSweepProgress> {
    const query = options?.force === true ? '?force=true' : ''
    return await this.http.post(
      `/api/projects/${seg(projectId)}/catalog/art${query}`,
      {},
      dto.artSweepProgressDto,
    )
  }

  async fetchArtSweep(projectId: ProjectId): Promise<ArtSweepProgress> {
    return await this.http.get(
      `/api/projects/${seg(projectId)}/catalog/art`,
      dto.artSweepProgressDto,
    )
  }

  async startArtReroll(projectId: ProjectId, slug: string): Promise<ArtSweepProgress> {
    return await this.http.post(
      `/api/projects/${seg(projectId)}/catalog/${seg(slug)}/art/reroll`,
      {},
      dto.artSweepProgressDto,
    )
  }

  async fetchArtReroll(projectId: ProjectId, slug: string): Promise<ArtSweepProgress> {
    return await this.http.get(
      `/api/projects/${seg(projectId)}/catalog/${seg(slug)}/art/reroll`,
      dto.artSweepProgressDto,
    )
  }
}

import type {
  BlurbSweepProgress,
  CourseRepository,
  RealizeResult,
} from '@application/ports/repositories.ts'
import type { CourseDetail } from '@domain/knowledge/course.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toAuthoringRun, toCourseDetail } from './mappers.ts'

export class HttpCourseRepository implements CourseRepository {
  constructor(private readonly http: HttpClient) {}

  async course(projectId: ProjectId, slug: string): Promise<CourseDetail> {
    return toCourseDetail(
      await this.http.get(`/api/projects/${seg(projectId)}/catalog/${seg(slug)}`, dto.courseDetailDto),
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
}

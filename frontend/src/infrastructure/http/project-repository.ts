import { z } from 'zod'

import { ApiError, ResearchDisabledError } from '@application/ports/errors.ts'
import type {
  ExtractionRepository,
  HealthRepository,
  ProjectRepository,
  ResearchRepository,
  SummaryHealth,
  WorkerRepository,
} from '@application/ports/repositories.ts'
import type { ExtractionFrame } from '@domain/knowledge/extraction.ts'
import type { Course } from '@domain/project/course.ts'
import type { Project, WorkflowPreset } from '@domain/project/project.ts'
import type { ResearchRun } from '@domain/research/run.ts'
import type { Roster } from '@domain/worker/worker.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toCourse, toExtractionFrame, toPreset, toProject, toRoster, toRun } from './mappers.ts'

export class HttpProjectRepository implements ProjectRepository {
  constructor(private readonly http: HttpClient) {}

  async list(): Promise<readonly Project[]> {
    const rows = await this.http.get('/api/projects', z.array(dto.projectDto))
    return rows.map(toProject)
  }

  async presets(): Promise<readonly WorkflowPreset[]> {
    const rows = await this.http.get('/api/workflows', z.array(dto.presetDto))
    return rows.map(toPreset)
  }

  async create(name: string): Promise<ProjectId> {
    const created = await this.http.post('/api/projects', { name }, dto.idDto)
    return ProjectId(created.id)
  }

  async chooseWorkflow(id: ProjectId, presetId: string): Promise<string> {
    const result = await this.http.post(
      `/api/projects/${seg(id)}/workflow`,
      { preset_id: presetId },
      z.object({ workflow: dto.workflowRefDto.nullish() }),
    )
    return result.workflow?.name ?? presetId
  }

  async join(
    id: ProjectId,
    takeOver: boolean,
  ): Promise<{ sessionId: SessionId; warning: string | null }> {
    const result = await this.http.post(
      `/api/projects/${seg(id)}/join`,
      { take_over: takeOver },
      z.object({
        id: z.string(),
        warning: z
          .string()
          .nullish()
          .transform((v) => v ?? null),
      }),
    )
    return { sessionId: SessionId(result.id), warning: result.warning }
  }

  async delete(id: ProjectId, releaseHolder: boolean): Promise<void> {
    // The flag is only sent when true: the route defaults it, and sending
    // `release_holder=false` against a free project reads as a decision that
    // was never made.
    const params = releaseHolder ? query({ release_holder: 'true' }) : ''
    await this.http.delete(`/api/projects/${seg(id)}${params}`, dto.okDto)
  }

  async course(id: ProjectId): Promise<Course> {
    return toCourse(await this.http.get(`/api/projects/${seg(id)}/course`, dto.courseDto), id)
  }
}

/** Matched on "not enabled" rather than on the variable name: the GET says only
 *  that much, and only the POST spells out what to set. */
const saysDisabled = (message: string): boolean => /not enabled|AGENT_RESEARCH_RUN/.test(message)

export class HttpResearchRepository implements ResearchRepository {
  constructor(private readonly http: HttpClient) {}

  async current(id: ProjectId): Promise<ResearchRun | null> {
    try {
      return toRun(await this.http.get(`/api/projects/${seg(id)}/auto-research`, dto.runDto))
    } catch (error) {
      // Two unrelated meanings behind one status code, told apart by the detail
      // text because that is all the server gives.
      if (error instanceof ApiError && error.isNotFound) {
        if (saysDisabled(error.message)) throw new ResearchDisabledError(error.message)
        return null
      }
      throw error
    }
  }

  async start(id: ProjectId, maxRounds: number | null): Promise<ResearchRun> {
    const body = maxRounds === null ? {} : { max_rounds: maxRounds }
    try {
      return toRun(await this.http.post(`/api/projects/${seg(id)}/auto-research`, body, dto.runDto))
    } catch (error) {
      if (error instanceof ApiError && error.isNotFound && saysDisabled(error.message)) {
        throw new ResearchDisabledError(error.message)
      }
      throw error
    }
  }

  async cancel(id: ProjectId): Promise<boolean> {
    const result = await this.http.post(
      `/api/projects/${seg(id)}/auto-research/cancel`,
      {},
      z.object({ cancelled: z.boolean().default(false) }),
    )
    return result.cancelled
  }
}

export class HttpWorkerRepository implements WorkerRepository {
  constructor(private readonly http: HttpClient) {}

  async on(projectId: ProjectId): Promise<Roster> {
    return toRoster(await this.http.get(`/api/projects/${seg(projectId)}/workers`, dto.rosterDto))
  }

  async everywhere(): Promise<readonly Roster[]> {
    const rows = await this.http.get('/api/workers', z.array(dto.rosterDto))
    return rows.map(toRoster)
  }
}

export class HttpExtractionRepository implements ExtractionRepository {
  constructor(private readonly http: HttpClient) {}

  async on(projectId: ProjectId): Promise<{
    readonly current: readonly ExtractionFrame[]
    readonly last: readonly ExtractionFrame[]
  }> {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/extraction`,
      dto.extractionCatchUpDto,
    )
    return { current: body.current.map(toExtractionFrame), last: body.last.map(toExtractionFrame) }
  }
}

export class HttpHealthRepository implements HealthRepository {
  constructor(private readonly http: HttpClient) {}

  async summaries(): Promise<SummaryHealth> {
    const body = await this.http.get('/api/health', dto.healthDto)
    return {
      healthy: body.summaries.healthy,
      following: body.summaries.following,
      failedEvents: body.summaries.failed_events,
    }
  }

  async rebuildSummaries(): Promise<void> {
    await this.http.post('/api/summaries/rebuild', {}, dto.okDto)
  }
}

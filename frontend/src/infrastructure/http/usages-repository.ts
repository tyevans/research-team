import type { UsagesRepository } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toUsage } from './mappers.ts'

export class HttpUsagesRepository implements UsagesRepository {
  constructor(private readonly http: HttpClient) {}

  async usages(projectId: ProjectId, entityId: string) {
    // No `limit` in the query string, matching the port's own reasoning: the
    // server's cap is the right one, and passing a number here would be a
    // second bound this client would have to keep in step with it.
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/graph/entities/${seg(entityId)}/usages`,
      dto.usagePageDto,
    )
    return body.usages.map(toUsage)
  }
}

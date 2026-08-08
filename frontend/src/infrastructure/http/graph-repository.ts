import type { GraphRepository } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toGraphNode, toNeighborhood } from './mappers.ts'

export class HttpGraphRepository implements GraphRepository {
  constructor(private readonly http: HttpClient) {}

  async search(projectId: ProjectId, name: string) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/graph/entities${query({ name })}`,
      dto.graphEntityPageDto,
    )
    return body.entities.map(toGraphNode)
  }

  async neighborhood(projectId: ProjectId, entityId: string, depth?: number) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/graph/entities/${seg(entityId)}/neighborhood${query({ depth })}`,
      dto.graphNeighborhoodDto,
    )
    return toNeighborhood(body)
  }
}

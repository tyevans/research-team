import type { GraphRepository } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, query, seg } from './http-client.ts'
import { toGraphNode, toNeighborhood, toWholeGraph } from './mappers.ts'

export class HttpGraphRepository implements GraphRepository {
  constructor(private readonly http: HttpClient) {}

  async whole(projectId: ProjectId) {
    // No `limit`: the server's own cap is the right one, and a number picked
    // here would be a second bound to keep in step with it.
    const body = await this.http.get(`/api/projects/${seg(projectId)}/graph`, dto.graphWholeDto)
    return toWholeGraph(body)
  }

  async search(projectId: ProjectId, name: string, entityType?: string) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/graph/entities${query({ name, entity_type: entityType })}`,
      dto.graphEntityPageDto,
    )
    // `next_after` present means the store had more to give than this page
    // returned -- the same "absent means finished" cursor shape the route
    // and reader use, read here as a truncation flag rather than resumed.
    return { entities: body.entities.map(toGraphNode), truncated: body.next_after !== null }
  }

  async neighborhood(projectId: ProjectId, entityId: string, depth?: number) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/graph/entities/${seg(entityId)}/neighborhood${query({ depth })}`,
      dto.graphNeighborhoodDto,
    )
    return toNeighborhood(body)
  }
}

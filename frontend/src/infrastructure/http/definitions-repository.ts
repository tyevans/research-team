import type { DefinitionsRepository } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toDefinition } from './mappers.ts'

export class HttpDefinitionsRepository implements DefinitionsRepository {
  constructor(private readonly http: HttpClient) {}

  async definition(projectId: ProjectId, entityId: string) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/graph/entities/${seg(entityId)}/definition`,
      dto.definitionDto,
    )
    return toDefinition(body)
  }
}

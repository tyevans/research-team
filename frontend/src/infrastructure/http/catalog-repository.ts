import type { CatalogRepository } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toCatalog } from './mappers.ts'

export class HttpCatalogRepository implements CatalogRepository {
  constructor(private readonly http: HttpClient) {}

  async catalog(projectId: ProjectId, includeUnnamed = false) {
    const suffix = includeUnnamed ? '?unnamed=true' : ''
    return toCatalog(
      await this.http.get(`/api/projects/${seg(projectId)}/catalog${suffix}`, dto.catalogDto),
    )
  }

  async feature(projectId: ProjectId, slug: string, rank: number) {
    await this.http.post(
      `/api/projects/${seg(projectId)}/catalog/${seg(slug)}/feature`,
      { rank },
      dto.catalogFeatureDto,
    )
  }

  async unfeature(projectId: ProjectId, slug: string) {
    await this.http.post(
      `/api/projects/${seg(projectId)}/catalog/${seg(slug)}/unfeature`,
      {},
      dto.catalogUnfeatureDto,
    )
  }
}

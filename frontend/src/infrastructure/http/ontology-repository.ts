import type { OntologyRepository } from '@application/ports/repositories.ts'
import { foldOntology } from '@domain/knowledge/ontology.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'

export class HttpOntologyRepository implements OntologyRepository {
  constructor(private readonly http: HttpClient) {}

  async classes(projectId: ProjectId) {
    const body = await this.http.get(`/api/projects/${seg(projectId)}/ontology`, dto.ontologyDto)
    // Folded here rather than in a mapper module, unlike every other
    // repository: the fold is not a per-field rename but the ordering rule
    // that makes an ordered scale readable, and it already lives in the domain
    // with the tests that pin it. A second mapper would be a place for the two
    // to disagree.
    return foldOntology(body)
  }

  async ungrouped(projectId: ProjectId, options?: { readonly includeExamined?: boolean }) {
    // The parameter is omitted rather than sent as `false` when it is not
    // asked for, so the ordinary sweep's request is byte-identical to what it
    // was before the re-read existed -- a cache or a log line that keyed on the
    // URL keeps meaning what it meant.
    const query = options?.includeExamined === true ? '?include_examined=true' : ''
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/sources/ungrouped${query}`,
      dto.ungroupedSourcesDto,
    )
    return body.sourceIds
  }

  async discover(projectId: ProjectId, sourceId: string, options?: { readonly strict?: boolean }) {
    const query = options?.strict === false ? '?strict=false' : ''
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}/ontology${query}`,
      {},
      dto.ontologyPassDto,
    )
    return body.found
  }
}

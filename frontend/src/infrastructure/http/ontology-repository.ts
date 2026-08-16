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

  async discover(projectId: ProjectId, sourceId: string) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/sources/${seg(sourceId)}/ontology`,
      {},
      dto.ontologyPassDto,
    )
    return body.found
  }
}

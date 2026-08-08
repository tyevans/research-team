import { z } from 'zod'

import type { TopicRepository } from '@application/ports/repositories.ts'
import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toTopicDetail, toTopicView } from './mappers.ts'

export class HttpTopicRepository implements TopicRepository {
  constructor(private readonly http: HttpClient) {}

  async list(projectId: ProjectId) {
    const rows = await this.http.get(
      `/api/projects/${seg(projectId)}/topics`,
      z.array(dto.topicDto),
    )
    return rows.map(toTopicView)
  }

  async read(projectId: ProjectId, topicId: TopicId) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/topics/${seg(topicId)}`,
      dto.topicDetailDto,
    )
    return toTopicDetail(body)
  }
}

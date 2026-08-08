import { z } from 'zod'

import type { TopicRepository } from '@application/ports/repositories.ts'
import type { TopicStatus } from '@domain/research/topic.ts'
import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import { toSeedingRun, toTopicDetail, toTopicView } from './mappers.ts'

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

  async setStatus(
    projectId: ProjectId,
    topicId: TopicId,
    toStatus: TopicStatus,
    justification: string,
  ) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/topics/${seg(topicId)}/status`,
      { to_status: toStatus, justification },
      dto.topicDetailDto,
    )
    return toTopicDetail(body)
  }

  async addSubQuestion(projectId: ProjectId, topicId: TopicId, key: string, question: string) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/topics/${seg(topicId)}/sub-questions`,
      { key, question },
      dto.topicDetailDto,
    )
    return toTopicDetail(body)
  }

  async resolveSubQuestion(projectId: ProjectId, topicId: TopicId, key: string, answer: string) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/topics/${seg(topicId)}/sub-questions/${seg(key)}/resolve`,
      { answer },
      dto.topicDetailDto,
    )
    return toTopicDetail(body)
  }

  async startSeed(projectId: ProjectId, subject: string, maxTopics: number) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/topics/seed`,
      { subject, max_topics: maxTopics },
      dto.seedingFrameDto,
    )
    return toSeedingRun(body)
  }

  async seedStatus(projectId: ProjectId) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/topics/seed`,
      dto.seedingCatchUpDto,
    )
    return {
      current: body.current ? toSeedingRun(body.current) : null,
      last: body.last ? toSeedingRun(body.last) : null,
    }
  }
}

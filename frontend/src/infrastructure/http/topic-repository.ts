import { z } from 'zod'

import type { TopicRepository } from '@application/ports/repositories.ts'
import type { DispatchAction } from '@domain/research/dispatch.ts'
import type { TopicStatus } from '@domain/research/topic.ts'
import type { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import * as dto from './dto.ts'
import { HttpClient, seg } from './http-client.ts'
import {
  toDispatch,
  toSeedingRun,
  toTopicDetail,
  toTopicDocuments,
  toTopicView,
} from './mappers.ts'

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

  async dispatch(projectId: ProjectId, topicId: TopicId, action: DispatchAction) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/topics/${seg(topicId)}/dispatch`,
      { action },
      dto.dispatchFrameDto,
    )
    return toDispatch(body)
  }

  /** One post, not a loop of the per-topic route.
   *
   * The loop is on the server, inside `dispatch_topics`, and that is where it
   * has to be: fifty presses from the browser would each be scheduled against
   * the same one-in-flight queue with nothing ordering them, and a tab closed
   * halfway would start half of what it said. One request either enqueues the
   * list in the order given or refuses it before any topic is resolved.
   */
  async dispatchBulk(projectId: ProjectId, action: DispatchAction, topicIds: readonly TopicId[]) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/dispatch/bulk`,
      // `topic_ids`, snake, and spread into a plain array because the wire
      // takes JSON and a `readonly TopicId[]` is a branded type the server has
      // never heard of.
      { action, topic_ids: [...topicIds].map(String) },
      dto.bulkDispatchDto,
    )
    return { queued: body.queued.map(toDispatch), unknown: body.unknown }
  }

  async dispatchStatus(projectId: ProjectId) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/dispatch`,
      dto.dispatchCatchUpDto,
    )
    return {
      running: body.running ? toDispatch(body.running) : null,
      queued: body.queued.map(toDispatch),
      finished: body.finished.map(toDispatch),
    }
  }

  async documents(projectId: ProjectId, topicId: TopicId) {
    const body = await this.http.get(
      `/api/projects/${seg(projectId)}/topics/${seg(topicId)}/documents`,
      dto.topicDocumentsDto,
    )
    return toTopicDocuments(body)
  }

  async cancelDispatch(projectId: ProjectId) {
    const body = await this.http.post(
      `/api/projects/${seg(projectId)}/dispatch/cancel`,
      {},
      z.object({ cancelled: z.number() }),
    )
    return body.cancelled
  }
}

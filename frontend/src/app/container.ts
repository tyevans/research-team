import type { EventStream } from '@application/ports/event-stream.ts'
import type { PreferenceStore } from '@application/ports/preferences.ts'
import type {
  ApprovalRepository,
  AutonomyRepository,
  DocumentRepository,
  ExtractionRepository,
  HealthRepository,
  LessonRepository,
  ProjectRepository,
  ResearchRepository,
  SessionRepository,
  TopicRepository,
  TurnRepository,
  WorkerRepository,
  WorkspaceRepository,
} from '@application/ports/repositories.ts'
import { HttpAutonomyRepository } from '@infrastructure/http/autonomy-repository.ts'
import { HttpDocumentRepository } from '@infrastructure/http/document-repository.ts'
import { HttpClient } from '@infrastructure/http/http-client.ts'
import {
  HttpExtractionRepository,
  HttpHealthRepository,
  HttpProjectRepository,
  HttpResearchRepository,
  HttpWorkerRepository,
} from '@infrastructure/http/project-repository.ts'
import { HttpSessionRepository } from '@infrastructure/http/session-repository.ts'
import { HttpTopicRepository } from '@infrastructure/http/topic-repository.ts'
import { HttpApprovalRepository, HttpTurnRepository } from '@infrastructure/http/turn-repository.ts'
import {
  HttpLessonRepository,
  HttpWorkspaceRepository,
} from '@infrastructure/http/workspace-repository.ts'
import { SseEventStream } from '@infrastructure/sse/event-stream.ts'
import { LocalPreferenceStore } from '@infrastructure/storage/preference-store.ts'

/** Everything the application needs from the outside world, in one bag.
 *
 * The composition root, and the only module that names a concrete adapter. Two
 * things follow from that: a test can build a container out of fakes without
 * touching a component, and swapping the transport is a change to one file.
 */
export interface Container {
  readonly sessions: SessionRepository
  readonly workspace: WorkspaceRepository
  readonly lessons: LessonRepository
  readonly turns: TurnRepository
  readonly approvals: ApprovalRepository
  readonly autonomy: AutonomyRepository
  readonly projects: ProjectRepository
  readonly research: ResearchRepository
  readonly topics: TopicRepository
  readonly documents: DocumentRepository
  readonly workers: WorkerRepository
  readonly extractions: ExtractionRepository
  readonly health: HealthRepository
  readonly stream: EventStream
  readonly preferences: PreferenceStore
  /** Injected so tests can drive it, and so nothing below reaches for the
   *  global clock directly. */
  readonly now: () => number
}

export const createContainer = (baseUrl = ''): Container => {
  const http = new HttpClient(baseUrl)
  return {
    sessions: new HttpSessionRepository(http),
    workspace: new HttpWorkspaceRepository(http),
    lessons: new HttpLessonRepository(http),
    turns: new HttpTurnRepository(http),
    approvals: new HttpApprovalRepository(http),
    autonomy: new HttpAutonomyRepository(http),
    projects: new HttpProjectRepository(http),
    research: new HttpResearchRepository(http),
    topics: new HttpTopicRepository(http),
    documents: new HttpDocumentRepository(http),
    workers: new HttpWorkerRepository(http),
    extractions: new HttpExtractionRepository(http),
    health: new HttpHealthRepository(http),
    stream: new SseEventStream(`${baseUrl}/api/stream`),
    preferences: new LocalPreferenceStore(),
    now: () => Date.now(),
  }
}

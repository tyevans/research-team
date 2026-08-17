import type { EventStream } from '@application/ports/event-stream.ts'
import type { InteractionSink } from '@application/ports/interaction-log.ts'
import type { PreferenceStore } from '@application/ports/preferences.ts'
import type {
  ApprovalRepository,
  AskRepository,
  AutonomyRepository,
  DefinitionsRepository,
  OntologyRepository,
  DocumentRepository,
  ExtractionRepository,
  GraphRepository,
  HealthRepository,
  LessonRepository,
  MediaProposalRepository,
  ProjectRepository,
  ResearchRepository,
  SessionRepository,
  TimelineRepository,
  TopicRepository,
  TurnRepository,
  UsagesRepository,
  WorkerRepository,
  WorkspaceRepository,
} from '@application/ports/repositories.ts'
import { HttpAskRepository } from '@infrastructure/http/ask-repository.ts'
import { HttpAutonomyRepository } from '@infrastructure/http/autonomy-repository.ts'
import { HttpDefinitionsRepository } from '@infrastructure/http/definitions-repository.ts'
import { HttpOntologyRepository } from '@infrastructure/http/ontology-repository.ts'
import { HttpDocumentRepository } from '@infrastructure/http/document-repository.ts'
import { HttpGraphRepository } from '@infrastructure/http/graph-repository.ts'
import { HttpClient } from '@infrastructure/http/http-client.ts'
import { HttpInteractionSink } from '@infrastructure/http/interaction-log-repository.ts'
import { HttpMediaProposalRepository } from '@infrastructure/http/media-proposal-repository.ts'
import {
  HttpExtractionRepository,
  HttpHealthRepository,
  HttpProjectRepository,
  HttpResearchRepository,
  HttpWorkerRepository,
} from '@infrastructure/http/project-repository.ts'
import { HttpSessionRepository } from '@infrastructure/http/session-repository.ts'
import { HttpTimelineRepository } from '@infrastructure/http/timeline-repository.ts'
import { HttpTopicRepository } from '@infrastructure/http/topic-repository.ts'
import { HttpApprovalRepository, HttpTurnRepository } from '@infrastructure/http/turn-repository.ts'
import { HttpUsagesRepository } from '@infrastructure/http/usages-repository.ts'
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
  readonly mediaProposals: MediaProposalRepository
  readonly graphs: GraphRepository
  readonly usages: UsagesRepository
  readonly definitions: DefinitionsRepository
  readonly ontology: OntologyRepository
  readonly timelines: TimelineRepository
  readonly workers: WorkerRepository
  readonly extractions: ExtractionRepository
  readonly health: HealthRepository
  /** Its own adapter rather than one built on `HttpClient`: it POSTs and reads
   *  a stream, and `HttpClient` reads whole bodies. */
  readonly ask: AskRepository
  readonly stream: EventStream
  readonly preferences: PreferenceStore
  /** Where the interaction log is reported to. Capture only; nothing reads
   *  it back, so there is no query hook and no repository beside this. */
  readonly interactions: InteractionSink
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
    mediaProposals: new HttpMediaProposalRepository(http),
    graphs: new HttpGraphRepository(http),
    usages: new HttpUsagesRepository(http),
    definitions: new HttpDefinitionsRepository(http),
    ontology: new HttpOntologyRepository(http),
    timelines: new HttpTimelineRepository(http),
    workers: new HttpWorkerRepository(http),
    extractions: new HttpExtractionRepository(http),
    health: new HttpHealthRepository(http),
    ask: new HttpAskRepository(baseUrl),
    stream: new SseEventStream(`${baseUrl}/api/stream`),
    preferences: new LocalPreferenceStore(),
    interactions: new HttpInteractionSink(http),
    now: () => Date.now(),
  }
}

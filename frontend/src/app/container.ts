import type { EventStream } from '@application/ports/event-stream.ts'
import type { InteractionSink } from '@application/ports/interaction-log.ts'
import type { PreferenceStore } from '@application/ports/preferences.ts'
import type {
  ApprovalRepository,
  AskRepository,
  AuthRepository,
  AutonomyRepository,
  CatalogRepository,
  CourseRepository,
  DefinitionsRepository,
  DialogueRepository,
  OntologyRepository,
  DocumentRepository,
  ExtractionRepository,
  GraphRepository,
  HealthRepository,
  InteractionLogRepository,
  LessonRepository,
  MediaProposalRepository,
  ProjectRepository,
  SessionRepository,
  SettingsRepository,
  CurriculumRepository,
  ExportRepository,
  TimelineRepository,
  TopicRepository,
  TurnRepository,
  UsagesRepository,
  WorkerRepository,
  WorkspaceRepository,
} from '@application/ports/repositories.ts'
import { HttpAskRepository } from '@infrastructure/http/ask-repository.ts'
import { HttpAuthRepository } from '@infrastructure/http/auth-repository.ts'
import { HttpAutonomyRepository } from '@infrastructure/http/autonomy-repository.ts'
import { HttpCatalogRepository } from '@infrastructure/http/catalog-repository.ts'
import { HttpCourseRepository } from '@infrastructure/http/course-repository.ts'
import { HttpDefinitionsRepository } from '@infrastructure/http/definitions-repository.ts'
import { HttpOntologyRepository } from '@infrastructure/http/ontology-repository.ts'
import { HttpSettingsRepository } from '@infrastructure/http/settings-repository.ts'
import { HttpDialogueRepository } from '@infrastructure/http/dialogue-repository.ts'
import { HttpDocumentRepository } from '@infrastructure/http/document-repository.ts'
import { HttpGraphRepository } from '@infrastructure/http/graph-repository.ts'
import { HttpClient } from '@infrastructure/http/http-client.ts'
import { HttpInteractionSink } from '@infrastructure/http/interaction-log-repository.ts'
import { HttpInteractionLogRepository } from '@infrastructure/http/interaction-log-query-repository.ts'
import { HttpMediaProposalRepository } from '@infrastructure/http/media-proposal-repository.ts'
import {
  HttpExtractionRepository,
  HttpHealthRepository,
  HttpProjectRepository,
  HttpWorkerRepository,
} from '@infrastructure/http/project-repository.ts'
import { HttpSessionRepository } from '@infrastructure/http/session-repository.ts'
import { HttpCurriculumRepository } from '@infrastructure/http/curriculum-repository.ts'
import { HttpExportRepository } from '@infrastructure/http/export-repository.ts'
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
  readonly topics: TopicRepository
  readonly documents: DocumentRepository
  readonly mediaProposals: MediaProposalRepository
  readonly graphs: GraphRepository
  readonly usages: UsagesRepository
  readonly definitions: DefinitionsRepository
  readonly ontology: OntologyRepository
  readonly settings: SettingsRepository
  readonly curricula: CurriculumRepository
  readonly catalog: CatalogRepository
  readonly courses: CourseRepository
  /** URLs, not bodies. Downloads are handed to the browser rather than
   *  fetched into the tab; see `HttpExportRepository`. */
  readonly exports: ExportRepository
  readonly timelines: TimelineRepository
  readonly workers: WorkerRepository
  readonly extractions: ExtractionRepository
  readonly health: HealthRepository
  /** Sign-in, sign-out and who is signed in. A repository like the rest even
   *  though two of its four members are URL builders rather than requests --
   *  the alternative is a component knowing that `/auth/login` exists, which
   *  is the one piece of routing knowledge this layer is here to keep out of
   *  the presentation. */
  readonly auth: AuthRepository
  /** Its own adapter rather than one built on `HttpClient`: it POSTs and reads
   *  a stream, and `HttpClient` reads whole bodies. */
  readonly ask: AskRepository
  /** Plural, matching `graphs`/`timelines`/`documents`. A singular key
   *  typechecks through the `as unknown as Container` cast every test harness
   *  uses and resolves to `undefined` at runtime, so the symptom is a page
   *  stuck loading forever rather than a type error. */
  readonly dialogues: DialogueRepository
  readonly stream: EventStream
  readonly preferences: PreferenceStore
  /** Where the interaction log is reported to. Capture only; nothing reads
   *  it back, so there is no query hook and no repository beside this. */
  readonly interactions: InteractionSink
  /** Reading the log back. Separate from `interactions` above and named for
   *  the direction, because the sink swallows every error by design and a
   *  debugging surface must not. */
  readonly interactionLog: InteractionLogRepository
  /** Injected so tests can drive it, and so nothing below reaches for the
   *  global clock directly. */
  readonly now: () => number
}

export const createContainer = (
  baseUrl = '',
  /** What to do the first time a request answers 401.
   *
   * Threaded from `main.tsx` rather than decided here, because "reload the
   * page" is a browser behaviour and this module composes adapters. Optional
   * so that every test harness building a container keeps working unchanged --
   * and so that a container built without it simply lets the 401 surface as an
   * `ApiError`, which is what a test wants to assert on. */
  onUnauthorized?: () => void,
): Container => {
  const http = new HttpClient(baseUrl, onUnauthorized)
  return {
    sessions: new HttpSessionRepository(http),
    workspace: new HttpWorkspaceRepository(http),
    lessons: new HttpLessonRepository(http),
    turns: new HttpTurnRepository(http),
    approvals: new HttpApprovalRepository(http),
    autonomy: new HttpAutonomyRepository(http),
    projects: new HttpProjectRepository(http),
    topics: new HttpTopicRepository(http),
    documents: new HttpDocumentRepository(http),
    mediaProposals: new HttpMediaProposalRepository(http),
    graphs: new HttpGraphRepository(http),
    usages: new HttpUsagesRepository(http),
    definitions: new HttpDefinitionsRepository(http),
    ontology: new HttpOntologyRepository(http),
    settings: new HttpSettingsRepository(http),
    curricula: new HttpCurriculumRepository(http),
    catalog: new HttpCatalogRepository(http),
    courses: new HttpCourseRepository(http),
    exports: new HttpExportRepository(baseUrl),
    timelines: new HttpTimelineRepository(http),
    workers: new HttpWorkerRepository(http),
    extractions: new HttpExtractionRepository(http),
    health: new HttpHealthRepository(http),
    auth: new HttpAuthRepository(http),
    ask: new HttpAskRepository(baseUrl),
    // `baseUrl` and not `http`, like `ask`: it POSTs and reads a stream, which
    // `HttpClient` would buffer whole.
    dialogues: new HttpDialogueRepository(baseUrl),
    stream: new SseEventStream(`${baseUrl}/api/stream`),
    preferences: new LocalPreferenceStore(),
    interactions: new HttpInteractionSink(http),
    interactionLog: new HttpInteractionLogRepository(http),
    now: () => Date.now(),
  }
}

import type { Approval, ApprovalDecision } from '@domain/approval/approval.ts'
import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { AutonomyChange, AutonomyPolicyView } from '@domain/autonomy/autonomy.ts'
import type { ExtractionFrame } from '@domain/knowledge/extraction.ts'
import type { EntitySearchResult, Neighborhood } from '@domain/knowledge/graph.ts'
import type { ComponentAudience, LessonDocument } from '@domain/lesson/document.ts'
import type { AttemptResponse, ItemProgress, Verdict } from '@domain/lesson/attempt.ts'
import type { Course } from '@domain/project/course.ts'
import type { Project, WorkflowPreset } from '@domain/project/project.ts'
import type { DocumentSummary, DocumentText } from '@domain/research/document.ts'
import type { ResearchRun } from '@domain/research/run.ts'
import type { SeedingRun } from '@domain/research/seeding.ts'
import type { TopicDetail, TopicStatus, TopicView } from '@domain/research/topic.ts'
import type { EventIndex } from '@domain/session/event-index.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import type { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { ForkNode, SessionProjection, SessionSummary } from '@domain/session/session.ts'
import type { TurnRange } from '@domain/session/turn.ts'
import type { Roster } from '@domain/worker/worker.ts'
import type { FileRevision } from '@domain/workspace/workspace-file.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type {
  ApprovalId,
  ComponentId,
  ProjectId,
  SessionId,
  SourceId,
  TopicId,
} from '@domain/shared/identifier.ts'

/** The ports this application depends on, stated in domain terms.
 *
 * Nothing here mentions HTTP, JSON, status codes or URLs. That is the whole
 * point: the use cases below depend on these interfaces, the adapters in
 * `infrastructure/` implement them, and the composition root is the only module
 * that knows which implementation is in play. Swapping the transport, or
 * standing a use case up against a fake in a test, touches nothing else.
 */

export interface SessionRepository {
  list(): Promise<readonly SessionSummary[]>
  tree(): Promise<readonly ForkNode[]>
  create(systemPrompt?: string): Promise<SessionId>
  /** The session folded to a point. HEAD and a scrubbed point are one call. */
  read(id: SessionId, at: ScrubPoint): Promise<SessionProjection>
  log(id: SessionId): Promise<readonly LogEntry[]>
  fork(id: SessionId, at: EventIndex): Promise<SessionId>
  /** Hand this session's files back to its project and stop working here. */
  release(id: SessionId): Promise<boolean>
}

export interface WorkspaceRepository {
  readFile(id: SessionId, path: FilePath, at: ScrubPoint): Promise<string>
  history(id: SessionId, path: FilePath): Promise<readonly FileRevision[]>
}

export interface LessonRepository {
  parse(
    id: SessionId,
    path: FilePath,
    audience: ComponentAudience,
    at: ScrubPoint,
  ): Promise<LessonDocument>
  /** Keyed by component id: ids are unique within a document, and the caller
   *  already holds the path. */
  progress(id: SessionId, path: FilePath): Promise<ReadonlyMap<ComponentId, ItemProgress>>
  /** The browser cannot mark an answer — it posts one and renders the reply. */
  submitAttempt(
    id: SessionId,
    input: {
      path: FilePath
      componentId: ComponentId
      response: AttemptResponse
      at: ScrubPoint
    },
  ): Promise<Verdict>
  /** Sends the whole set of ticks, not the one that changed: absolute state
   *  means a dropped request costs one stale render rather than a box that is
   *  ticked in the log and clear on the screen forever. */
  saveChecklist(
    id: SessionId,
    input: { path: FilePath; componentId: ComponentId; checked: readonly number[]; at: ScrubPoint },
  ): Promise<void>
}

export interface TurnRepository {
  send(id: SessionId, input: string): Promise<TurnRange | null>
  cancel(id: SessionId): Promise<{ readonly cancelled: boolean; readonly settled: boolean }>
  /** Whether a turn is running, as the server currently believes.
   *  Advisory: see `TurnEndLedger` for why a positive answer is not trusted
   *  unconditionally. */
  current(id: SessionId): Promise<RunningTurn>
  /** Provisional content for the turn in flight, for a tab that missed the
   *  frames — they carry no feed position, so nothing can replay them. */
  activity(id: SessionId): Promise<{
    readonly running: readonly ActivityEntry[]
    readonly discarded: readonly ActivityEntry[]
  }>
}

export interface RunningTurn {
  readonly running: boolean
  readonly turnIndex: number | null
  readonly startedAt: string | null
  readonly elapsedSeconds: number | null
}

export interface ApprovalRepository {
  pending(id: SessionId): Promise<readonly Approval[]>
  decide(id: SessionId, approvalId: ApprovalId, decision: ApprovalDecision): Promise<void>
}

/** What the agent may do without asking.
 *
 * The asymmetry in these three signatures is the API's, not an oversight, and
 * it is worth stating because it is surprising: the read takes no session
 * because there is no per-session answer to give, while the writes take one
 * because the audit record — `AutonomyChanged` — lands on a session's stream.
 * The session in a write is *who is answering for this change*, not where it
 * applies. It applies everywhere in the process.
 *
 * Every write returns the whole policy, so one flipped switch needs no second
 * request, and so a view whose `levels` went stale behind another tab's write
 * is corrected by its own next write.
 */
export interface AutonomyRepository {
  /** Rejects when this build has no policy wired up, which a caller must
   *  distinguish from "everything is auto". */
  read(): Promise<AutonomyPolicyView>
  /** `level` and `tool` are plain strings so a bad value reaches the server's
   *  own validation and comes back as its message, naming the offending value,
   *  rather than being swallowed by a type this build made up. */
  setLevel(id: SessionId, tool: string, level: string): Promise<AutonomyPolicyView>
  /** Autos every gated tool. Stage gates are excluded unless asked for: their
   *  floor is the workflow review gate, and auto-ing them lets a run cross
   *  every stage boundary with nobody looking. */
  allowAll(id: SessionId, includeStageGates: boolean): Promise<AutonomyChange>
}

export interface ProjectRepository {
  list(): Promise<readonly Project[]>
  presets(): Promise<readonly WorkflowPreset[]>
  create(name: string): Promise<ProjectId>
  chooseWorkflow(id: ProjectId, presetId: string): Promise<string>
  /** `takeOver` ends the holding session first. */
  join(id: ProjectId, takeOver: boolean): Promise<{ sessionId: SessionId; warning: string | null }>
  delete(id: ProjectId, releaseHolder: boolean): Promise<void>
  course(id: ProjectId): Promise<Course>
}

export interface ResearchRepository {
  /** Resolves to `null` when nothing is running, and rejects with
   *  `ResearchDisabledError` when this instance was not wired for runs at all —
   *  two different meanings the API expresses with the same status code. */
  current(id: ProjectId): Promise<ResearchRun | null>
  start(id: ProjectId, maxRounds: number | null): Promise<ResearchRun>
  cancel(id: ProjectId): Promise<boolean>
}

export interface TopicRepository {
  /** Every topic this project tracks, ranked on nothing — the queue does
   *  that, with `byUrgency`. */
  list(projectId: ProjectId): Promise<readonly TopicView[]>
  read(projectId: ProjectId, topicId: TopicId): Promise<TopicDetail>
  /** Rejects with a 422 `ApiError` for a blank or whitespace-only
   *  justification, and a 409 `ApiError` for re-selecting the topic's
   *  current status — the domain aggregate refuses both as no-ops on the
   *  audit trail, not failures the client should paper over. */
  setStatus(
    projectId: ProjectId,
    topicId: TopicId,
    toStatus: TopicStatus,
    justification: string,
  ): Promise<TopicDetail>
  addSubQuestion(
    projectId: ProjectId,
    topicId: TopicId,
    key: string,
    question: string,
  ): Promise<TopicDetail>
  resolveSubQuestion(
    projectId: ProjectId,
    topicId: TopicId,
    key: string,
    answer: string,
  ): Promise<TopicDetail>
  /** Start one seeding turn that names this project's first topics for
   *  `subject`. The topics it opens need no reading here -- `open_topic`
   *  appends to the log, so the existing `topics` list query invalidates on
   *  those frames and the new topics arrive on their own; `seedStatus`
   *  below answers only "is a run in flight, and how did the last one go".
   *  Rejects with a 409 `ApiError` when a run is already active on this
   *  project -- one at a time, refused rather than raced. */
  startSeed(projectId: ProjectId, subject: string, maxTopics: number): Promise<SeedingRun>
  /** The current or most recently finished seeding run, for a tab that
   *  arrived mid-run or reconnected after one. These frames carry no feed
   *  position and cannot replay off `Last-Event-ID` -- see `seeding.py`'s
   *  module docstring -- so this catch-up read is the only way back. */
  seedStatus(
    projectId: ProjectId,
  ): Promise<{ readonly current: SeedingRun | null; readonly last: SeedingRun | null }>
}

export interface DocumentRepository {
  /** Every source this project has stored, dropped ones included -- the
   *  corpus keeps them on purpose, as an audit trail, and hiding them here
   *  would misreport what the project holds. */
  list(projectId: ProjectId): Promise<readonly DocumentSummary[]>
  /** One document's text, or a `start`/`end` range of it. Omitting `range`
   *  reads the whole document; the server clamps a range past the end
   *  rather than refusing it, and the offsets in the result are what it
   *  actually returned. */
  read(projectId: ProjectId, sourceId: SourceId, range?: DocumentRange): Promise<DocumentText>
}

export interface DocumentRange {
  readonly start?: number
  readonly end?: number
}

export interface GraphRepository {
  /** Entities matching a name substring and, optionally, an exact entity
   *  type -- the browser's only entry point into the graph, since there is
   *  no route that lists every node. `truncated` on the result says whether
   *  the server held more back than the page returned. */
  search(projectId: ProjectId, name: string, entityType?: string): Promise<EntitySearchResult>
  /** `entityId` and what lies within `depth` hops of it. Rejects with a 422
   *  `ApiError` for a depth past the server's bound, which the caller must
   *  surface rather than clamp -- see the route's own docstring for why the
   *  server refuses instead of silently capping it. */
  neighborhood(projectId: ProjectId, entityId: string, depth?: number): Promise<Neighborhood>
}

export interface WorkerRepository {
  /** Everything in flight on a project. Rejects when this build has no
   *  roster, which a caller must distinguish from an empty one. */
  on(projectId: ProjectId): Promise<Roster>
}

export interface ExtractionRepository {
  /** Every frame the running extraction has emitted, and the last finished
   *  one's.
   *
   *  The only recovery path there is. These frames carry no feed position, so
   *  a reconnect cannot replay them off the log; without this a tab that
   *  arrived mid-ingest, or one whose socket dropped, would show a frozen pane
   *  indistinguishable from a stalled extraction. Two empty lists when nothing
   *  has run — an absent extraction is a state, not a missing resource. */
  on(projectId: ProjectId): Promise<{
    readonly current: readonly ExtractionFrame[]
    readonly last: readonly ExtractionFrame[]
  }>
}

export interface HealthRepository {
  summaries(): Promise<SummaryHealth>
  rebuildSummaries(): Promise<void>
}

/** The session list is answered from a projection, so it can be wrong in a way
 *  that reading it will never reveal. This is the only signal there is. */
export interface SummaryHealth {
  readonly healthy: boolean
  /** `false` means the projection stopped — a browser cannot fix that. */
  readonly following: boolean
  readonly failedEvents: number
}

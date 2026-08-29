import type { z } from 'zod'

import type { ItemProgress, Verdict } from '@domain/lesson/attempt.ts'
import type { ComponentBlock, DocumentBlock, LessonDocument } from '@domain/lesson/document.ts'
import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Approval, ApprovalDecision } from '@domain/approval/approval.ts'
import type { AutonomyChange, AutonomyPolicyView } from '@domain/autonomy/autonomy.ts'
import type { ExtractionFrame, ExtractionStage } from '@domain/knowledge/extraction.ts'
import type {
  Definition,
  DefinitionCitation,
  GraphLink,
  GraphNode,
  Neighborhood,
  Usage,
  WholeGraph,
} from '@domain/knowledge/graph.ts'
import type {
  AreaMember,
  Curriculum,
  LearningArea,
  LearningPath,
  PrerequisiteEdge,
} from '@domain/knowledge/curriculum.ts'
import type { AuthoringRun, AuthoringStatus } from '@domain/knowledge/authoring.ts'
import type { Blurb, Catalog, Category, CourseCandidate } from '@domain/knowledge/catalog.ts'
import type {
  CourseDetail,
  CourseFit,
  CourseText,
  FitEntity,
  Outline,
  RealizedCourse,
} from '@domain/knowledge/course.ts'
import type { Timeline, TimelineBand } from '@domain/knowledge/timeline.ts'
import type {
  ApprovalSummary,
  BrowserSession,
  BrowserSessionPage,
  FrictionSummary,
  InteractionLogHealth,
  InteractionPage,
  InteractionSummary,
  KindCount,
  LoggedInteraction,
  ProjectionFailure,
  ViewDwell,
} from '@domain/interaction/log.ts'
import type { Message, MessageRole } from '@domain/conversation/message.ts'
import type { Project, ProjectDetail } from '@domain/project/project.ts'
import type {
  DocumentText,
  MediaSummary,
  SourceSummary,
  TextSummary,
} from '@domain/research/document.ts'
import type { ExtractionOutcome, ExtractionQueueBoard } from '@domain/research/extraction-queue.ts'
import type {
  IgnoredMedia,
  MediaProposal,
  MediaProposalGroup,
  MediaProposalStatus,
} from '@domain/research/media-proposal.ts'
import type { Dispatch, DispatchStatus } from '@domain/research/dispatch.ts'
import type { TopicDocuments } from '@domain/research/topic-document.ts'
import type { SeedingRun, SeedingStatus } from '@domain/research/seeding.ts'
import type { TopicDetail, TopicStatus, TopicView } from '@domain/research/topic.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import type { ForkNode, SessionProjection, SessionSummary } from '@domain/session/session.ts'
import type { TurnRange } from '@domain/session/turn.ts'
import type { Roster } from '@domain/worker/worker.ts'
import type { FileRevision, WorkspaceFile } from '@domain/workspace/workspace-file.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import {
  ApprovalId,
  BrowserSessionId,
  ComponentId,
  InstallId,
  MessageId,
  ProjectId,
  SessionId,
  SourceId,
  TopicId,
} from '@domain/shared/identifier.ts'

import type * as dto from './dto.ts'
// A value import, unlike the type-only namespace above: `readExtractionFrame`
// parses at run time because a live frame is JSON nobody has validated yet.
import { extractionFrameDto } from './dto.ts'

/** The anti-corruption layer: wire shapes in, domain objects out.
 *
 * One module, one direction, no branching on anything but shape. Everything
 * above this reads `session.knowledgeAttached`; only this file knows the server
 * calls it `knowledge_attached`, and only this file has to change if it stops.
 */

type Dto<T extends z.ZodTypeAny> = z.infer<T>

export const toLogEntry = (raw: Dto<typeof dto.logEntryDto>): LogEntry => ({
  index: EventIndex(raw.index),
  type: raw.type,
  occurredAt: raw.occurred_at,
  summary: raw.summary ?? '',
  path: raw.path,
  turnIndex: raw.turn_index,
  isError: raw.is_error,
  cancelled: raw.cancelled,
})

const ROLES: Readonly<Record<string, MessageRole>> = {
  user: 'user',
  assistant: 'assistant',
  tool: 'tool',
}

export const toMessage = (raw: Dto<typeof dto.messageDto>): Message => ({
  // An unrecognised role renders as an assistant turn rather than vanishing:
  // the backend maps langchain's names already, and a new one is far more
  // likely to be model output than anything else.
  role: ROLES[raw.role] ?? 'assistant',
  content: raw.content,
  toolCalls: raw.tool_calls.map((call) => ({ name: call.name, args: call.args })),
  isError: raw.is_error,
})

export const toWorkspaceFile = (raw: Dto<typeof dto.workspaceFileDto>): WorkspaceFile => ({
  path: FilePath.of(raw.path),
  size: raw.size,
  revisions: raw.revisions,
})

export const toSession = (raw: Dto<typeof dto.sessionDto>): SessionProjection => ({
  id: SessionId(raw.id),
  projectId: raw.project_id ? ProjectId(raw.project_id) : null,
  holdsProject: raw.holds_project,
  knowledgeAttached: raw.knowledge_attached,
  modelName: raw.model_name,
  systemPrompt: raw.system_prompt,
  turnIndex: raw.turn_index,
  failedTurns: raw.failed_turns,
  forkedFrom: raw.forked_from ? SessionId(raw.forked_from) : null,
  forkedAt: raw.forked_at,
  eventCount: raw.event_count,
  compactedThrough: raw.compacted_through,
  compactionSummary: raw.compaction_summary,
  at: raw.at,
  files: raw.files.map(toWorkspaceFile),
  messages: raw.messages.map(toMessage),
})

export const toSessionSummary = (raw: Dto<typeof dto.sessionSummaryDto>): SessionSummary => ({
  id: SessionId(raw.id),
  projectId: ProjectId(raw.project_id),
  startedAt: raw.started_at,
  turns: raw.turns,
  files: raw.files,
  firstMessage: raw.first_message,
  forkedFrom: raw.forked_from ? SessionId(raw.forked_from) : null,
  forkedAt: raw.forked_at,
  failedTurns: raw.failed_turns,
})

export const toForkNode = (raw: dto.ForkNodeDto): ForkNode => ({
  ...toSessionSummary(raw),
  children: raw.children.map(toForkNode),
})

export const toFileRevision = (raw: Dto<typeof dto.fileRevisionDto>): FileRevision => ({
  index: EventIndex(raw.index),
  type: raw.type,
  occurredAt: raw.occurred_at,
  content: raw.content,
  oldString: raw.old_string,
  newString: raw.new_string,
  replaceAll: raw.replace_all,
})

const toDocumentBlock = (raw: Dto<typeof dto.documentBlockDto>): DocumentBlock => {
  if (raw.kind === 'markdown') return { kind: 'markdown', text: raw.text }
  const block: ComponentBlock = {
    kind: 'component',
    id: ComponentId(raw.id),
    type: raw.type,
    data: raw.data,
    raw: raw.raw,
    lang: raw.lang,
    unknown: raw.unknown,
    errors: raw.errors.map((error) => ({ path: error.path, message: error.message })),
    withheld: raw.withheld,
    resolved: raw.resolved,
  }
  return block
}

export const toLessonDocument = (raw: Dto<typeof dto.lessonDocumentDto>): LessonDocument => ({
  blocks: raw.blocks.map(toDocumentBlock),
})

export const toItemProgress = (raw: Dto<typeof dto.itemProgressDto>): ItemProgress => ({
  attempts: raw.attempts,
  correct: raw.correct,
  bestScore: raw.best_score,
  lastScore: raw.last_score,
  checked: raw.checked,
})

export const toProgressMap = (
  raw: Dto<typeof dto.progressDto>,
): ReadonlyMap<ComponentId, ItemProgress> =>
  new Map(
    Object.entries(raw.items).map(([id, record]) => [ComponentId(id), toItemProgress(record)]),
  )

/** One `ReadonlyMap` per turn, keyed `turn/{position}`.
 *
 * A `Map` inside rather than a plain record because that is exactly what
 * `useAttemptMachine`'s `stored` port takes, so an exchange hands its own entry
 * straight through with no adaptation at the call site. The outer level stays a
 * record: it is looked up by a string the caller builds, never iterated. */
export const toDialogueProgress = (
  raw: Dto<typeof dto.dialogueProgressDto>,
): Readonly<Record<string, ReadonlyMap<ComponentId, ItemProgress>>> =>
  Object.fromEntries(
    Object.entries(raw.items).map(([turn, items]) => [
      turn,
      new Map(
        Object.entries(items).map(([id, record]) => [ComponentId(id), toItemProgress(record)]),
      ),
    ]),
  )

export const toVerdict = (raw: Dto<typeof dto.verdictDto>): Verdict => ({
  correct: raw.correct,
  score: raw.score,
  feedback: raw.feedback,
  rationale: raw.rationale,
  correctOptions: raw.correct_options,
  blanks: raw.blanks.map((blank) => ({
    blank: blank.blank,
    correct: blank.correct,
    answer: blank.answer,
  })),
  progress: raw.progress ? toItemProgress(raw.progress) : null,
})

/** A turn reports exactly where it landed. Both bounds or nothing: a range with
 *  one end is not a range, and the caller's fallback ("turn complete", no chip)
 *  is correct for that case. */
export const toTurnRange = (raw: Dto<typeof dto.turnResultDto>): TurnRange | null => {
  if (typeof raw.from_index !== 'number' || typeof raw.to_index !== 'number') return null
  return {
    turnIndex: raw.turn_index,
    from: EventIndex(raw.from_index),
    to: EventIndex(raw.to_index),
  }
}

export const toActivityEntry = (raw: Dto<typeof dto.activityEntryDto>): ActivityEntry => ({
  messageId: MessageId(raw.message_id),
  sessionId: SessionId(raw.session_id),
  kind: raw.kind,
  text: raw.text,
  payload: raw.payload,
})

const KNOWN_DECISIONS: readonly ApprovalDecision[] = ['approve', 'edit', 'reject', 'respond']

const isKnownDecision = (value: string): value is ApprovalDecision =>
  (KNOWN_DECISIONS as readonly string[]).includes(value)

export const toApproval = (raw: Dto<typeof dto.approvalDto>): Approval => ({
  id: ApprovalId(raw.id),
  sessionId: SessionId(raw.session_id),
  toolName: raw.tool_name,
  description: raw.description,
  args: raw.args,
  // A decision this build does not know is dropped rather than carried
  // through. Passing it on would render a button that posts a `type` the
  // server rejects — a control that fails when pressed is worse than one that
  // was never offered, because the gate stays open either way and only the
  // second wastes the reviewer's trust.
  allowedDecisions: raw.allowed_decisions.filter(isKnownDecision),
})

export const toProject = (raw: Dto<typeof dto.projectDto>): Project => ({
  id: ProjectId(raw.id),
  name: raw.name,
  activeSessionId: raw.active_session_id ? SessionId(raw.active_session_id) : null,
  tipAtEvent: raw.tip_at_event,
})

/** The row, plus the one field only the detail route answers.
 *
 * Built on `toProject` rather than repeating it: the two shapes came apart
 * over `reading_head_session_id` and nothing else, and a second literal here
 * is how they come apart over a field nobody meant to split. */
export const toProjectDetail = (raw: Dto<typeof dto.projectDetailDto>): ProjectDetail => ({
  ...toProject(raw),
  readingHeadSessionId: raw.reading_head_session_id ? SessionId(raw.reading_head_session_id) : null,
})

/** An ISO-8601 timestamp as epoch milliseconds, or null.
 *
 * Null stays null rather than defaulting to now: a worker with no start time
 * would otherwise render as "0s elapsed", which reads as having just begun.
 */
const toEpoch = (raw: string | null): number | null => {
  if (!raw) return null
  const parsed = Date.parse(raw)
  return Number.isNaN(parsed) ? null : parsed
}

export const toRoster = (raw: Dto<typeof dto.rosterDto>): Roster => ({
  projectId: ProjectId(raw.project_id),
  workers: raw.workers.map((worker) => ({
    // The server's vocabulary, narrowed. An unrecognised kind renders as a
    // plain row rather than being dropped: a worker this build cannot label
    // is still a worker, and hiding it is the failure mode that matters.
    //
    // `dispatch` is listed explicitly rather than left to the fallback. The
    // fallback is `turn`, which is not a neutral label but a different
    // specific kind -- a dispatch arriving from a newer server was being named
    // a turn on screen, which is a confident wrong answer rather than a vague
    // one. Anything genuinely unknown still lands on `turn`, and that remains
    // the weakest part of this mapping.
    kind:
      worker.kind === 'run' || worker.kind === 'extraction' || worker.kind === 'dispatch'
        ? worker.kind
        : 'turn',
    ref: worker.ref,
    detail: worker.detail,
    sessionId: worker.session_id ? SessionId(worker.session_id) : null,
    parent: worker.parent,
    startedAt: toEpoch(worker.started_at),
  })),
  idleSessionIds: raw.idle_session_ids.map((id) => SessionId(id)),
})

/** A `Map` rather than the record the wire sent, so a tool named `toString` or
 *  `constructor` cannot be answered by `Object.prototype` — a plain-object
 *  lookup would report a level for a tool the server never mentioned. */
export const toAutonomy = (raw: Dto<typeof dto.autonomyDto>): AutonomyPolicyView => ({
  levels: new Map(Object.entries(raw.levels)),
  gated: raw.gated,
})

export const toAutonomyChange = (raw: Dto<typeof dto.autonomyChangeDto>): AutonomyChange => ({
  changed: new Map(Object.entries(raw.changed)),
  policy: toAutonomy(raw),
})

/** The stages this build knows, in the order the ingest walks them. */
const STAGES: readonly ExtractionStage[] = [
  'storing',
  'extracting',
  'extracted',
  'consolidating',
  'consolidated',
  'failed',
  // Not in the ingest's order, because they are not on the ingest's walk:
  // perception is a separate job reporting through the same channel, and it
  // emits `perceiving` then either `perceived` or `failed`. Listed last rather
  // than interleaved so the sequence above still reads as one walk.
  'perceiving',
  'perceived',
]

/** An unrecognised stage reads as `extracting` rather than being dropped.
 *
 * `extracting` and not, say, `failed`, because the two terminal stages end the
 * extraction: mistaking a stage this build has not heard of for a terminal one
 * would file a running extraction under "last" and freeze the pane on it. A
 * wrong non-terminal label is a cosmetic error; a wrong terminal one is not. */
const toStage = (raw: string): ExtractionStage =>
  STAGES.find((stage) => stage === raw) ?? 'extracting'

export const toExtractionFrame = (raw: Dto<typeof dto.extractionFrameDto>): ExtractionFrame => ({
  type: 'Extraction',
  projectId: raw.project_id,
  sourceId: raw.source_id,
  stage: toStage(raw.stage),
  detail: raw.detail,
  entities: raw.entities,
  relationships: raw.relationships,
  domain: raw.domain,
  domainConfidence: raw.domain_confidence,
  index: raw.index,
  total: raw.total,
  modelCalls: raw.model_calls,
})

/** The same mapping for a live frame, which arrives unvalidated.
 *
 * Null rather than a throw, and null rather than a partly-filled frame: an
 * extraction frame off the socket is JSON nobody has checked, and folding a
 * half-shaped one would put `undefined` where a count belongs and render as
 * progress that never happened. This is also the seam that keeps zod out of
 * the store, which is application-layer and should not know the wire shape. */
export const readExtractionFrame = (raw: unknown): ExtractionFrame | null => {
  const parsed = extractionFrameDto.safeParse(raw)
  return parsed.success ? toExtractionFrame(parsed.data) : null
}

const SEED_STATUSES: readonly SeedingStatus[] = ['running', 'done', 'failed']

/** An unrecognised status reads as `running`, the same reasoning as
 *  `toStage`'s fallback: `running` is the one status that keeps the control
 *  disabled and shows the run as still in flight, which is the safer
 *  misreading of the two -- a build talking to a server with a fourth status
 *  should stay cautious rather than declare an unknown outcome finished. */
const toSeedStatus = (raw: string): SeedingStatus =>
  SEED_STATUSES.find((status) => status === raw) ?? 'running'

export const toSeedingRun = (raw: Dto<typeof dto.seedingFrameDto>): SeedingRun => ({
  runId: raw.run_id,
  status: toSeedStatus(raw.status),
  subject: raw.subject,
  reply: raw.reply,
  detail: raw.detail,
})

const DISPATCH_STATUSES: readonly DispatchStatus[] = [
  'queued',
  'running',
  'done',
  'failed',
  'cancelled',
]

/** An unrecognised status reads as `running` rather than being dropped.
 *
 * `running` and not `queued`, because the two differ in what the UI offers:
 * a row believing itself queued when the server has moved on shows a
 * position that will never change, while one believing itself running shows
 * a spinner that a later frame corrects. Guessing toward the state that
 * self-corrects is the cheaper mistake — the same reasoning `toSeedStatus`
 * applies to its own default.
 */
const toDispatchStatus = (raw: string): DispatchStatus =>
  DISPATCH_STATUSES.find((status) => status === raw) ?? 'running'

export const toDispatch = (raw: Dto<typeof dto.dispatchFrameDto>): Dispatch => ({
  dispatchId: raw.dispatch_id,
  topicId: raw.topic_id,
  action: raw.action,
  status: toDispatchStatus(raw.status),
  question: raw.question,
  position: raw.position,
  path: raw.path,
  sessionId: raw.session_id,
  detail: raw.detail,
})

export const toTopicDocuments = (raw: Dto<typeof dto.topicDocumentsDto>): TopicDocuments => ({
  directory: raw.directory,
  sessionId: raw.session_id ? SessionId(raw.session_id) : null,
  documents: raw.documents.map((document) => ({
    path: FilePath.of(document.path),
    name: document.name,
  })),
})

/** The statuses this build knows. */
const TOPIC_STATUSES: readonly TopicStatus[] = [
  'open',
  'investigating',
  'answered',
  'not_pursuing',
  'superseded',
]

/** An unrecognised status reads as `open` rather than being dropped.
 *
 * `open`, not one of the closed statuses, for the reason `toStage` picks
 * `extracting`: mistaking a status this build has not heard of for a closed
 * one would sink a live topic to the bottom of the queue, which is the wrong
 * direction to fail in — a topic that still needs a look belongs where it
 * will be seen. */
const toTopicStatus = (raw: string): TopicStatus =>
  TOPIC_STATUSES.find((status) => status === raw) ?? 'open'

export const toTopicView = (raw: Dto<typeof dto.topicDto>): TopicView => ({
  topicId: TopicId(raw.topic_id),
  question: raw.question,
  status: toTopicStatus(raw.status),
  sources: raw.sources,
  findings: raw.findings,
  openSubQuestions: raw.open_sub_questions,
  triggers: raw.triggers,
  needsAttention: raw.needs_attention,
  isBlocked: raw.is_blocked,
})

export const toTopicDetail = (raw: Dto<typeof dto.topicDetailDto>): TopicDetail => ({
  topicId: TopicId(raw.topic_id),
  question: raw.question,
  status: toTopicStatus(raw.status),
  sources: raw.sources,
  findings: raw.findings,
  openSubQuestions: raw.open_sub_questions,
  triggers: raw.triggers,
  needsAttention: raw.needs_attention,
  isBlocked: raw.is_blocked,
  rationale: raw.rationale,
  scope: raw.scope,
  subQuestions: raw.sub_questions.map((sub) => ({
    key: sub.key,
    question: sub.question,
    answer: sub.answer,
    resolved: sub.resolved,
  })),
  sourceIds: raw.source_ids,
  findingNotes: raw.finding_notes,
  contested: raw.contested,
})

/** The provenance half, shared by both kinds. Split out so the two branches
 *  below differ only in the fields that actually differ -- the failure mode of
 *  spelling all nine twice is one of them quietly drifting. */
const toSourceProvenance = (raw: Dto<typeof dto.documentDto>) => ({
  sourceId: SourceId(raw.source_id),
  sha256: raw.sha256,
  uri: raw.uri,
  title: raw.title,
  publishedAt: raw.published_at,
  note: raw.note,
  fetchedAt: raw.fetched_at,
  droppedReason: raw.dropped_reason,
  extracted: raw.extracted,
})

/** Discriminated on `kind` rather than copying whatever fields happen to be
 *  present, so the absence the wire encodes survives the crossing: a media row
 *  gets no `charCount` at all here, not a zero. */
export const toSourceSummary = (raw: Dto<typeof dto.documentDto>): SourceSummary =>
  raw.kind === 'media'
    ? {
        ...toSourceProvenance(raw),
        kind: 'media',
        mediaType: raw.media_type,
        byteCount: raw.byte_count,
      }
    : {
        ...toSourceProvenance(raw),
        kind: 'text',
        charCount: raw.char_count,
        derivedFrom: raw.derived_from,
        degradations: raw.degradations,
      }

export const toTextSummary = (raw: Dto<typeof dto.textSourceDto>): TextSummary => ({
  ...toSourceProvenance(raw),
  kind: 'text',
  charCount: raw.char_count,
  derivedFrom: raw.derived_from,
  degradations: raw.degradations,
})

export const toMediaSummary = (raw: Dto<typeof dto.mediaSourceDto>): MediaSummary => ({
  ...toSourceProvenance(raw),
  kind: 'media',
  mediaType: raw.media_type,
  byteCount: raw.byte_count,
})

/** The five statuses `decide`'s transition table can reach, plus a fallback
 *  for any this build has never heard of -- `mediaProposalDto` deliberately
 *  leaves `status` as a bare string so an older console does not fail the
 *  whole listing over a status a newer server started sending; this is the
 *  one place that narrows it, and it narrows to `'proposed'` rather than
 *  throwing, which puts the row back in front of a person to judge instead
 *  of dropping it from a list that is supposed to be everything. */
const KNOWN_MEDIA_PROPOSAL_STATUSES: readonly MediaProposalStatus[] = [
  'proposed',
  'accepted',
  'rejected',
  'stored',
  'failed',
]

const toMediaProposalStatus = (raw: string): MediaProposalStatus =>
  (KNOWN_MEDIA_PROPOSAL_STATUSES as readonly string[]).includes(raw)
    ? (raw as MediaProposalStatus)
    : 'proposed'

export const toMediaProposal = (raw: Dto<typeof dto.mediaProposalDto>): MediaProposal => ({
  proposalId: raw.proposal_id,
  needId: raw.need_id,
  topicId: raw.topic_id,
  pageUrl: raw.page_url,
  assetUrl: raw.asset_url,
  thumbnailUrl: raw.thumbnail_url,
  kind: raw.kind,
  title: raw.title,
  reason: raw.reason,
  query: raw.query,
  status: toMediaProposalStatus(raw.status),
  note: raw.note ?? '',
  sourceId: raw.source_id === null ? null : SourceId(raw.source_id),
  error: raw.error,
})

export const toMediaProposalGroup = (
  raw: Dto<typeof dto.mediaProposalGroupDto>,
): MediaProposalGroup => ({
  needId: raw.need_id,
  needDescription: raw.need_description,
  proposals: raw.proposals.map(toMediaProposal),
})

export const toIgnoredMedia = (raw: Dto<typeof dto.ignoredMediaDto>): IgnoredMedia => ({
  assets: raw.assets,
  hosts: raw.hosts,
})

export const toExtractionOutcome = (
  raw: Dto<typeof dto.extractionOutcomeDto>,
): ExtractionOutcome => ({
  sourceId: SourceId(raw.source_id),
  status: raw.status,
  detail: raw.detail,
  entities: raw.entities,
  relationships: raw.relationships,
})

export const toExtractionQueueBoard = (
  raw: Dto<typeof dto.extractionQueueDto>,
): ExtractionQueueBoard => ({
  running: raw.running === null ? null : SourceId(raw.running),
  queued: raw.queued.map(SourceId),
  finished: raw.finished.map(toExtractionOutcome),
})

export const toDocumentText = (raw: Dto<typeof dto.documentTextDto>): DocumentText => ({
  ...toTextSummary(raw),
  text: raw.text,
  start: raw.start,
  end: raw.end,
})

export const toGraphNode = (raw: Dto<typeof dto.graphEntityDto>): GraphNode => ({
  id: raw.entity_id,
  name: raw.name,
  entityType: raw.entity_type,
  inferred: raw.inferred,
  temporal: raw.temporal,
})

export const toGraphLink = (raw: Dto<typeof dto.graphRelationshipDto>): GraphLink => ({
  source: raw.source_id,
  target: raw.target_id,
  relationshipType: raw.relationship_type,
  inferred: raw.inferred,
  derivation: raw.derivation,
})

export const toWholeGraph = (raw: Dto<typeof dto.graphWholeDto>): WholeGraph => ({
  entities: raw.entities.map(toGraphNode),
  relationships: raw.relationships.map(toGraphLink),
  truncated: raw.truncated,
  inferredTruncated: raw.inferred_truncated,
})

export const toUsage = (raw: Dto<typeof dto.usageDto>): Usage => ({
  sourceId: raw.source_id,
  start: raw.start,
  end: raw.end,
  text: raw.text,
  score: raw.score,
})

export const toDefinitionCitation = (
  raw: Dto<typeof dto.definitionCitationDto>,
): DefinitionCitation => ({
  sourceId: raw.source_id,
  start: raw.start,
  end: raw.end,
  atSeconds: raw.at_seconds,
})

export const toDefinition = (raw: Dto<typeof dto.definitionDto>): Definition => ({
  text: raw.text,
  citations: raw.citations.map(toDefinitionCitation),
  model: raw.model,
  generatedAt: raw.generated_at,
  stale: raw.stale,
})

export const toNeighborhood = (raw: Dto<typeof dto.graphNeighborhoodDto>): Neighborhood => ({
  root: toGraphNode(raw.root),
  entities: raw.entities.map(toGraphNode),
  relationships: raw.relationships.map(toGraphLink),
})

export const toTimelineBand = (raw: Dto<typeof dto.timelineBandDto>): TimelineBand => ({
  id: raw.entity_id,
  name: raw.name,
  entityType: raw.entity_type,
  extent: raw.extent,
  start: raw.start,
  end: raw.end,
  precision: raw.precision,
  uncertainty: raw.uncertainty,
})

export const toTimeline = (raw: Dto<typeof dto.timelineDto>): Timeline => ({
  bands: raw.bands.map(toTimelineBand),
  undatedCount: raw.undated_count,
  truncated: raw.truncated,
})

export const toAreaMember = (raw: Dto<typeof dto.areaMemberDto>): AreaMember => ({
  entityId: raw.entity_id,
  name: raw.name,
  entityType: raw.entity_type,
  centrality: raw.centrality,
  temporal: raw.temporal,
})

export const toLearningArea = (raw: Dto<typeof dto.learningAreaDto>): LearningArea => ({
  slug: raw.slug,
  title: raw.title,
  summary: raw.summary,
  size: raw.size,
  truncatedMembers: raw.truncated_members,
  members: raw.members.map(toAreaMember),
})

export const toPrerequisiteEdge = (raw: Dto<typeof dto.prerequisiteEdgeDto>): PrerequisiteEdge => ({
  before: raw.before,
  after: raw.after,
  weight: raw.weight,
  reason: raw.reason,
  contested: raw.contested,
})

export const toLearningPath = (raw: Dto<typeof dto.learningPathDto>): LearningPath => ({
  slug: raw.slug,
  title: raw.title,
  destination: raw.destination,
  // `areas` on the wire, `areaSlugs` here. Renamed deliberately: the field
  // holds slugs, and a client property called `areas` beside `Curriculum.areas`
  // -- which holds whole areas -- is two different types one letter apart.
  areaSlugs: raw.areas,
  edges: raw.edges.map(toPrerequisiteEdge),
})

export const toCurriculum = (raw: Dto<typeof dto.curriculumDto>): Curriculum => ({
  areas: raw.areas.map(toLearningArea),
  path: toLearningPath(raw.path),
  derivedFrom: {
    entities: raw.derived_from.entities,
    relationships: raw.derived_from.relationships,
    passages: raw.derived_from.passages,
    semanticEdges: raw.derived_from.semantic_edges,
    usedEmbeddings: raw.derived_from.used_embeddings,
    truncated: raw.derived_from.truncated,
  },
})

export const toAuthoringRun = (raw: Dto<typeof dto.authoringFrameDto>): AuthoringRun => ({
  runId: raw.run_id,
  status: raw.status,
  kind: raw.kind,
  targets: raw.targets,
  completed: raw.completed,
  sessions: raw.sessions,
  current: raw.current,
  failures: raw.failures.map((f) => ({ target: f.target, detail: f.detail })),
})

export const toAuthoringStatus = (raw: Dto<typeof dto.authoringStatusDto>): AuthoringStatus => ({
  current: raw.current === null ? null : toAuthoringRun(raw.current),
  last: raw.last === null ? null : toAuthoringRun(raw.last),
})

const toCandidateBlurb = (raw: Dto<typeof dto.candidateBlurbDto>): Blurb => ({
  text: raw.text,
  membershipHash: raw.membershipHash,
  generatedAt: raw.generatedAt,
})

export const toCourseCandidate = (raw: Dto<typeof dto.courseCandidateDto>): CourseCandidate => ({
  slug: raw.slug,
  title: raw.title,
  category: raw.category,
  prominence: raw.prominence,
  size: raw.size,
  membershipHash: raw.membershipHash,
  anchors: raw.anchors.map(toAreaMember),
  art: raw.art,
  blurb: raw.blurb === null ? null : toCandidateBlurb(raw.blurb),
  featuredRank: raw.featuredRank,
})

export const toCategory = (raw: Dto<typeof dto.categoryDto>): Category => ({
  key: raw.key,
  label: raw.label,
  candidates: raw.candidates.map(toCourseCandidate),
})

export const toCatalog = (raw: Dto<typeof dto.catalogDto>): Catalog => ({
  sections: {
    hero: raw.hero.map(toCourseCandidate),
    highlights: raw.highlights.map(toCourseCandidate),
    filed: raw.filed.map(toCategory),
  },
  categories: new Map(Object.entries(raw.categories)),
  unplaceableFeatured: raw.unplaceableFeatured,
  unnamedCount: raw.unnamedCount,
  orphanedCourses: raw.orphanedCourses,
  derivedFrom: {
    entities: raw.derived_from.entities,
    relationships: raw.derived_from.relationships,
  },
})

const toOutline = (raw: Dto<typeof dto.outlineDto>): Outline => ({
  promise: raw.promise,
  sections: raw.sections.map((s) => ({ heading: s.heading, summary: s.summary })),
  membershipHash: raw.membershipHash,
  model: raw.model,
  generatedAt: raw.generatedAt,
})

const toFitEntity = (raw: Dto<typeof dto.fitEntityDto>): FitEntity => ({
  entityId: raw.entity_id,
  name: raw.name,
})

const toCourseFit = (raw: Dto<typeof dto.courseFitDto>): CourseFit => ({
  kept: raw.kept.map(toFitEntity),
  added: raw.added.map(toFitEntity),
  dropped: raw.dropped,
  orphaned: raw.orphaned,
})

const toRealizedCourse = (raw: Dto<typeof dto.realizedCourseDto>): RealizedCourse => ({
  realizedAt: raw.realizedAt,
  membershipHash: raw.membershipHash,
  fit: toCourseFit(raw.fit),
  authoredSessionId: raw.authoredSessionId,
})

/** `courseTextDto` to the domain shape. A pass-through in every field, and
 *  kept anyway rather than letting the DTO reach the component: the console's
 *  presentation layer imports from `@domain`, and a component typed on a zod
 *  inference would tie the page's props to the wire. */
export const toCourseText = (raw: Dto<typeof dto.courseTextDto>): CourseText => ({
  slug: raw.slug,
  state: raw.state,
  sessionId: raw.sessionId,
  unitPath: raw.unitPath,
  unit: raw.unit,
  lessons: raw.lessons.map((file) => ({ path: file.path, markdown: file.markdown })),
})

export const toCourseDetail = (raw: Dto<typeof dto.courseDetailDto>): CourseDetail => ({
  candidate: toCourseCandidate(raw.candidate),
  outline: raw.outline === null ? null : toOutline(raw.outline),
  members: raw.members.map(toAreaMember),
  course: raw.course === null ? null : toRealizedCourse(raw.course),
})

/* The interaction log's read side. */

/** A validated instant string to a `Date`.
 *
 * Total, because `dto.ts`'s `instant` refinement has already rejected
 * anything `Date.parse` cannot read -- the check is there rather than here so
 * the failure names the endpoint and the field. */
const toInstant = (raw: string): Date => new Date(raw)

const toMaybeInstant = (raw: string | null): Date | null => (raw === null ? null : new Date(raw))

/** A `{name: count}` record to an ordered array.
 *
 * `Object.entries` and not a sort: the server sends `kinds` in its own
 * vocabulary order, zeros included, and that order is the readability of the
 * pane. Sorting here -- by name, or by count -- would throw away the one thing
 * the server took care to send, and would move a kind up the list on the day
 * somebody happened to use it. */
const toCounts = (raw: Readonly<Record<string, number>>): readonly KindCount[] =>
  Object.entries(raw).map(([kind, count]) => ({ kind, count }))

export const toProjectionFailure = (
  raw: Dto<typeof dto.interactionFailureDto>,
): ProjectionFailure => ({
  id: raw.id,
  eventType: raw.event_type,
  error: raw.error,
  failedAt: toMaybeInstant(raw.failed_at),
})

export const toInteractionLogHealth = (
  raw: Dto<typeof dto.interactionHealthDto>,
): InteractionLogHealth => ({
  collecting: raw.collecting,
  total: raw.total,
  firstAt: toMaybeInstant(raw.first_at),
  lastAt: toMaybeInstant(raw.last_at),
  kinds: toCounts(raw.kinds),
  failures: raw.failures.map(toProjectionFailure),
  installCount: raw.install_count,
  sessionCount: raw.session_count,
})

export const toLoggedInteraction = (
  raw: Dto<typeof dto.interactionEventDto>,
): LoggedInteraction => ({
  browserSessionId: BrowserSessionId(raw.browser_session_id),
  installId: InstallId(raw.install_id),
  seq: raw.seq,
  kind: raw.kind,
  view: raw.view,
  occurredAt: toInstant(raw.occurred_at),
  receivedAt: toMaybeInstant(raw.received_at),
  projectId: raw.project_id === null ? null : ProjectId(raw.project_id),
  sessionId: raw.session_id === null ? null : SessionId(raw.session_id),
  payload: raw.payload,
})

export const toBrowserSession = (raw: Dto<typeof dto.browserSessionRowDto>): BrowserSession => ({
  browserSessionId: BrowserSessionId(raw.browser_session_id),
  installId: InstallId(raw.install_id),
  startedAt: toMaybeInstant(raw.started_at),
  endedAt: toMaybeInstant(raw.ended_at),
  eventCount: raw.event_count,
  maxSeq: raw.max_seq,
  views: raw.views,
  projectIds: raw.project_ids.map(ProjectId),
  kinds: toCounts(raw.kinds),
})

export const toBrowserSessionPage = (
  raw: Dto<typeof dto.browserSessionPageDto>,
): BrowserSessionPage => ({
  sessions: raw.sessions.map(toBrowserSession),
  total: raw.total,
})

export const toInteractionPage = (
  raw: Dto<typeof dto.interactionEventPageDto>,
): InteractionPage => ({
  events: raw.events.map(toLoggedInteraction),
  total: raw.total,
  limit: raw.limit,
  offset: raw.offset,
})

export const toViewDwell = (raw: Dto<typeof dto.viewDwellDto>): ViewDwell => ({
  view: raw.view,
  entries: raw.entries,
  exits: raw.exits,
  dwellMsMedian: raw.dwell_ms_median,
  dwellMsP90: raw.dwell_ms_p90,
  hiddenMsMedian: raw.hidden_ms_median,
})

export const toFrictionSummary = (raw: Dto<typeof dto.frictionSummaryDto>): FrictionSummary => ({
  undone: raw.undone,
  retried: raw.retried,
  emptyResults: raw.empty_results,
  emptyByWhere: raw.empty_by_where.map((place) => ({ where: place.where, count: place.count })),
  repeatSearches: raw.repeat_searches,
})

export const toApprovalSummary = (raw: Dto<typeof dto.approvalSummaryDto>): ApprovalSummary => ({
  total: raw.total,
  expanded: raw.expanded,
  medianLatencyMs: raw.median_latency_ms,
  medianLatencyMsExpanded: raw.median_latency_ms_expanded,
  medianLatencyMsPlain: raw.median_latency_ms_plain,
  byDecision: Object.entries(raw.by_decision).map(([decision, count]) => ({ decision, count })),
})

export const toInteractionSummary = (
  raw: Dto<typeof dto.interactionSummaryDto>,
): InteractionSummary => ({
  byKind: toCounts(raw.by_kind),
  byView: raw.by_view.map(toViewDwell),
  friction: toFrictionSummary(raw.friction),
  approvals: toApprovalSummary(raw.approvals),
})

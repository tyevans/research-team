import type { z } from 'zod'

import type { ItemProgress, Verdict } from '@domain/lesson/attempt.ts'
import type { ComponentBlock, DocumentBlock, LessonDocument } from '@domain/lesson/document.ts'
import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Approval, ApprovalDecision, GateContext } from '@domain/approval/approval.ts'
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
import type { Timeline, TimelineBand } from '@domain/knowledge/timeline.ts'
import type { Message, MessageRole } from '@domain/conversation/message.ts'
import type {
  Course,
  StageProgress,
  StageStatus,
  ArtifactSlot,
  Provenance,
  Finding,
} from '@domain/project/course.ts'
import type { Project, WorkflowPreset } from '@domain/project/project.ts'
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
import type { ResearchRun } from '@domain/research/run.ts'
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
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import {
  ApprovalId,
  ComponentId,
  MessageId,
  ProjectId,
  RunId,
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

const toGateContext = (raw: Dto<typeof dto.gateContextDto>): GateContext => ({
  stage: raw.stage,
  findingsArtifact: raw.findings_artifact,
  artifactPaths: raw.artifact_paths,
  blocked: raw.blocked,
  artifactsReviewed: raw.artifacts_reviewed,
  linksReviewed: raw.links_reviewed,
  unimplementedChecks: raw.unimplemented_checks,
  unreadableArtifacts: raw.unreadable_artifacts,
  findings: raw.findings.map((finding) => ({
    check: finding.check,
    severity: finding.severity,
    message: finding.message,
    cites: finding.cites,
    suggestedEdit: finding.suggested_edit,
  })),
})

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
  context: raw.context ? toGateContext(raw.context) : null,
})

export const toProject = (raw: Dto<typeof dto.projectDto>): Project => ({
  id: ProjectId(raw.id),
  name: raw.name,
  activeSessionId: raw.active_session_id ? SessionId(raw.active_session_id) : null,
  tipAtEvent: raw.tip_at_event,
  workflow: raw.workflow,
  stage: raw.stage,
})

export const toPreset = (raw: Dto<typeof dto.presetDto>): WorkflowPreset => ({
  id: raw.id,
  name: raw.name,
  version: raw.version,
  description: raw.description,
  produces: raw.produces,
  stageCount: raw.stage_count,
  terminatesAt: raw.terminates_at,
  hasValueFilter: raw.has_value_filter,
  label: raw.label,
})

const toProvenance = (raw: Dto<typeof dto.provenanceDto>): Provenance => ({
  sources: raw.sources.map((span) => ({
    sourceId: SourceId(span.source_id),
    start: span.start,
    end: span.end,
  })),
  inferred: raw.inferred,
  unreadable: raw.unreadable,
  empty: raw.empty,
})

const toArtifactSlot = (raw: Dto<typeof dto.artifactSlotDto>): ArtifactSlot => ({
  path: raw.path,
  artifactType: raw.artifact_type,
  subtype: raw.subtype,
  cardinality: raw.cardinality,
  stageId: raw.stage_id,
  present: raw.present,
  hasFrontmatter: raw.has_frontmatter,
  missingFields: raw.missing_fields,
  provenance: raw.provenance ? toProvenance(raw.provenance) : null,
  bodyChars: raw.body_chars,
})

const toFinding = (raw: Dto<typeof dto.findingDto>): Finding => ({
  check: raw.check,
  severity: raw.severity,
  message: raw.message,
  cites: raw.cites,
  suggestedEdit: raw.suggested_edit,
})

const STAGE_STATUSES: readonly StageStatus[] = ['done', 'current', 'upcoming', 'unknown']

/** A status this build has not heard of is a stage it cannot place, which is
 *  what `unknown` already means -- `course.py`'s `_status` returns it for
 *  exactly that, a stage whose position cannot be resolved. So the fold reuses
 *  a meaning rather than inventing one, and `.rail-unknown` and `.chip-unknown`
 *  already draw it.
 *
 *  It draws it in `--k-failure` red, and that is the intended register rather
 *  than an accident of reuse: an unrecognised status means this console and the
 *  server disagree about the vocabulary, which is a deployment mismatch and
 *  should look like one. What it costs is the literal string -- a future
 *  `skipped` renders as "unknown" rather than as itself. That is the trade for
 *  a closed union, and the union is what stopped `todo` from being believed for
 *  as long as it was. */
const toStageStatus = (raw: string): StageStatus =>
  STAGE_STATUSES.includes(raw as StageStatus) ? (raw as StageStatus) : 'unknown'

const toStageProgress = (raw: Dto<typeof dto.stageProgressDto>): StageProgress => ({
  index: raw.index,
  id: raw.id,
  name: raw.name,
  kind: raw.kind,
  spine: raw.spine,
  scopeLevel: raw.scope_level,
  status: toStageStatus(raw.status),
  outputs: raw.outputs.map(toArtifactSlot),
  gateDecisions: raw.gate_decisions,
  reviewerRole: raw.reviewer_role,
  findingsReport: raw.findings_report,
})

export const toCourse = (raw: Dto<typeof dto.courseDto>, projectId: ProjectId): Course => ({
  projectId,
  projectName: raw.project_name,
  holdingSessionId: raw.holding_session_id ? SessionId(raw.holding_session_id) : null,
  preset: raw.preset,
  position: raw.position,
  stageCount: raw.stage_count,
  stages: raw.stages.map(toStageProgress),
  findings: raw.live_findings.map(toFinding),
  unimplementedChecks: raw.unimplemented_checks,
})

export const toRun = (raw: Dto<typeof dto.runDto>): ResearchRun => ({
  runId: RunId(raw.run_id),
  projectId: ProjectId(raw.project_id),
  sessionId: SessionId(raw.session_id),
  // No status at all is the 202 body: ids only, no fold yet. Modelled as an
  // absent progress rather than as zeroed counters, because a run reporting
  // "0 rounds" and one that has not been folded are different facts.
  progress:
    raw.status === undefined
      ? null
      : {
          status: raw.status,
          rounds: raw.rounds ?? 0,
          turns: raw.turns ?? 0,
          findings: raw.findings ?? 0,
          stopReason: raw.stop_reason ?? null,
          workingOn: raw.working_on ?? null,
          quietRounds: raw.quiet_rounds ?? 0,
          failures: raw.failures ?? 0,
          budget: {
            maxRounds: raw.budget?.max_rounds ?? null,
            quietRounds: raw.budget?.quiet_rounds ?? null,
          },
          readOnly: raw.read_only ?? false,
        },
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
    // `dispatch` and `stage` are listed explicitly rather than left to the
    // fallback. The fallback is `turn`, which is not a neutral label but a
    // different specific kind -- a dispatch arriving from a newer server was
    // being named a turn on screen, which is a confident wrong answer rather
    // than a vague one. Anything genuinely unknown still lands on `turn`, and
    // that remains the weakest part of this mapping.
    kind:
      worker.kind === 'run' ||
      worker.kind === 'extraction' ||
      worker.kind === 'dispatch' ||
      worker.kind === 'stage'
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
  stageGates: raw.stage_gates,
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
  // `fromNullable` is the whole reason `at` is not carried as a raw number:
  // it is what keeps "HEAD" from being spelled as `null` in a tenth place.
  at: ScrubPoint.fromNullable(raw.at),
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

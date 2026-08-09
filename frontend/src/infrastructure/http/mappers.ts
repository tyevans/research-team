import type { z } from 'zod'

import type { ItemProgress, Verdict } from '@domain/lesson/attempt.ts'
import type { ComponentBlock, DocumentBlock, LessonDocument } from '@domain/lesson/document.ts'
import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Approval } from '@domain/approval/approval.ts'
import type { AutonomyChange, AutonomyPolicyView } from '@domain/autonomy/autonomy.ts'
import type { ExtractionFrame, ExtractionStage } from '@domain/knowledge/extraction.ts'
import type { GraphLink, GraphNode, Neighborhood, WholeGraph } from '@domain/knowledge/graph.ts'
import type { Message, MessageRole } from '@domain/conversation/message.ts'
import type {
  Course,
  StageProgress,
  ArtifactSlot,
  Provenance,
  Finding,
} from '@domain/project/course.ts'
import type { Project, WorkflowPreset } from '@domain/project/project.ts'
import type { DocumentSummary, DocumentText } from '@domain/research/document.ts'
import type { ResearchRun } from '@domain/research/run.ts'
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
  projectId: raw.project_id ? ProjectId(raw.project_id) : null,
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

/** A flat session list rendered as a tree of roots.
 *
 * Used when `/api/tree` answers empty but sessions exist — the projection has
 * drifted, and a flat list is a truthful degradation where "no sessions" is a
 * lie. */
export const summariesAsForest = (summaries: readonly SessionSummary[]): readonly ForkNode[] =>
  summaries.map((summary) => ({ ...summary, children: [] }))

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

export const toApproval = (raw: Dto<typeof dto.approvalDto>): Approval => ({
  id: ApprovalId(raw.id),
  sessionId: SessionId(raw.session_id),
  toolName: raw.tool_name,
  description: raw.description,
  args: raw.args,
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

const toStageProgress = (raw: Dto<typeof dto.stageProgressDto>): StageProgress => ({
  index: raw.index,
  id: raw.id,
  name: raw.name,
  kind: raw.kind,
  spine: raw.spine,
  scopeLevel: raw.scope_level,
  status: raw.status,
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
    kind: worker.kind === 'run' || worker.kind === 'extraction' ? worker.kind : 'turn',
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

export const toDocumentSummary = (raw: Dto<typeof dto.documentDto>): DocumentSummary => ({
  sourceId: SourceId(raw.source_id),
  charCount: raw.char_count,
  sha256: raw.sha256,
  uri: raw.uri,
  title: raw.title,
  publishedAt: raw.published_at,
  note: raw.note,
  droppedReason: raw.dropped_reason,
})

export const toDocumentText = (raw: Dto<typeof dto.documentTextDto>): DocumentText => ({
  ...toDocumentSummary(raw),
  text: raw.text,
  start: raw.start,
  end: raw.end,
})

export const toGraphNode = (raw: Dto<typeof dto.graphEntityDto>): GraphNode => ({
  id: raw.entity_id,
  name: raw.name,
  entityType: raw.entity_type,
})

export const toGraphLink = (raw: Dto<typeof dto.graphRelationshipDto>): GraphLink => ({
  source: raw.source_id,
  target: raw.target_id,
  relationshipType: raw.relationship_type,
})

export const toWholeGraph = (raw: Dto<typeof dto.graphWholeDto>): WholeGraph => ({
  entities: raw.entities.map(toGraphNode),
  relationships: raw.relationships.map(toGraphLink),
  truncated: raw.truncated,
})

export const toNeighborhood = (raw: Dto<typeof dto.graphNeighborhoodDto>): Neighborhood => ({
  root: toGraphNode(raw.root),
  entities: raw.entities.map(toGraphNode),
  relationships: raw.relationships.map(toGraphLink),
})

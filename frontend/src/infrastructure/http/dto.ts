import { z } from 'zod'

/** The wire shapes, exactly as `presenters.py` writes them.
 *
 * Deliberately verbatim — snake_case, nullables and all. This module is the
 * only place in the application allowed to look like the backend; mapping into
 * domain types happens next door in `mappers.ts`. Keeping the two apart is what
 * makes a backend rename a one-file change rather than a rename across every
 * component that reads the field.
 *
 * Unknown keys pass through rather than failing: the console must keep working
 * against a backend that has grown a field it does not read yet.
 */

/** A nullable that also tolerates the key being absent entirely. Several of
 *  these fields are populated by `getattr(event, name, None)` server-side, and
 *  a few endpoints omit rather than null them. */
const maybe = <T extends z.ZodTypeAny>(schema: T) => schema.nullish().transform((v) => v ?? null)

/** A field this layer deliberately does not describe — a message body, a tool's
 *  arguments — read structurally further in, and absent as often as not.
 *
 *  Spelled out rather than left as a bare `z.unknown()`, which under Zod 3 was
 *  implicitly optional and under Zod 4 is not. That difference is silent in the
 *  types and rejects real responses at run time, so the optionality is stated
 *  here where it can be read. */
const opaque = z.unknown().optional()

export const logEntryDto = z.object({
  index: z.number(),
  type: z.string(),
  occurred_at: z.string(),
  summary: maybe(z.string()),
  path: maybe(z.string()),
  turn_index: maybe(z.number()),
  is_error: maybe(z.boolean()),
  cancelled: maybe(z.boolean()),
})
export type LogEntryDto = z.infer<typeof logEntryDto>

export const messageDto = z.object({
  role: z.string(),
  content: opaque,
  tool_calls: z
    .array(z.object({ name: z.string(), args: z.record(z.string(), z.unknown()).default({}) }))
    .default([]),
  is_error: z.boolean().default(false),
})

export const workspaceFileDto = z.object({
  path: z.string(),
  size: z.number(),
  revisions: z.number().default(0),
})

export const sessionDto = z.object({
  id: z.string(),
  project_id: maybe(z.string()),
  holds_project: maybe(z.boolean()),
  knowledge_attached: maybe(z.boolean()),
  system_prompt: maybe(z.string()),
  model_name: maybe(z.string()),
  turn_index: z.number().default(0),
  failed_turns: z.number().default(0),
  forked_from: maybe(z.string()),
  forked_at: maybe(z.number()),
  event_count: z.number().default(0),
  compacted_through: maybe(z.number()),
  compaction_summary: maybe(z.string()),
  at: maybe(z.number()),
  files: z.array(workspaceFileDto).default([]),
  messages: z.array(messageDto).default([]),
})

export const sessionSummaryDto = z.object({
  id: z.string(),
  /** Required, unlike `sessionDto`'s. This shape is folded from a stream that
   *  must open with `SessionStarted`, which carries a project — so a summary
   *  without one is a response no current backend can produce, and parsing it
   *  as `null` would only push the impossible state further in. The cost is
   *  that a pre-#65 database served by a current build fails loudly here
   *  rather than rendering a project-less row; loudly is the point. */
  project_id: z.string(),
  started_at: maybe(z.string()),
  turns: maybe(z.number()),
  files: maybe(z.number()),
  first_message: maybe(z.string()),
  forked_from: maybe(z.string()),
  forked_at: maybe(z.number()),
  failed_turns: maybe(z.number()),
})

/** The fork tree is recursive, so its schema needs an explicit type: inference
 *  cannot see through the self-reference.
 *
 *  The child schema is a getter rather than a `z.lazy` wrapper — that is Zod 4's
 *  idiom for this, and it is the same trick either way: the property is not
 *  evaluated until something reads it, by which time `forkNodeDto` is bound. */
export type ForkNodeDto = z.infer<typeof sessionSummaryDto> & { children: ForkNodeDto[] }

export const forkNodeDto: z.ZodType<ForkNodeDto, unknown> = sessionSummaryDto.extend({
  get children() {
    return z.array(forkNodeDto).default([])
  },
})

export const fileRevisionDto = z.object({
  index: z.number(),
  type: z.string(),
  occurred_at: z.string(),
  content: maybe(z.string()),
  old_string: maybe(z.string()),
  new_string: maybe(z.string()),
  replace_all: maybe(z.boolean()),
})

/** `/files` answers an object; older shapes answered the bare string. Accepting
 *  both costs one union and removes a class of "undefined contents" bug. */
export const fileContentDto = z.union([
  z.object({ content: z.string() }).transform((body) => body.content),
  z.string(),
])

export const componentErrorDto = z.object({
  path: maybe(z.string()),
  message: z.string(),
})

export const documentBlockDto = z.union([
  z.object({ kind: z.literal('markdown'), text: z.string().default('') }),
  z.object({
    kind: z.literal('component'),
    id: z.string(),
    type: z.string().default(''),
    data: z.record(z.string(), z.unknown()).default({}),
    raw: z.string().default(''),
    lang: maybe(z.string()),
    unknown: z.boolean().default(false),
    errors: z.array(componentErrorDto).default([]),
    withheld: z.array(z.string()).default([]),
  }),
])

export const lessonDocumentDto = z.object({
  blocks: z.array(documentBlockDto).default([]),
})

export const itemProgressDto = z.object({
  path: z.string().optional(),
  component_id: z.string().optional(),
  attempts: z.number().default(0),
  correct: z.boolean().default(false),
  best_score: z.number().default(0),
  last_score: z.number().default(0),
  checked: z.array(z.number()).default([]),
})

export const progressDto = z.object({
  scope: z.string().optional(),
  path: maybe(z.string()),
  items: z.record(z.string(), itemProgressDto).default({}),
})

export const verdictDto = z.object({
  correct: z.boolean().default(false),
  score: maybe(z.number()),
  feedback: z.array(z.string()).default([]),
  rationale: maybe(z.string()),
  correct_options: z.array(z.number()).default([]),
  blanks: z
    .array(
      z.object({
        blank: z.number(),
        correct: z.boolean().default(false),
        answer: z.string().default(''),
      }),
    )
    .default([]),
  progress: itemProgressDto.nullish().transform((v) => v ?? null),
})

export const turnResultDto = z.object({
  turn_index: maybe(z.number()),
  from_index: maybe(z.number()),
  to_index: maybe(z.number()),
})

export const runningTurnDto = z.object({
  running: z.boolean().default(false),
  turn_index: maybe(z.number()),
  started_at: maybe(z.string()),
  elapsed_seconds: maybe(z.number()),
})

export const activityEntryDto = z.object({
  session_id: z.string(),
  message_id: z.string(),
  kind: z.string().default('message'),
  text: maybe(z.string()),
  payload: opaque,
})

export const activityDto = z.object({
  running: z.array(activityEntryDto).default([]),
  discarded: z.array(activityEntryDto).default([]),
})

/** One finding from `stage_exit.gate_context()`. */
export const gateFindingDto = z.object({
  check: z.string(),
  severity: z.string(),
  message: z.string(),
  cites: z.array(z.string()).default([]),
  suggested_edit: maybe(z.string()),
})

/** `stage_exit.gate_context()`, field for field.
 *
 * Written out rather than left `opaque` because the card renders every one of
 * these; the cost is that a server-side rename here breaks parsing rather than
 * silently blanking the panel, which is the failure we would rather have. */
export const gateContextDto = z.object({
  stage: z.string(),
  findings_artifact: z.string(),
  artifact_paths: z.array(z.string()).default([]),
  blocked: z.boolean(),
  artifacts_reviewed: z.number(),
  links_reviewed: z.number(),
  unimplemented_checks: z.array(z.string()).default([]),
  unreadable_artifacts: z.array(z.string()).default([]),
  findings: z.array(gateFindingDto).default([]),
})

export const approvalDto = z.object({
  id: z.string(),
  session_id: z.string(),
  tool_name: z.string(),
  description: maybe(z.string()),
  args: opaque,
  /** Plain strings, not an enum: an unknown decision from a newer server is
   *  dropped in `toApproval`, and failing the whole parse instead would lose
   *  the three decisions we do understand along with it. */
  allowed_decisions: z.array(z.string()).default([]),
  /** Present only on a stage gate. `presenters` omits the key rather than
   *  nulling it, deliberately, so absence is the reliable signal — hence
   *  `.optional()` and not `maybe()`, which would erase the difference. */
  context: gateContextDto.optional(),
})

export const workflowRefDto = z.object({
  id: z.string(),
  name: z.string(),
  version: z
    .union([z.string(), z.number()])
    .nullish()
    .transform((v) => v ?? null),
})

export const stageRefDto = z.object({
  id: z.string(),
  name: z.string(),
  index: z.number(),
  of: z.number(),
})

export const projectDto = z.object({
  id: z.string(),
  name: z.string(),
  active_session_id: maybe(z.string()),
  tip_at_event: z.number().default(0),
  workflow: workflowRefDto.nullish().transform((v) => v ?? null),
  stage: stageRefDto.nullish().transform((v) => v ?? null),
})

export const presetDto = z.object({
  id: z.string(),
  name: z.string(),
  version: z
    .union([z.string(), z.number()])
    .nullish()
    .transform((v) => v ?? null),
  description: z.string().default(''),
  produces: z.string().default(''),
  stage_count: z.number().default(0),
  terminates_at: z.object({ id: z.string(), name: z.string(), spine: z.number() }),
  has_value_filter: z.boolean().default(false),
  label: z.string(),
})

export const provenanceDto = z.object({
  sources: z
    .array(
      z.object({
        source_id: z.string(),
        start: maybe(z.number()),
        end: maybe(z.number()),
      }),
    )
    .default([]),
  inferred: z.boolean().default(false),
  unreadable: z.number().default(0),
  empty: z.boolean().default(false),
})

export const artifactSlotDto = z.object({
  path: z.string(),
  artifact_type: z.string(),
  subtype: maybe(z.string()),
  cardinality: z.string().default(''),
  stage_id: z.string().default(''),
  present: z.boolean().default(false),
  has_frontmatter: z.boolean().default(false),
  missing_fields: z.array(z.string()).default([]),
  provenance: provenanceDto.nullish().transform((v) => v ?? null),
  body_chars: z.number().default(0),
})

export const findingDto = z.object({
  check: z.string(),
  severity: z.string(),
  message: z.string(),
  cites: z.array(z.string()).default([]),
  suggested_edit: maybe(z.string()),
})

export const stageProgressDto = z.object({
  index: z.number(),
  id: z.string(),
  name: z.string(),
  kind: z.string().default(''),
  spine: z.number().default(0),
  scope_level: z.string().default(''),
  /* `z.string()` rather than an enum, for the reason `seedingFrameDto.status`
     gives: a status this build has not heard of should reach the mapper's
     fallback rather than fail validation. The *default* is the part that was
     wrong -- `'todo'` is a name the server has never sent and no stylesheet
     matches, so a payload omitting `status` drew an unstyled chip reading
     "todo". A payload that does not say where a stage sits is a stage this
     console cannot place, which is what `unknown` means. */
  status: z.string().default('unknown'),
  outputs: z.array(artifactSlotDto).default([]),
  gate_decisions: z.array(z.string()).default([]),
  reviewer_role: maybe(z.string()),
  findings_report: maybe(z.string()),
})

export const courseDto = z.object({
  project_name: z.string().default(''),
  holding_session_id: maybe(z.string()),
  preset: z.object({
    id: z.string(),
    name: z.string(),
    version: z
      .union([z.string(), z.number()])
      .nullish()
      .transform((v) => v ?? null),
  }),
  position: maybe(z.number()),
  stage_count: z.number().default(0),
  stages: z.array(stageProgressDto).default([]),
  live_findings: z.array(findingDto).default([]),
  unimplemented_checks: z.array(z.string()).default([]),
})

export const runDto = z.object({
  run_id: z.string(),
  project_id: z.string(),
  session_id: z.string(),
  // Everything below is absent on the 202 body: a run that has begun and has
  // not been folded yet.
  status: z.string().optional(),
  rounds: z.number().optional(),
  turns: z.number().optional(),
  findings: z.number().optional(),
  stop_reason: maybe(z.string()).optional(),
  working_on: maybe(z.string()).optional(),
  quiet_rounds: z.number().optional(),
  failures: z.number().optional(),
  budget: z.object({ max_rounds: maybe(z.number()), quiet_rounds: maybe(z.number()) }).optional(),
  read_only: z.boolean().optional(),
})

export const healthDto = z.object({
  summaries: z.object({
    healthy: z.boolean().default(true),
    following: z.boolean().default(true),
    failed_events: z.number().default(0),
  }),
})

/** The live frames, as four separate schemas rather than one union.
 *
 * They cannot be a discriminated union: three have a literal `type`, but a log
 * frame's `type` is an open set of domain event names and could be any string —
 * so no schema can express "everything else". The reader dispatches on the
 * `type` field first and then parses with exactly one of these, which is both
 * what a union would have compiled to and considerably easier to read. */
export const frameEnvelopeDto = z.object({ type: z.string() })
export const approvalRequestedFrameDto = approvalDto
export const approvalSettledFrameDto = z.object({ id: z.string(), session_id: z.string() })
export const activityFrameDto = activityEntryDto
export const logFrameDto = logEntryDto.extend({ session_id: z.string() })
/** One topic event on the live feed. `change` is the event class name and is
 *  a plain string for the reason `extractionFrameDto.stage` is: a server that
 *  has grown a new topic event must move this list, not fail validation on it
 *  and leave the pane stale. */
export const topicFrameDto = z.object({ topic_id: z.string(), change: z.string() })

/** A knowledge-graph or corpus event on the live feed. One shape for both:
 *  the server addresses each by project and names the event class, and the
 *  two differ only in the `type` that selected them. `change` is a plain
 *  string for the reason `topicFrameDto.change` is -- a server that grew a
 *  new event must move the pane, not fail validation and leave it stale. */
export const projectChangeFrameDto = z.object({ project_id: z.string(), change: z.string() })

/** A project event on the live feed: the shape above plus the reviewer's
 *  verdict.
 *
 *  `decision` is optional *and* nullable, which is two different absences on
 *  purpose. Null is what the server sends for the five project events that are
 *  not a stage advance -- "this is not that kind of change". Absent is a server
 *  older than the field, which must still move the rail rather than fail
 *  validation and leave the page stale, for the reason `change` is a plain
 *  string rather than an enum. */
export const projectFrameDto = projectChangeFrameDto.extend({
  decision: maybe(z.string()).optional(),
})

export const workerDto = z.object({
  kind: z.string(),
  ref: z.string(),
  detail: z.string(),
  session_id: maybe(z.string()),
  parent: maybe(z.string()),
  started_at: maybe(z.string()),
})

export const rosterDto = z.object({
  project_id: z.string(),
  workers: z.array(workerDto).default([]),
  idle_session_ids: z.array(z.string()).default([]),
})

/** One note from a running `remember`.
 *
 * `stage` is a plain string rather than an enum on purpose: an unrecognised
 * stage must reach the mapper's fallback, not fail validation. A build talking
 * to a server that has grown a seventh stage should show the extraction
 * progressing, not blank the pane on every frame. */
export const extractionFrameDto = z.object({
  type: z.string(),
  project_id: z.string(),
  source_id: z.string(),
  stage: z.string(),
  detail: z.string().default(''),
  entities: maybe(z.number()),
  relationships: maybe(z.number()),
  domain: maybe(z.string()),
  domain_confidence: maybe(z.number()),
  index: maybe(z.number()),
  total: maybe(z.number()),
  model_calls: maybe(z.number()),
})

export const extractionCatchUpDto = z.object({
  current: z.array(extractionFrameDto).default([]),
  last: z.array(extractionFrameDto).default([]),
})

/** One seeding run's status, from `SeedingActivity` -- passed straight
 *  through by `seeding_view`, so this is the frame's actual wire shape
 *  rather than a fold of many. `status` is a plain string for the reason
 *  `extractionFrameDto.stage` is: a status this build has not heard of
 *  should reach the mapper's fallback, not fail validation. `subject`,
 *  `reply` and `detail` are each populated on some statuses and absent on
 *  others -- `maybe` tolerates the key being missing entirely rather than
 *  merely null, matching how `SeedingActivity.start`'s running frame omits
 *  them outright instead of nulling them. */
export const seedingFrameDto = z.object({
  type: z.string(),
  project_id: z.string(),
  run_id: z.string(),
  status: z.string(),
  subject: maybe(z.string()),
  reply: maybe(z.string()),
  detail: maybe(z.string()),
})

/** `current`/`last` are each nullable rather than defaulted to an empty
 *  array like `extractionCatchUpDto`'s: there is at most one frame per side,
 *  not a sequence, so "nothing yet" is `null` and not `[]`. */
export const seedingCatchUpDto = z.object({
  current: seedingFrameDto.nullable().default(null),
  last: seedingFrameDto.nullable().default(null),
})

/** One dispatch, in the one shape the 202, the catch-up read and the SSE
 *  channel all send — `dispatch_view` on the server is what keeps them
 *  identical, and this schema is what notices if they stop being.
 *
 * `action` and `status` are `z.string()` rather than enums, matching
 * `seedingFrameDto` and `topicFrameDto`: a server that grows a `lesson`
 * action or a status this build has not heard of must reach the mapper's
 * fallback, not fail validation and blank the row. */
export const dispatchFrameDto = z.object({
  type: z.string(),
  project_id: z.string(),
  topic_id: z.string(),
  dispatch_id: z.string(),
  action: z.string(),
  status: z.string(),
  question: maybe(z.string()),
  position: maybe(z.number()),
  path: maybe(z.string()),
  session_id: maybe(z.string()),
  detail: maybe(z.string()),
})

/** `running` is nullable and the two lists default to empty, matching the
 *  shapes their sources have: there is at most one running dispatch, and any
 *  number queued or finished. */
export const dispatchCatchUpDto = z.object({
  running: dispatchFrameDto.nullable().default(null),
  queued: z.array(dispatchFrameDto).default([]),
  finished: z.array(dispatchFrameDto).default([]),
})

/** A topic's own documents, and the session/scrub pair to read them at.
 *
 * `session_id` and `at` are both nullable and mean different things: no
 * session at all (a project never joined, which therefore has no documents
 * either), and HEAD (a live holder, whose uncommitted work the tip does not
 * yet know about). */
export const topicDocumentsDto = z.object({
  directory: z.string(),
  session_id: maybe(z.string()),
  at: maybe(z.number()),
  documents: z.array(z.object({ path: z.string(), name: z.string() })).default([]),
})

/** The autonomy policy, as all three routes shape it through one presenter.
 *
 * `levels` values are `z.string()` rather than an enum on purpose: a server
 * that grows a fourth level must reach the domain's fallback and render as
 * itself, not fail validation and blank the panel. `gated` and `stage_gates`
 * are sent so the frontend never hardcodes a tool list — a list that drifts
 * from `GATED_TOOLS` shows up as a tool silently unmanageable from the web. */
export const autonomyDto = z.object({
  levels: z.record(z.string(), z.string()).default({}),
  gated: z.array(z.string()).default([]),
  stage_gates: z.array(z.string()).default([]),
})

/** Allow-all adds `changed`: only what actually moved, possibly empty. It is
 *  what to report back to the person who clicked — `levels` would claim eight
 *  changes where one was made. */
export const autonomyChangeDto = autonomyDto.extend({
  changed: z.record(z.string(), z.string()).default({}),
})

/** One row of `/api/projects/{id}/topics`. `status` and `triggers` are plain
 *  strings rather than enums for the reason `extractionFrameDto.stage` is: a
 *  status or trigger this build has not heard of must still reach the mapper
 *  and render as itself, not fail validation and blank the whole queue. */
export const topicDto = z.object({
  topic_id: z.string(),
  question: z.string(),
  status: z.string(),
  sources: z.number(),
  findings: z.number(),
  open_sub_questions: z.number(),
  triggers: z.array(z.string()).default([]),
  needs_attention: z.boolean(),
  is_blocked: z.boolean(),
})

/** The topic's own page: the row plus what the list leaves out. `.extend`
 *  because the server builds it the same way — `topic_detail_view` spreads
 *  `topic_view` and adds these fields — and drift between the two shapes
 *  would first show up here. */
export const topicDetailDto = topicDto.extend({
  rationale: z.string(),
  scope: z.string(),
  sub_questions: z
    .array(
      z.object({
        key: z.string(),
        question: z.string(),
        answer: maybe(z.string()),
        resolved: z.boolean(),
      }),
    )
    .default([]),
  source_ids: z.array(z.string()).default([]),
  finding_notes: z.array(z.string()).default([]),
  contested: z.boolean(),
})

/** One row of `/api/projects/{id}/sources`: metadata only, never text. See
 *  `source_view` -- `dropped_reason` is always present, `null` for a live
 *  document. */
export const documentDto = z.object({
  source_id: z.string(),
  char_count: z.number(),
  sha256: z.string(),
  uri: maybe(z.string()),
  title: maybe(z.string()),
  published_at: maybe(z.string()),
  note: maybe(z.string()),
  dropped_reason: maybe(z.string()),
  // Defaulted rather than required, for `graphRelationshipDto.inferred`'s
  // reason: a server that predates the field answers rows without it, and
  // refusing the whole listing over a flag would take the document browser
  // down to report a missing annotation.
  extracted: z.boolean().default(false),
})

/** One row of `/sources/extraction-queue`'s `finished`: how a document's most
 *  recent extraction went.
 *
 * `detail` only on a failure and the counts only on a success, which is why
 * all three are optional rather than nullable on the wire -- the server omits
 * the keys that do not apply rather than sending nulls. See `_drain`. */
export const extractionOutcomeDto = z.object({
  source_id: z.string(),
  status: z.enum(['done', 'failed']),
  detail: maybe(z.string()),
  entities: maybe(z.number()),
  relationships: maybe(z.number()),
})

/** `/api/projects/{id}/sources/extraction-queue`: what is extracting, what is
 *  waiting, and how each document's last one went.
 *
 * Every list defaults, because a build with no queue wired answers three empty
 * lists rather than a 503 -- having nothing extracting is a state, not an
 * error, and this schema should not be the thing that turns it into one. */
export const extractionQueueDto = z.object({
  running: maybe(z.string()),
  queued: z.array(z.string()).default([]),
  finished: z.array(extractionOutcomeDto).default([]),
})

/** `/api/projects/{id}/sources/{source_id}`: the row plus the text and the
 *  offsets it was actually read at. `.extend` for the reason `topicDetailDto`
 *  gives -- `source_text_view` spreads `source_view` and adds these three. */
export const documentTextDto = documentDto.extend({
  text: z.string(),
  start: z.number(),
  end: z.number(),
})

/** One node of `/api/projects/{id}/graph/entities` and the neighbourhood
 *  route: an id, its label and its kind. Shared by both because
 *  `neighborhood_view` builds on `entity_view` the same way `topicDetailDto`
 *  builds on `topicDto`. */
export const graphEntityDto = z.object({
  entity_id: z.string(),
  name: z.string(),
  entity_type: z.string(),
  // Nullable and defaulted, matching `truncated` below: this project breaks
  // contracts rather than migrating them (server and bundle ship from one
  // repository, so there is no older server to tolerate), but a fixture in
  // this test suite that predates the field is real and should not have to
  // be found and updated just because this one entity gained an attribute.
  temporal: z.string().nullable().default(null),
})

export const graphEntityPageDto = z.object({
  entities: z.array(graphEntityDto).default([]),
  next_after: maybe(z.string()),
})

export const graphRelationshipDto = z.object({
  source_id: z.string(),
  target_id: z.string(),
  relationship_type: z.string(),
  // See graphEntityDto.temporal for why these default rather than require.
  inferred: z.boolean().default(false),
  derivation: z.string().nullable().default(null),
})

/** `/api/projects/{id}/graph`: the whole graph, and whether the server's cap
 *  cut it short. No root -- see `WholeGraph`. */
export const graphWholeDto = z.object({
  entities: z.array(graphEntityDto).default([]),
  relationships: z.array(graphRelationshipDto).default([]),
  truncated: z.boolean().default(false),
  // Whole-graph only, not the neighbourhood -- a neighbourhood is bounded by
  // MAX_NEIGHBORHOOD_DEPTH over one root and never approaches the cap this
  // flag protects against, so `graphNeighborhoodDto` deliberately omits it.
  inferred_truncated: z.boolean().default(false),
})

export const graphNeighborhoodDto = z.object({
  root: graphEntityDto,
  entities: z.array(graphEntityDto).default([]),
  relationships: z.array(graphRelationshipDto).default([]),
})

/** One row of `/api/projects/{id}/graph/entities/{entity_id}/usages`. Best
 *  matches first, already sorted server-side -- see `usages_view`'s own
 *  docstring -- so nothing here re-sorts. */
export const usageDto = z.object({
  source_id: z.string(),
  start: z.number(),
  end: z.number(),
  text: z.string(),
  score: z.number(),
})

export const usagePageDto = z.object({
  usages: z.array(usageDto).default([]),
})

/** One span from `/api/projects/{id}/graph/entities/{entity_id}/definition`'s
 *  `citations` array -- a passage, not a whole document, unlike `Citation`
 *  in `ask/conversation.ts`. */
export const definitionCitationDto = z.object({
  source_id: z.string(),
  start: z.number(),
  end: z.number(),
})

/** `text`/`model`/`generated_at` are nullable together -- `presenters.py`'s
 *  `definition_view` sends all three `null` in the one case where there is
 *  nothing to report, and not otherwise. */
export const definitionDto = z.object({
  text: z.string().nullable(),
  citations: z.array(definitionCitationDto).default([]),
  model: z.string().nullable(),
  generated_at: z.string().nullable(),
  stale: z.boolean(),
})

export const idDto = z.object({ id: z.string() })
export const okDto = z.unknown()

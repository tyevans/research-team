import type { Approval, ApprovalAnswer } from '@domain/approval/approval.ts'
import type {
  BrowserSessionPage,
  InteractionLogHealth,
  InteractionPage,
  InteractionSummary,
  LoggedInteraction,
} from '@domain/interaction/log.ts'
import type { InteractionFilters } from '@domain/interaction/filters.ts'
import type { AskEvent } from '@domain/ask/conversation.ts'
import type { DialogueEvent } from '@domain/dialogue/conversation.ts'
import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { AutonomyChange, AutonomyPolicyView } from '@domain/autonomy/autonomy.ts'
import type { ExtractionFrame } from '@domain/knowledge/extraction.ts'
import type {
  Definition,
  EntitySearchResult,
  Neighborhood,
  Usage,
  WholeGraph,
} from '@domain/knowledge/graph.ts'
import type { OntologyClass } from '@domain/knowledge/ontology.ts'
import type { Scope, SettingsSchema } from '@domain/settings/spec.ts'
import type { ResolvedSettings, ScopeRef } from '@domain/settings/layer.ts'
import type { AuthoringRun, AuthoringStatus } from '@domain/knowledge/authoring.ts'
import type { Curriculum, LearningArea, LearningPath } from '@domain/knowledge/curriculum.ts'
import type { Catalog } from '@domain/knowledge/catalog.ts'
import type { CourseDetail, CourseText } from '@domain/knowledge/course.ts'
import type { Timeline } from '@domain/knowledge/timeline.ts'
import type { ComponentAudience, DocumentBlock, LessonDocument } from '@domain/lesson/document.ts'
import type { AttemptResponse, ItemProgress, Verdict } from '@domain/lesson/attempt.ts'
import type { ProjectDetail, ProjectListing } from '@domain/project/project.ts'
import type {
  DocumentText,
  MediaSummary,
  SourceSummary,
  TextSummary,
} from '@domain/research/document.ts'
import type { ExtractionQueueBoard } from '@domain/research/extraction-queue.ts'
import type { IgnoredMedia, MediaProposalGroup } from '@domain/research/media-proposal.ts'
import type { Dispatch, DispatchAction } from '@domain/research/dispatch.ts'
import type { TopicDocuments } from '@domain/research/topic-document.ts'
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
  BrowserSessionId,
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
  /** No `create`. A session belongs to a project, so it is `ProjectRepository`
   *  that mints one -- `join` -- and there is no session to make without one.
   *  `fork` is the other way a session comes into being, and it inherits the
   *  project of the session it came from. */
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
  decide(id: SessionId, approvalId: ApprovalId, answer: ApprovalAnswer): Promise<void>
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
  /** Autos every gated tool.
   *
   * Parameterless since the workflow system came out. It used to take
   * `includeStageGates`, and the exclusion it defaulted to was the stage review
   * gate -- the one place a person was guaranteed to be looking before a run
   * built on what it had produced. There is no such gate now, so there is no
   * subset to hold back and nothing for the flag to select.
   */
  allowAll(id: SessionId): Promise<AutonomyChange>
}

export interface ProjectRepository {
  /** Every project, each with the pipeline counts the index draws.
   *
   * `ProjectListing` rather than `Project`: the summary is the whole reason
   * the index can tell one project from another, and typing this as `Project`
   * would let a build that dropped the field typecheck and render six
   * identical rows -- which is the state this replaced. */
  list(): Promise<readonly ProjectListing[]>
  /** One project, for a page that was reached by URL rather than from the
   *  list. Separate from `list()` rather than a lookup in its result: a
   *  reload, a bookmark or a shared link arrives with no listing fetched, and
   *  filtering one would fold every project to answer about one. */
  project(id: ProjectId): Promise<ProjectDetail>
  create(name: string): Promise<ProjectId>
  /** `takeOver` ends the holding session first. */
  join(id: ProjectId, takeOver: boolean): Promise<{ sessionId: SessionId; warning: string | null }>
  delete(id: ProjectId, releaseHolder: boolean): Promise<void>
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
  /** Send an agent at one topic. Answers with the dispatch as *queued*, not
   *  running: the server has scheduled it and not started it when this
   *  resolves, and the `running` frame follows over the live feed.
   *
   *  Never rejects with a 409, unlike `startSeed` — a control that appears on
   *  every topic row cannot answer "the project is busy" to every second
   *  press, so a busy project queues. Rejects 404 for a topic this project
   *  does not have and 422 for an action this build does not run. */
  dispatch(projectId: ProjectId, topicId: TopicId, action: DispatchAction): Promise<Dispatch>
  /** Send the same agent at every topic in a list, in the order given.
   *
   *  **The scope is the caller's and there is no "all".** A route that took
   *  "all" would have to define it against a queue the browser is filtering,
   *  and the two definitions would drift; the safety property this buys is
   *  that the count on screen and the number of turns started are the same
   *  number by construction rather than by two pieces of code agreeing.
   *
   *  Rejects 422 for an empty list, for more than fifty ids, and for an
   *  action this build does not run. Ids the project does not hold come back
   *  in `unknown` rather than refusing the whole call -- see
   *  `BulkDispatchResult`. */
  dispatchBulk(
    projectId: ProjectId,
    action: DispatchAction,
    topicIds: readonly TopicId[],
  ): Promise<BulkDispatchResult>
  /** What is running, what is queued and how each topic's last one went.
   *
   *  The catch-up read these frames cannot do without: they carry no feed
   *  position, so `Last-Event-ID` cannot replay them and a reconnecting tab
   *  would otherwise be unable to tell "still running" from "finished before
   *  I got here". */
  dispatchStatus(projectId: ProjectId): Promise<DispatchBoard>
  /** Stop what is running on this project and drop everything queued.
   *
   *  Per project rather than per dispatch, matching the route and
   *  `ResearchSupervisor.cancel` behind it. */
  cancelDispatch(projectId: ProjectId): Promise<number>
  /** Everything written about one topic, and the session/scrub pair to read
   *  it at. Answers an empty listing for a topic nobody has dispatched at —
   *  that is a state, not a missing resource — and rejects 404 only for a
   *  topic this project does not have. */
  documents(projectId: ProjectId, topicId: TopicId): Promise<TopicDocuments>
}

/** What one fan-out started, and what it could not.
 *
 * `unknown` exists so a caller can say "started 11 of 12" rather than
 * silently starting fewer than it offered. A client that ignores it is the
 * failure this field is here to make expressible.
 */
export interface BulkDispatchResult {
  readonly queued: readonly Dispatch[]
  readonly unknown: readonly string[]
}

/** Everything a project has dispatched, as one read.
 *
 * Three fields rather than one list with a status filter, because they are
 * three different questions the UI asks in three different places: the pane
 * header counts the first two, and a row reads only the third unless it is
 * itself the running one.
 */
export interface DispatchBoard {
  readonly running: Dispatch | null
  readonly queued: readonly Dispatch[]
  readonly finished: readonly Dispatch[]
}

export interface DocumentRepository {
  /** Every source this project has stored, dropped ones included -- the
   *  corpus keeps them on purpose, as an audit trail, and hiding them here
   *  would misreport what the project holds. */
  list(projectId: ProjectId): Promise<readonly SourceSummary[]>
  /** One document's text, or a `start`/`end` range of it. Omitting `range`
   *  reads the whole document; the server clamps a range past the end
   *  rather than refusing it, and the offsets in the result are what it
   *  actually returned. */
  read(projectId: ProjectId, sourceId: SourceId, range?: DocumentRange): Promise<DocumentText>
  /** Queue one stored document for extraction.
   *
   * Answers whether *this* press took the document on. `false` is not an
   * error: it means the queue already holds it or is running it, which is what
   * the caller wanted. The server says so plainly (202, not 409) precisely so
   * a client can avoid claiming it started something it did not, and a
   * `Promise<void>` here would throw that distinction away at the port. */
  extract(projectId: ProjectId, sourceId: SourceId): Promise<boolean>
  /** Queue every stored document with no graph yet, answering how many this
   *  press actually took on -- which is not how many are unextracted, because
   *  the queue refuses what it already holds. Dropped documents are excluded
   *  by the server, not filtered here. */
  extractAll(projectId: ProjectId): Promise<number>
  /** What is extracting, what is waiting, and how each document's last one
   *  went. The queue publishes no frames, so this read is the only way to
   *  learn any of it -- see `ExtractionQueueBoard`. */
  extractionQueue(projectId: ProjectId): Promise<ExtractionQueueBoard>
  /** Stop the running extraction and drop everything waiting, for this
   *  project. Answers how many went, so a caller can report the number rather
   *  than guessing from a queue it re-reads a moment later. */
  cancelExtraction(projectId: ProjectId): Promise<number>
  /** Queue one stored medium to be perceived into a text source.
   *
   * Shaped exactly like `extract` -- a boolean off a 202 -- because it queues
   * into the same place: perception rides `ExtractionActivity` and waits
   * behind whatever else the project has running, rather than owning a second
   * queue and a second pane to watch it in. So `false` means the same thing
   * here as there: the queue already holds this source, which is not an error.
   *
   * The refusals are the interesting part and they are all rejections, not
   * return values: 404 for no such medium, 409 for an id holding text or for a
   * dropped source, 410 for a record whose blob is gone, and 503 when the
   * install has no vision model and no transcriber. The 503 names *which* --
   * `AGENT_VISION_MODEL`, ffmpeg -- and a caller that replaces that message
   * with one of its own throws away the only sentence an operator can act on.
   * Report `ApiError.message` verbatim. */
  perceive(projectId: ProjectId, sourceId: SourceId): Promise<boolean>
  /** Store a document a person is holding.
   *
   * Refused by the server when the corpus already holds the id, rather than
   * superseding it: uploading is creating, and quietly replacing somebody
   * else's document is not what the word means.
   *
   * A `TextSummary` and not a `SourceSummary`, for the same reason as
   * `uploadMedia` below: this route stores text and only text, so a caller
   * should not have to re-narrow what it just created. Narrowed *here* and
   * not only in the adapter -- every caller reaches the repository through
   * this interface, so a union left on the port is a union every caller
   * still sees, whatever the class returns. */
  create(projectId: ProjectId, draft: DocumentDraft): Promise<TextSummary>
  /** Change a stored document. Every field is optional and an omitted one is
   *  left alone -- in particular `text`, so correcting a title does not
   *  round-trip the prose, and cannot send back a stale copy of it. */
  revise(projectId: ProjectId, sourceId: SourceId, edit: DocumentEdit): Promise<SourceSummary>
  /** Exclude a document, keeping the record and the reason. The corpus keeps
   *  dropped documents on purpose, so this is reversible -- see `restore`. */
  drop(projectId: ProjectId, sourceId: SourceId, reason: string): Promise<SourceSummary>
  /** Put a dropped document back. Refused for one that is not dropped, so a
   *  press that did nothing cannot look like one that worked. */
  restore(projectId: ProjectId, sourceId: SourceId): Promise<SourceSummary>
  /** Store bytes a person is holding: a recording, a scan, a slide deck.
   *
   * Multipart rather than a base64 field in `create`'s JSON, which is the
   * server's reason repeated here because it is what makes this a separate
   * method: a gigabyte through a JSON parser is held in memory twice over.
   * Answers a `MediaSummary` and not a `SourceSummary` -- this route stores
   * media and only media, so a caller does not have to re-narrow what it just
   * uploaded.
   *
   * Unlike `create` there is no 409 on a repeat: a second store under the same
   * id is a *revision* of a media source. It is refused only when that id
   * already holds text. */
  uploadMedia(projectId: ProjectId, draft: MediaDraft): Promise<MediaSummary>
  /** Where the bytes are, for the elements that fetch their own: a `<video>`
   *  or an `<img>` takes a URL rather than a promise, and the range requests a
   *  player makes to seek are the browser's, not this application's.
   *
   * On the repository because the base url is the transport's business --
   * a component building this string itself would be the one place in the
   * tree that knew a path. Not a promise: nothing is fetched to answer it. */
  contentUrl(projectId: ProjectId, sourceId: SourceId): string
}

/** A separate seam from `DocumentRepository`, though both speak for the
 *  corpus: a proposal has no bytes, and `Corpus`'s own guards -- kind flips,
 *  derivedness, digest supersession -- have nothing to say about a row that
 *  is not yet a source. `domain/media_proposals.py`'s own module docstring
 *  is why the *backend* keeps this a separate aggregate; this port mirrors
 *  that split rather than smuggling proposal reads through `documents`. */
export interface MediaProposalRepository {
  /** Every proposal in the project, grouped by the need that produced it --
   *  the shape `GET .../media-proposals` already answers in, so nothing here
   *  re-groups a flat list the server did not send flat. */
  list(projectId: ProjectId): Promise<readonly MediaProposalGroup[]>
  /** Record the decision and hand the download off to the accept worker.
   *
   * Resolves once the decision is recorded, not once the download finishes --
   * an hour of audio is minutes of transcription, and a caller that awaited
   * that would be a caller that hung the pane. `MediaProposalStored`/`Failed`
   * only ever show up in a re-read of `list`, which is why the card stays in
   * a working state and polls rather than awaiting a second promise here. */
  accept(projectId: ProjectId, proposalId: string): Promise<void>
  /** Close the record without touching either ignore list -- rejecting is not
   *  blacklisting, so a fresh proposal for the same asset is still allowed
   *  later. `note` is optional because most rejections are obvious. */
  reject(projectId: ProjectId, proposalId: string, note?: string): Promise<void>
  /** Ignore the asset or host behind one proposal, keyed off the proposal's
   *  own recorded asset -- the caller does not have to already know the key,
   *  unlike `unignore` below. Reversible; see `unignore`. */
  ignore(projectId: ProjectId, proposalId: string, grain: 'asset' | 'host'): Promise<void>
  /** Both ignore lists, for the undo list beside the pane -- a suppression
   *  nobody can see is indistinguishable from a chain that stopped working. */
  ignored(projectId: ProjectId): Promise<IgnoredMedia>
  /** Reverse an ignore at either grain, by the key `ignored` reported. */
  unignore(projectId: ProjectId, grain: 'asset' | 'host', key: string): Promise<void>
  /** Run the three-stage curation chain once for one topic -- the only way
   *  any proposal comes to exist. Resolves once the chain has actually run
   *  (the route answers 202 after appending events, not before starting),
   *  with the outcome counts the response carries -- `needs`/`candidates`/
   *  `ignored`/`rejectedParses` -- so a caller can toast something more
   *  useful than "done". */
  run(projectId: ProjectId, topicId: string): Promise<MediaCurationOutcome>
}

/** What one curation run reported, mirroring the route's own `CurationOutcome`
 *  field-for-field -- see `application/media_curation.py`'s `CurationOutcome`. */
export interface MediaCurationOutcome {
  readonly needs: number
  readonly candidates: number
  readonly ignored: number
  readonly rejectedParses: number
  /** Needs whose search pool came back empty -- the one route to zero
   *  candidates that no other count covers. See `CurationOutcome`. */
  readonly searchedEmpty: number
  /** Needs whose pooled candidates the judge saw and kept none of -- the
   *  fifth route to zero, and the one that leaves every other count clean.
   *  See `CurationOutcome`. */
  readonly judgedOut: number
}

/** A media upload. `file` rather than bytes: a `File` streams to the network
 *  without being read into a string first, which is the whole difference
 *  between uploading a two-hour recording and crashing the tab. */
export interface MediaDraft {
  /** The citation key, as on `DocumentDraft` -- and here too it is the thing
   *  that cannot change afterwards. */
  sourceId: string
  file: File
  uri?: string
  title?: string
  note?: string
  publishedAt?: string
}

export interface DocumentRange {
  readonly start?: number
  readonly end?: number
}

export interface DocumentDraft {
  /** The citation key. The corpus keys on it and it cannot be changed
   *  afterwards without orphaning every citation that points at it. */
  sourceId: string
  text: string
  uri?: string
  title?: string
  note?: string
  publishedAt?: string
}

/** An omitted field is left as stored. There is no way to clear one back to
 *  null: telling "unset" from "set to null" needs a sentinel and no control
 *  in the console asks for it. An empty title is sent as "". */
export interface DocumentEdit {
  text?: string
  uri?: string
  title?: string
  note?: string
  publishedAt?: string
}

export interface GraphRepository {
  /** The project's graph entire, up to the server's cap -- what the browser
   *  draws before the reader has searched for anything. `truncated` says the
   *  cap bit, which also means edges to whatever it cut off are absent. */
  whole(projectId: ProjectId): Promise<WholeGraph>
  /** Entities matching a name substring and, optionally, an exact entity
   *  type -- how a reader finds one thing inside a graph too big to take in
   *  whole. `truncated` on the result says whether the server held more back
   *  than the page returned. */
  search(projectId: ProjectId, name: string, entityType?: string): Promise<EntitySearchResult>
  /** `entityId` and what lies within `depth` hops of it. Rejects with a 422
   *  `ApiError` for a depth past the server's bound, which the caller must
   *  surface rather than clamp -- see the route's own docstring for why the
   *  server refuses instead of silently capping it. */
  neighborhood(projectId: ProjectId, entityId: string, depth?: number): Promise<Neighborhood>
}

/** Its own port rather than a method on `GraphRepository`: usages are a BM25
 *  lookup over the corpus, not a graph read, and the two already diverge on
 *  their store on the server side (`UsageReader` in `app.py`'s own words).
 *  Keeping them apart here means a fake for one never has to stub the other. */
export interface UsagesRepository {
  /** Passages mentioning `entityId`, best match first -- already the server's
   *  order, so nothing here re-sorts. No `limit` parameter: the route caps it
   *  server-side and refuses (422) rather than clamps a limit past that cap,
   *  and this panel always wants "as many as the server will give", so there
   *  is no caller-chosen value to thread through. */
  usages(projectId: ProjectId, entityId: string): Promise<readonly Usage[]>
}

/** Its own port for the reason `UsagesRepository` gives: a different read,
 *  a different failure shape (`text: null` is a valid answer, not an
 *  exception), and a fake for one should never have to stub the other. */
export interface DefinitionsRepository {
  /** `entityId`'s generated definition. Never rejects for "nothing to
   *  ground it in" -- that is `text: null` in the resolved value, per
   *  `Definition`'s own docstring -- so a caller does not need a catch
   *  block to tell an undefinable entity from a network failure. */
  definition(projectId: ProjectId, entityId: string): Promise<Definition>
}

/** The settings surface, as four calls.
 *
 * `PUT` and `DELETE` are separate methods rather than one `set(key, value |
 * null)`, because their failures are different questions. A `PUT` fails with
 * 422 and a sentence to render beside the field; a `DELETE` fails with **404
 * when nothing was set**, which the contract makes deliberate — clearing a key
 * that was never set is almost always a misspelling, and a silent 204 is how
 * the misspelling survives. A single method would have to flatten those into
 * one error type at exactly the seam where they diverge.
 */
export interface SettingsRepository {
  /** The declarations. Static, needs no scope and no credentials, and answers
   *  on a build with nothing else wired — so it is cacheable forever. */
  schema(): Promise<SettingsSchema>

  /** Resolution over a chain, reporting which layer answered each key.
   *
   * The chain is passed as scope refs rather than a single scope, because the
   * page makes this call **twice**: once with the scope it is editing, and
   * once with that scope *omitted*, which is the only correct answer to "what
   * would this fall back to if I cleared the override". The alternative —
   * reading the schema's `default` — is wrong whenever a middle layer answers,
   * which is the whole reason the feature exists, and is `null` for every
   * secret by contract, so it cannot answer the one case that frightens
   * people. An empty chain is a real request and resolves to environment and
   * default alone. */
  resolved(chain: readonly ScopeRef[]): Promise<ResolvedSettings>

  /** Write one override. `value` is a string whatever the setting's type: a
   *  form posts strings, and one server-side parser is what keeps the HTTP
   *  layer and the environment layer agreeing about what `"on"` means.
   *
   *  Throws `ApiError` with 422 for an unknown key, a refused value, a scope
   *  the declaration forbids, or a secret with no `AGENT_SETTINGS_KEY`. */
  put(scope: Scope, scopeId: string, key: string, value: string): Promise<void>

  /** Remove one override.
   *
   * `true` when something was removed, `false` when there was nothing to
   * remove — the 404 the contract specifies, turned into an outcome here
   * rather than thrown, because it is the answer to a question the UI asked
   * and not a failure of the request. Every other status still throws. */
  clear(scope: Scope, scopeId: string, key: string): Promise<boolean>
}

export interface OntologyRepository {
  /** Every class a discovery pass has found in this project.
   *
   * Empty is a real answer, not an error: a project nobody has run a pass on
   * has no classes. The server answers 503 rather than an empty list when it
   * is unwired, so a caller that gets `[]` can trust it. */
  classes(projectId: ProjectId): Promise<readonly OntologyClass[]>

  /** Read one document for the classes it states, and say how many were found.
   *
   * `null` means the document was not read -- an unreadable reply, or one over
   * the server's size ceiling -- where `0` means it was read and states none.
   * The two are kept apart because only one of them should stop anyone
   * retrying.
   *
   * `strict: false` reads the document under a weaker rule: a class whose
   * quoted sentence is not in the text survives if all its members are, cited
   * to the first member's occurrence and returned with `evidenceQuoted: false`.
   * It supersedes whatever a strict pass stored for that document, which is
   * both how it is meant to be used and its hazard. Default strict, because a
   * reader who has not asked for it must not be handed classes the document may
   * never have grouped. */
  discover(
    projectId: ProjectId,
    sourceId: string,
    options?: { readonly strict?: boolean },
  ): Promise<number | null>

  /** Every extracted document no discovery pass has read yet, in listing order.
   *
   * The sweep's work list. Extracted rather than merely stored, because a
   * document with no graph has no entities for a class's members to resolve
   * against; and "no pass has read it" rather than "it has no classes",
   * because a document read and found barren is done -- treating it as pending
   * would re-read every barren document at model cost on every press.
   *
   * Empty means finished, and can be trusted: the server answers 503 rather
   * than an empty list when discovery is unwired.
   *
   * `includeExamined` asks the other question: every extracted document,
   * whether a pass has read it or not. It is what a re-read is driven from, and
   * it exists because "examined" is not "examined correctly" -- a class the
   * verifier refused and a document that genuinely states none are recorded
   * identically, so the default list retires both forever. Unextracted
   * documents and media stay excluded either way; neither is something a pass
   * could have got wrong. */
  ungrouped(
    projectId: ProjectId,
    options?: { readonly includeExamined?: boolean },
  ): Promise<readonly string[]>
}

/** A window over the project's timeline. Every part optional: the whole
 *  timeline is a real thing to ask for, and it is the console's own request. */
export interface TimelineWindowQuery {
  readonly entityType?: string
  /** ISO instants bounding a half-open `[from, to)` window; either may be
   *  omitted for an open end. Sent as `from`/`to` -- the route aliases them
   *  back onto `from_`, because `from` is a Python keyword. */
  readonly from?: string
  readonly to?: string
  readonly limit?: number
}

/** Which serialisation of a graph export to ask for.
 *
 * `html` is the one that opens on its own — a single self-contained file with
 * the drawing in it. The other two exist because the first thing anybody does
 * with a graph they were sent is try to load it somewhere else. */
export type GraphExportFormat = 'html' | 'json' | 'graphml'

/** How much of the graph to export.
 *
 * A discriminated union rather than three optional fields, so a caller cannot
 * ask for an area scope and forget the slug — the server answers that with a
 * 422, and a download route's 422 is a page the browser navigates to rather
 * than an error this console can show. */
export type GraphExportScope =
  | { readonly kind: 'project' }
  | { readonly kind: 'area'; readonly slug: string }
  | { readonly kind: 'entity'; readonly entityId: string; readonly depth: number }

/** How a course export is packaged. `zip` is markdown for reading in a
 *  repository; `html` is one self-contained page for handing to a person —
 *  see `course_html.py` for what each lesson widget becomes offline. */
export type CourseExportFormat = 'zip' | 'html'

export interface ExportRepository {
  /** Where the authored course can be downloaded as one archive, or one area
   *  of it. A URL and not a promise — see the adapter for why a download is
   *  the browser's job rather than this console's.
   *
   *  `format` is last and optional so every existing call site keeps meaning
   *  the archive. The server refuses an unknown value with a 422 rather than
   *  defaulting, because the two formats differ in media type. */
  courseUrl(projectId: ProjectId, area?: string, format?: CourseExportFormat): string

  /** Where a drawing of the graph, or a cut of it, can be downloaded. */
  graphUrl(projectId: ProjectId, format: GraphExportFormat, scope?: GraphExportScope): string
}

export interface CurriculumRepository {
  /** The project's learning areas and the complete path through them.
   *
   * One call rather than two because the two are derived from one read of the
   * graph: a map with no order is a bag, an order with no areas is a list of
   * slugs, and two calls could be answered from two projections while a
   * project is still extracting.
   *
   * `derivedFrom` on the result is not dressing. An area map over forty
   * entities and one over four thousand draw identically, so a caller must
   * show what the projection was built from or a reader cannot tell a thin
   * result from a rich one -- or from a feature that never ran. */
  curriculum(projectId: ProjectId): Promise<Curriculum>

  /** One area with its full membership rather than its anchors.
   *
   * A separate call rather than a field on the above, because the map wants
   * five names per area and the area page wants sixty: sending every member of
   * every area to draw a map is the response growing with the project while
   * what it draws does not. */
  area(projectId: ProjectId, slug: string): Promise<LearningArea>

  /** Re-embed every entity in the project. Resolves with how many were written.
   *
   * The repair for two states that look identical on screen and are not: a
   * project ingested before entity vectors were durable has none recorded at
   * all, and an entity that gained relationships after it was first seen
   * carries a vector that predates them. Neither is visible except as a
   * curriculum clustered on less than it could be.
   *
   * Not automatic, and deliberately so — folding the log at project open must
   * never depend on a live embedding endpoint, or a project reopened years
   * from now would not open. So this is a thing a person asks for. */
  refreshEmbeddings(projectId: ProjectId): Promise<number>

  /** The complete path (`complete`), or the prerequisite closure of one area.
   *
   * Both from one route because they are cuts of one digraph. A destination
   * path's steps are always a subsequence of the complete path's -- two orders
   * that disagreed would be two curricula, and a reader switching views would
   * have no way to choose between them. */
  path(projectId: ProjectId, slug: string): Promise<LearningPath>

  /** Whether an authoring run is in flight, and how the last one went.
   *
   * Both halves, because a tab that arrived mid-run and one that arrived after
   * it finished need different answers and neither can reconstruct the other's
   * from the file list. */
  authoringStatus(projectId: ProjectId): Promise<AuthoringStatus>

  /** Start writing courses: one area, or every area on the path.
   *
   * Answers the run that has *begun*, not the files. Those arrive over the log
   * like any other write, so a caller wanting them invalidates its file list on
   * those frames rather than reading this result for them. */
  /** `takeOver` releases whoever holds the project first. Off by default:
   *  a take-over ends somebody else's session, so the console asks before
   *  sending it. 409 when the holder is mid-turn -- releasing then advances
   *  the tip past writes still coming. */
  author(
    projectId: ProjectId,
    request: { area?: string; lessons?: number; takeOver?: boolean },
  ): Promise<AuthoringRun>

  /** Stop this project's authoring run. Answers how many targets it abandoned.
   *
   * Zero when nothing was running, which is not an error — a stop control
   * pressed twice is a person pressing a button.
   *
   * What it does *not* do is discard the courses the run already wrote. Those
   * exist in sessions whose ids are on the log, and the run is recorded as
   * cancelled with them still listed. */
  cancelAuthoring(projectId: ProjectId): Promise<number>
}

export interface CatalogRepository {
  /** The front page: hero, highlights, everything else by category, and what
   *  it was derived from -- matching `CurriculumRepository.curriculum`'s own
   *  reasoning, an empty catalog and a rich one must not render identically.
   *
   *  `includeUnnamed` defaults false, matching the server's own default
   *  (`GET /catalog?unnamed=`) -- a title-less card falls back to the
   *  cluster's single most central entity name, which reads as an entity
   *  rather than a course. */
  catalog(projectId: ProjectId, includeUnnamed?: boolean): Promise<Catalog>

  /** Put one candidate on the front page, at `rank`. No precondition that
   *  `slug` currently names an area -- re-clustering can move or dissolve one
   *  out from under a feature, and `Catalog.unplaceableFeatured` is where that
   *  is reported rather than refused here. */
  feature(projectId: ProjectId, slug: string, rank: number): Promise<void>

  /** Take one candidate off the front page. Accepted even for a slug never
   *  featured -- there is no aggregate here to enforce a precondition
   *  against, and a second click doing nothing is not an error. */
  unfeature(projectId: ProjectId, slug: string): Promise<void>
}

/** What the course realization endpoints answer -- `POST .../realize`'s own
 *  shape server-side (`app.py`'s `realize_course`). `authoring` and `reason`
 *  are mutually informative rather than either alone: a caller reads the run
 *  panel from the next authoring-status poll when `authoring` is `null`, not
 *  from re-deriving it out of `reason`. */
export interface RealizeResult {
  readonly realized: boolean
  readonly authoring: AuthoringRun | null
  readonly reason: string | null
  /** The session holding the project, when that is why no run started.
   *
   * Set only for the holder case, so a caller can offer the take-over
   * without matching on `reason`'s wording. Writing a course needs the
   * project's filesystem and `JoinProject` admits one session at a time --
   * see `_authoring_holder` in `app.py` for what this being invisible cost. */
  readonly heldBy: SessionId | null
}

/** `_NOT_RUNNING`'s shape in `blurb_sweep.py` -- one project, one sweep at a
 *  time, and the shape a project that has never swept and one whose sweep
 *  just finished both answer alike. */
export interface BlurbSweepProgress {
  readonly running: boolean
  readonly done: number
  readonly total: number
  readonly failed: number
  readonly error: string | null
}

/** `_NOT_RUNNING`'s shape in the art sweep's own server module -- same shape
 *  as `BlurbSweepProgress` (one project, one sweep at a time), kept as its
 *  own type rather than reused because the two sweeps are unrelated runs
 *  over unrelated fields and nothing here should let a caller pass one
 *  where the other is meant. */
export interface ArtSweepProgress {
  readonly running: boolean
  readonly done: number
  readonly total: number
  readonly failed: number
  readonly error: string | null
}

export interface CourseRepository {
  /** One cluster's detail page: its candidate card, its outline, its full
   *  current membership, and -- if realized -- how it has drifted since. */
  course(projectId: ProjectId, slug: string): Promise<CourseDetail>

  /** The markdown the authoring turns wrote for this course, and which of
   *  three states its text is in.
   *
   *  A second request rather than a field on `course()`, for `useLesson`'s
   *  reason: the detail response is polled and invalidated by realize,
   *  abandon, a blurb sweep and an art reroll, none of which change a word of
   *  the authored text -- and the text is the largest thing on the page. It is
   *  also the only part whose state changes while a run is in flight, so it
   *  wants its own poll rather than dragging the whole detail with it. */
  courseText(projectId: ProjectId, slug: string): Promise<CourseText>

  /** Record that a person has decided this cluster is a course, then try to
   *  start authoring it. See `RealizeResult`'s own docstring for why a
   *  failure to start authoring is not this call's own error. */
  realize(projectId: ProjectId, slug: string): Promise<RealizeResult>

  /** Withdraw the decision that this cluster is a course. Does not cancel or
   *  discard a run already in flight -- the decision is withdrawn, not the
   *  work it caused. */
  abandon(projectId: ProjectId, slug: string): Promise<void>

  /** Start writing catalog copy for every candidate whose cached blurb is
   *  missing or stale, in the background. */
  startBlurbSweep(projectId: ProjectId): Promise<BlurbSweepProgress>

  /** Where the last (or current) blurb sweep on this project stands. */
  fetchBlurbSweep(projectId: ProjectId): Promise<BlurbSweepProgress>

  /** Start illustrating every candidate whose cached art is missing or
   *  stale, in the background. `force: true` re-illustrates *every*
   *  candidate, including one whose art is already fresh -- the distinct
   *  affordance the owner asked for, so pressing the ordinary button never
   *  costs a model call per card that already has art. */
  startArtSweep(projectId: ProjectId, options?: { force?: boolean }): Promise<ArtSweepProgress>

  /** Where the last (or current) art sweep on this project stands. */
  fetchArtSweep(projectId: ProjectId): Promise<ArtSweepProgress>

  /** Drop one candidate's art assignment and generate a fresh piece,
   *  skipping the library search -- see the server's `ArtReroll` for why a
   *  reroll must not risk re-matching back to the very picture the reroll
   *  is trying to escape. */
  startArtReroll(projectId: ProjectId, slug: string): Promise<ArtSweepProgress>

  /** Where the last (or current) reroll of this candidate's art stands. */
  fetchArtReroll(projectId: ProjectId, slug: string): Promise<ArtSweepProgress>
}

export interface TimelineRepository {
  /** The project's dated entities in time order, inside `window`, up to the
   *  server's cap.
   *
   * `undatedCount` on the result is not optional dressing -- most entities in
   * a real graph carry no dates, so a timeline is a view of a minority of the
   * corpus and the caller must show the denominator. `truncated` says the cap
   * bit, the same way `WholeGraph.truncated` does.
   *
   * An options object rather than the positional `entityType` this replaced:
   * three of the four parameters are optional and independent, and a
   * positional list of four optionals is a call site nobody can read. */
  timeline(projectId: ProjectId, window?: TimelineWindowQuery): Promise<Timeline>
}

export interface WorkerRepository {
  /** Every project that has something running, in one request.
   *
   * For a reader with no project in view -- the agent widget sits on every
   * page, so asking `on` per project would be O(projects) requests on every
   * page load. Only projects with a worker come back, so an empty array is the
   * ordinary answer and is *not* the same as the rejection a build without a
   * roster gives. */
  everywhere(): Promise<readonly Roster[]>
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

export interface AskRepository {
  /** Streams one question's answer, calling `onEvent` per frame. Rejects with
   *  a 409 `ApiError` when the chat already has a question running -- the
   *  caller must surface that rather than retry, since retrying would join a
   *  queue that does not exist.
   *
   *  Only a refusal made *before* streaming starts can be a status code --
   *  an unknown project rejects with a 404 the same way, since the route
   *  checks it before opening the stream. A failure after the first frame
   *  arrives as an `error` event and resolves instead, so a caller that only
   *  handles rejection will show a turn that silently stops. */
  ask(
    projectId: ProjectId,
    chatId: string,
    question: string,
    onEvent: (event: AskEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>
  /** Forgets the server's copy of a conversation, backing "new chat". */
  forget(projectId: ProjectId, chatId: string): Promise<void>
  /** The browser cannot mark an answer to a question the model asked back
   *  either — the key never left the server. Posts one and renders the reply.
   *
   *  Returns no progress alongside the verdict, unlike the lesson route: an
   *  ask records no attempt, so there is nothing to fold back in. */
  submitAskAttempt(
    projectId: ProjectId,
    conversationId: string,
    input: { position: number; componentId: ComponentId; response: AttemptResponse },
  ): Promise<Verdict>
}

/** A dialogue's framing: what it is for, when it is done, and how it opened.
 *
 * Returned whole from `start` rather than fetched afterwards. The route
 * `POST /dialogues` answered `{"dialogueId"}` alone for three commits while its
 * own docstring claimed the goal arrived there, so a freshly framed dialogue
 * drew an empty framing block and an empty thread until the reader answered a
 * question they could not see. `app.py`'s `start_dialogue` carries the trade
 * against a second `GET`.
 *
 * `openingBlocks`, never a raw prompt string: no dialogue surface carries raw
 * prompt text, because the raw copy ships the fenced component's answer key
 * beside a projection that withheld it. */
export interface DialogueFraming {
  readonly dialogueId: string
  readonly goal: string
  readonly stoppingCondition: string
  readonly openingBlocks: readonly DocumentBlock[]
}

/** What this reader has had marked in one dialogue, keyed `turn/{position}`
 *  and then by component id.
 *
 * Two levels because a component id is unique only within one utterance. Each
 * turn's value is exactly the shape `useAttemptMachine`'s `stored` port takes,
 * so an exchange passes its own entry through unadapted. */
export type DialogueProgress = Readonly<Record<string, ReadonlyMap<ComponentId, ItemProgress>>>

/** The socratic surface, which runs the other way round from the ask: the
 *  system asks and the reader answers. Its own port rather than a widened
 *  `AskRepository` for the reason `domain/dialogue/conversation.ts` opens
 *  with -- a shared type would make that inversion a runtime concern.
 *
 * Moved here from above `DialogueFraming`, where it read as that record's
 * docstring and explained nothing about it while the interface it is actually
 * about had none. */
export interface DialogueRepository {
  /** Frames a dialogue and returns it, id and framing together. Not a stream:
   *  framing produces three strings and no activity worth watching, and the
   *  id is the server's to mint because it is a row key and a URL segment. */
  start(projectId: ProjectId, topic: string): Promise<DialogueFraming>
  /** Streams one exchange. Rejects with a 404 for an unknown or concluded
   *  dialogue and a 409 for one already running -- both are raised before the
   *  stream opens, so both are status codes. A failure after the first frame
   *  arrives as an `error` event and resolves, so a caller that only handles
   *  rejection will show a turn that silently stops. */
  reply(
    projectId: ProjectId,
    dialogueId: string,
    reply: string,
    onEvent: (event: DialogueEvent) => void,
    signal?: AbortSignal,
  ): Promise<void>
  /** Marks one answer to a component the dialogue asked. The key never left
   *  the server, so the browser cannot grade it.
   *
   *  Unlike `submitAskAttempt` this attempt is *recorded* against the dialogue
   *  id, and `progress` below is what reads it back -- which is what makes the
   *  recording visible to a reader rather than only true in the log. */
  submitDialogueAttempt(
    projectId: ProjectId,
    dialogueId: string,
    input: { position: number; componentId: ComponentId; response: AttemptResponse },
  ): Promise<Verdict>
  /** Everything this reader has had marked in this dialogue.
   *
   * The whole argument for this surface being its own principal: an ask
   * discards an attempt and a dialogue keeps one, so this is the call that
   * makes "your answers survive a refresh" true on screen and not just in
   * storage. An untouched dialogue answers `{}` rather than rejecting. */
  progress(projectId: ProjectId, dialogueId: string): Promise<DialogueProgress>
  /** Ends a dialogue because the reader chose to stop.
   *
   * POST and not DELETE: nothing is removed -- the dialogue, its turns and
   * every marked answer stay readable, and the wrong verb would tell a reader
   * otherwise.
   *
   * There is no matching read: nothing here reads one dialogue whole, so the
   * fact that the reader ended it lives only in the store for this session.
   * The server does carry it -- `_dialogue_view` sends `concludedReason` -- and
   * B120's `read(projectId, dialogueId)` is where it would arrive from.
   *
   * Rejects with a 409 when the dialogue had already concluded, most likely
   * because the model concluded it on the previous turn. That is not a
   * failure: the reader wanted it stopped and it is stopped. It is a separate
   * status rather than a success because the caller must not then claim the
   * reader ended it. */
  end(projectId: ProjectId, dialogueId: string): Promise<void>
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

/** How much of the log to read, beside *which* of it.
 *
 * Separate from `InteractionFilters` rather than folded into it, because the
 * two have different lifetimes: a filter is in the URL and is a bookmark, and
 * a page cursor is the pane scrolling. Putting `offset` in the route would put
 * a scroll position in every link somebody sent.
 */
export interface InteractionWindow {
  readonly limit?: number
  readonly offset?: number
  /** `newest` is the server's default and the feed's. `oldest` is the session
   *  drill-down, where a visit reads as a story only in the order it
   *  happened. */
  readonly order?: 'newest' | 'oldest'
}

/** Reading the interaction log back.
 *
 * Its own port rather than methods on `InteractionSink`
 * (`@application/ports/interaction-log.ts`): the sink batches, drops on
 * failure and runs on a timer, and this fetches on demand and reports its
 * errors. One object would have two reasons to change, and the sink's
 * deliberate error-swallowing is the last behaviour a read path should
 * inherit.
 */
export interface InteractionLogRepository {
  /** Is the instrument working. Takes no filters: the answer is about the
   *  whole log, and a filtered health reading would be a different question
   *  wearing the same word. */
  health(): Promise<InteractionLogHealth>
  /** Browser sessions, newest first.
   *
   * Takes the same `InteractionFilters` the rest of the page carries, and
   * sends only the four axes this route understands -- install, project and
   * the time window. `kinds` and `views` are dropped rather than passed: the
   * server ignores a parameter it does not know, so passing them would answer
   * the unfiltered question while the filter bar showed a narrowed one. */
  sessions(filters: InteractionFilters, window?: InteractionWindow): Promise<BrowserSessionPage>
  /** One browser session's whole ordered stream. Unpaged, and unfiltered:
   *  the drill-down is a visit read end to end, and a filter over it would
   *  hide the gaps that make it a story. */
  session(id: BrowserSessionId): Promise<readonly LoggedInteraction[]>
  events(filters: InteractionFilters, window?: InteractionWindow): Promise<InteractionPage>
  /** Aggregates over the same window as `events`. No `InteractionWindow`:
   *  a summary of a page rather than of the filtered set would be a number
   *  that changed as somebody scrolled. */
  summary(filters: InteractionFilters): Promise<InteractionSummary>
}

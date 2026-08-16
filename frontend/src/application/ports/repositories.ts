import type { Approval, ApprovalAnswer } from '@domain/approval/approval.ts'
import type { AskEvent } from '@domain/ask/conversation.ts'
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
import type { Timeline } from '@domain/knowledge/timeline.ts'
import type { ComponentAudience, LessonDocument } from '@domain/lesson/document.ts'
import type { AttemptResponse, ItemProgress, Verdict } from '@domain/lesson/attempt.ts'
import type { Course } from '@domain/project/course.ts'
import type { Project, WorkflowPreset } from '@domain/project/project.ts'
import type {
  DocumentText,
  MediaSummary,
  SourceSummary,
  TextSummary,
} from '@domain/research/document.ts'
import type { ExtractionQueueBoard } from '@domain/research/extraction-queue.ts'
import type { IgnoredMedia, MediaProposalGroup } from '@domain/research/media-proposal.ts'
import type { ResearchRun } from '@domain/research/run.ts'
import type { Dispatch } from '@domain/research/dispatch.ts'
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
  /** Send an agent at one topic. Answers with the dispatch as *queued*, not
   *  running: the server has scheduled it and not started it when this
   *  resolves, and the `running` frame follows over the live feed.
   *
   *  Never rejects with a 409, unlike `startSeed` — a control that appears on
   *  every topic row cannot answer "the project is busy" to every second
   *  press, so a busy project queues. Rejects 404 for a topic this project
   *  does not have and 422 for an action this build does not run. */
  dispatch(projectId: ProjectId, topicId: TopicId, action: string): Promise<Dispatch>
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

export interface TimelineRepository {
  /** The project's dated entities in time order, up to the server's cap.
   *
   * `undatedCount` on the result is not optional dressing -- most entities in
   * a real graph carry no dates, so a timeline is a view of a minority of the
   * corpus and the caller must show the denominator. `truncated` says the cap
   * bit, the same way `WholeGraph.truncated` does. */
  timeline(projectId: ProjectId, entityType?: string): Promise<Timeline>
}

export interface WorkerRepository {
  /** Everything in flight on a project. Rejects when this build has no
   *  roster, which a caller must distinguish from an empty one. */
  on(projectId: ProjectId): Promise<Roster>
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

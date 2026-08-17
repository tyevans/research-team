import type { ComponentAudience } from '@domain/lesson/document.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { ProjectId, SessionId, SourceId, TopicId } from '@domain/shared/identifier.ts'

/** Cache keys, in one place.
 *
 * Two rules, both learned from the code this replaces. Every key that reads a
 * *fold* carries its scrub point, because the same path at two points is two
 * different documents and a shared key would show one under the other's
 * heading. And every key is built here rather than spelled out at the call
 * site, because an invalidation that misspells a key silently does nothing.
 */
export const queryKeys = {
  sessions: () => ['sessions'] as const,
  tree: () => ['tree'] as const,
  projects: () => ['projects'] as const,
  presets: () => ['presets'] as const,
  health: () => ['health'] as const,

  /** Deliberately unparameterised. The autonomy policy is one object serving
   *  the whole instance, so keying it by session or project would give the
   *  drawer and the course panel separate caches over the same state — and
   *  they would disagree the moment either wrote. One key means one write
   *  corrects both. */
  autonomy: () => ['autonomy'] as const,

  course: (project: ProjectId) => ['course', project] as const,
  run: (project: ProjectId) => ['run', project] as const,
  workers: (project: ProjectId) => ['workers', project] as const,
  /** Every project's run and worker state at once.
   *
   * The landing page draws one live marker per project row and has no list of
   * which projects to invalidate -- the rows it drew are the virtualizer's
   * business, not the invalidator's. These are prefixes rather than keys, and
   * they are here for the reason every other key is: an invalidation that
   * misspells one silently does nothing. */
  allRuns: () => ['run'] as const,
  allWorkers: () => ['workers'] as const,
  /** Everything running anywhere, as one cached answer.
   *
   * Deliberately under the `allWorkers()` prefix rather than beside it, so the
   * invalidation the landing page already fires refreshes this too. The widget
   * is on every page and the landing page is one of them; two keys would have
   * the row markers and the widget disagreeing about the same instant. */
  runningAgents: () => ['workers', 'all'] as const,
  topics: (project: ProjectId) => ['topics', project] as const,
  topic: (project: ProjectId, topic: TopicId) => ['topic', project, topic] as const,
  seed: (project: ProjectId) => ['seed', project] as const,
  /** One key for the whole project's dispatches, not one per topic.
   *
   * The catch-up route answers running, queued and finished in a single read,
   * and every dispatch frame changes at most one of those three -- so forty
   * topic rows share one cache entry and one invalidation, rather than forty
   * entries the same frame would have to know which of to touch. */
  dispatch: (project: ProjectId) => ['dispatch', project] as const,
  /** Per topic, unlike `dispatch` above: this listing is one topic's directory
   *  and a dispatch on another topic cannot change it. */
  topicDocuments: (project: ProjectId, topic: TopicId) =>
    ['topic-documents', project, topic] as const,
  documents: (project: ProjectId) => ['documents', project] as const,
  /** One key for the whole project's extraction queue, for `dispatch`'s
   *  reason: the catch-up route answers running, queued and finished in a
   *  single read, so a corpus of hundreds shares one cache entry rather than
   *  one per row. Separate from `documents` because they answer different
   *  questions -- what the corpus holds, and what is being done to it -- and a
   *  press that changes only the second should not refetch the first. */
  extractionQueue: (project: ProjectId) => ['extraction-queue', project] as const,
  /** Ranged reads are their own key, distinct from the whole-document read
   *  `range` omitted gives -- a range and the full text are two different
   *  responses over the same source, and sharing a key would show one
   *  under the other's cache entry. */
  document: (project: ProjectId, source: SourceId, range?: { start?: number; end?: number }) =>
    ['document', project, source, range?.start ?? null, range?.end ?? null] as const,

  /** One key for a project's whole set of media proposals, matching
   *  `dispatch`'s reasoning: the listing route answers every need's group in
   *  one read, and a card's accept/reject/ignore invalidates the same key a
   *  sibling card's press would. */
  mediaProposals: (project: ProjectId) => ['media-proposals', project] as const,
  /** Separate from `mediaProposals` above rather than folded in, because an
   *  ignore changes both and a reject changes neither -- a shared key would
   *  make either write refetch a list it did not touch. */
  ignoredMedia: (project: ProjectId) => ['ignored-media', project] as const,

  /** The graph itself is a zustand store, not a query cache -- see
   *  `graph-store.ts` -- so this is the first graph-shaped key here. Keyed by
   *  entity id, not by project alone: the panel that reads this opens on one
   *  entity at a time, and a shared key would show one entity's passages
   *  under another's heading the moment a reader picked a different node. */
  usages: (project: ProjectId, entityId: string) => ['usages', project, entityId] as const,
  /** Its own key rather than folded into `usages` above: they are two
   *  separate requests (see `use-definition.ts`'s own docstring for why),
   *  and a shared key would make a definition refetch invalidate the
   *  passages too, and vice versa. */
  definition: (project: ProjectId, entityId: string) => ['definition', project, entityId] as const,
  /** One entity-name lookup, shared by every resolved widget on the page.
   *
   * Keyed on the name rather than on the component id: an answer that cites
   * "Constantine" in a `definition` and again in a `graph` is one search, not
   * two, and keying by component would make the same question a cache miss
   * per widget. Not the zustand graph store (`graph-store.ts:85`) for the
   * spec's reason -- that store is per-project console state with selection
   * and expansion in it, and a widget wants a cached read rather than a share
   * in someone else's cursor. */
  entityReference: (project: ProjectId, name: string) =>
    ['entity-reference', project, name] as const,
  /** One entity's neighbourhood at one depth. Depth is in the key rather than
   *  refetched over: two widgets on the same entity at depths 1 and 2 are two
   *  different graphs, and a shared key would draw one under the other. */
  neighborhood: (project: ProjectId, entityId: string, depth: number) =>
    ['neighborhood', project, entityId, depth] as const,
  /** One project's discovered classes. Keyed on the project alone: the view
   *  shows all of them at once, and a per-class key would be a cache entry
   *  nothing ever reads on its own. */
  ontology: (project: ProjectId) => ['ontology', project] as const,

  file: (session: SessionId, path: FilePath, at: ScrubPoint) =>
    ['file', session, path.value, ScrubPoint.toNullable(at)] as const,
  fileHistory: (session: SessionId, path: FilePath) =>
    ['file-history', session, path.value] as const,
  lesson: (session: SessionId, path: FilePath, audience: ComponentAudience, at: ScrubPoint) =>
    ['lesson', session, path.value, audience, ScrubPoint.toNullable(at)] as const,
  lessonProgress: (session: SessionId, path: FilePath) =>
    ['lesson-progress', session, path.value] as const,
} as const

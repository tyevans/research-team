import type { ComponentAudience } from '@domain/lesson/document.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type {
  BrowserSessionId,
  ProjectId,
  SessionId,
  SourceId,
  TopicId,
} from '@domain/shared/identifier.ts'
import type { InteractionFilters } from '@domain/interaction/filters.ts'
import type { InteractionWindow } from '@application/ports/repositories.ts'

/** Cache keys, in one place.
 *
 * Two rules, both learned from the code this replaces. Every key that reads a
 * *fold* carries its scrub point, because the same path at two points is two
 * different documents and a shared key would show one under the other's
 * heading. And every key is built here rather than spelled out at the call
 * site, because an invalidation that misspells a key silently does nothing.
 */
/** A filter, flattened into a stable key fragment.
 *
 * Every field, in a fixed order, so two structurally equal filters produce
 * equal keys whatever order their object literals were written in --
 * React Query hashes the key structurally, and an object spread in a
 * different order would be a cache miss that looks like a stale render.
 * The arrays go in as arrays rather than joined: a `views` of `['a,b']` and
 * one of `['a', 'b']` are different filters, and joining would collapse them. */
const filterKey = (filters: InteractionFilters) =>
  [
    filters.kinds,
    filters.views,
    filters.projectId,
    filters.installId,
    filters.browserSessionId,
    filters.since,
    filters.until,
  ] as const

/** `null` for each absent field rather than an absent key, so an unwindowed
 *  read and one that happens to ask for the server's own default are still
 *  distinguishable -- they are different requests (`page` in
 *  `interaction-log-query-repository.ts` omits rather than defaults) and
 *  collapsing them would serve one under the other. */
const windowKey = (window?: InteractionWindow) =>
  [window?.limit ?? null, window?.offset ?? null, window?.order ?? null] as const

export const queryKeys = {
  sessions: () => ['sessions'] as const,
  tree: () => ['tree'] as const,
  projects: () => ['projects'] as const,
  health: () => ['health'] as const,

  /** Deliberately unparameterised. The autonomy policy is one object serving
   *  the whole instance, so keying it by session or project would give the
   *  drawer and the queue's panel separate caches over the same state — and
   *  they would disagree the moment either wrote. One key means one write
   *  corrects both. */
  autonomy: () => ['autonomy'] as const,

  /** One project's identity and holder. Its own key rather than a slice of
   *  `projects()`: that key is the landing page's whole list as one cache
   *  entry, and a project page invalidating it would refetch every row to
   *  refresh one. */
  project: (project: ProjectId) => ['project', project] as const,

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
  /** One window over the timeline. Every bound is in the key: two widgets
   *  asking for two centuries are two different answers, and a key on the
   *  project alone would show one century's bands under the other's heading
   *  -- the same mistake `document`'s range key exists to avoid. */
  timeline: (
    project: ProjectId,
    window: {
      entityType?: string | null
      from?: string | null
      to?: string | null
      limit?: number | null
    },
  ) =>
    [
      'timeline',
      project,
      window.entityType ?? null,
      window.from ?? null,
      window.to ?? null,
      window.limit ?? null,
    ] as const,
  /** One project's discovered classes. Keyed on the project alone: the view
   *  shows all of them at once, and a per-class key would be a cache entry
   *  nothing ever reads on its own. */
  ontology: (project: ProjectId) => ['ontology', project] as const,
  /** The discovery sweep's work list. A key of its own rather than a slice of
   *  `ontology`, because the two invalidate on different events: a pass that
   *  reads a barren document changes this list and adds no class. */
  ungroupedSources: (project: ProjectId) => ['ontology', 'ungrouped', project] as const,

  /** A project's areas and the path through them.
   *
   * One key for both halves because one request answers both, and because they
   * are computed from one read of the graph -- two keys would let a cache serve
   * a map from one projection beside an order from another. */
  curriculum: (project: ProjectId) => ['curriculum', project] as const,

  /** One area's full membership. Under the curriculum prefix so invalidating
   *  the projection invalidates every area page opened from it. */
  learningArea: (project: ProjectId, slug: string) =>
    ['curriculum', project, 'area', slug] as const,

  /** Whether an authoring run is in flight. Its own prefix, deliberately: it
   *  is polled while a run is running, and sharing the curriculum's key would
   *  refetch the clustering pass on every poll. */
  authoring: (project: ProjectId) => ['authoring', project] as const,

  /** The whole front page in one key, matching `curriculum`'s reasoning: one
   *  request answers hero, highlights and every filed category, so a feature
   *  or unfeature invalidates the one cache entry that shows all three.
   *
   *  `includeUnnamed` is part of the key, not a separate flag checked after
   *  the fact -- the server filters before sectioning (`CatalogService.build`),
   *  so "show unnamed" and "hide unnamed" are genuinely different response
   *  bodies (different hero/highlights membership, not just a client-side
   *  filter over one shared payload) and belong in separate cache entries. */
  catalog: (project: ProjectId, includeUnnamed: boolean) =>
    ['catalog', project, includeUnnamed] as const,

  /** One catalog course's detail page, keyed by slug beside `catalog` rather
   *  than under it -- a realize/abandon invalidates this one course, not the
   *  whole front page's cache entry. Named `courseDetail` rather than
   *  `course`: `queryKeys.course` was taken until the workflow system came
   *  out, by the unrelated `Course` a project's stage rail was folded from.
   *  The name is free now and the rename is not worth the churn. */
  courseDetail: (project: ProjectId, slug: string) => ['course-detail', project, slug] as const,

  /** One course's authored markdown, keyed apart from `courseDetail` on
   *  purpose. The detail is invalidated by realize, abandon, a blurb sweep and
   *  an art reroll -- four writes that change nothing about the text -- and
   *  the text is the largest payload on the page. Sharing a key would refetch
   *  a whole course every time somebody rerolled its picture. */
  courseText: (project: ProjectId, slug: string) => ['course-text', project, slug] as const,

  /** Where the last (or current) blurb sweep on this project stands --
   *  its own key, not folded into `catalog`: it is polled on its own
   *  interval while a sweep runs, and sharing `catalog`'s key would refetch
   *  the whole front page on every poll. */
  blurbSweep: (project: ProjectId) => ['blurb-sweep', project] as const,

  /** Where the last (or current) art sweep on this project stands -- its
   *  own key, matching `blurbSweep`'s own reasoning above. */
  artSweep: (project: ProjectId) => ['art-sweep', project] as const,

  /** Where the last (or current) reroll of one candidate's art stands --
   *  keyed by slug, not just project, matching `courseDetail`'s reasoning:
   *  two cards rerolling at once must not share one poll. */
  artReroll: (project: ProjectId, slug: string) => ['art-reroll', project, slug] as const,

  /** The interaction log's read side, all under one prefix.
   *
   * A namespace rather than five top-level keys, so the explorer's refetch
   * interval invalidates the page with `['interactions']` and nothing else on
   * the app has to be listed. Nested under it rather than beside it for
   * `runningAgents`' reason: one prefix, one invalidation.
   *
   * Every filtered key carries the whole filter, serialised the same way the
   * URL carries it. Two windows over the same log are two different answers,
   * and a key on the route name alone would show last Tuesday's counts under
   * this hour's heading -- the mistake `document`'s range key and `timeline`'s
   * window key both exist to avoid. */
  interactions: {
    all: () => ['interactions'] as const,
    /** Unfiltered on purpose: health is a fact about the whole log, and a
     *  filtered reading of it would be a different question wearing the same
     *  word. One cache entry, whatever the filter bar says. */
    health: () => ['interactions', 'health'] as const,
    sessions: (filters: InteractionFilters, window?: InteractionWindow) =>
      ['interactions', 'sessions', filterKey(filters), windowKey(window)] as const,
    /** One browser session's stream. Keyed by id alone -- the drill-down is
     *  unfiltered and unpaged, so there is nothing else that could change the
     *  answer. */
    session: (id: BrowserSessionId) => ['interactions', 'session', id] as const,
    events: (filters: InteractionFilters, window?: InteractionWindow) =>
      ['interactions', 'events', filterKey(filters), windowKey(window)] as const,
    /** No window: the summary is over the filtered set, not over a page, so
     *  scrolling the feed must not refetch it. */
    summary: (filters: InteractionFilters) =>
      ['interactions', 'summary', filterKey(filters)] as const,
  },

  file: (session: SessionId, path: FilePath, at: ScrubPoint) =>
    ['file', session, path.value, ScrubPoint.toNullable(at)] as const,
  fileHistory: (session: SessionId, path: FilePath) =>
    ['file-history', session, path.value] as const,
  lesson: (session: SessionId, path: FilePath, audience: ComponentAudience, at: ScrubPoint) =>
    ['lesson', session, path.value, audience, ScrubPoint.toNullable(at)] as const,
  lessonProgress: (session: SessionId, path: FilePath) =>
    ['lesson-progress', session, path.value] as const,
} as const

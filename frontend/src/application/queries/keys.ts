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
  /** Ranged reads are their own key, distinct from the whole-document read
   *  `range` omitted gives -- a range and the full text are two different
   *  responses over the same source, and sharing a key would show one
   *  under the other's cache entry. */
  document: (project: ProjectId, source: SourceId, range?: { start?: number; end?: number }) =>
    ['document', project, source, range?.start ?? null, range?.end ?? null] as const,

  file: (session: SessionId, path: FilePath, at: ScrubPoint) =>
    ['file', session, path.value, ScrubPoint.toNullable(at)] as const,
  fileHistory: (session: SessionId, path: FilePath) =>
    ['file-history', session, path.value] as const,
  lesson: (session: SessionId, path: FilePath, audience: ComponentAudience, at: ScrubPoint) =>
    ['lesson', session, path.value, audience, ScrubPoint.toNullable(at)] as const,
  lessonProgress: (session: SessionId, path: FilePath) =>
    ['lesson-progress', session, path.value] as const,
} as const

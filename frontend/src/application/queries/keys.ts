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
  topics: (project: ProjectId) => ['topics', project] as const,
  topic: (project: ProjectId, topic: TopicId) => ['topic', project, topic] as const,
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

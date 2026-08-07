import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import {
  hasComponents,
  type ComponentAudience,
  type LessonDocument,
} from '@domain/lesson/document.ts'
import type { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

export interface Lesson {
  readonly doc: LessonDocument | null
  /** Whether this document is worth rendering through the component pipeline
   *  at all — and, separately, whether the author/learner toggle has anything
   *  to switch between. */
  readonly interactive: boolean
}

/** The parsed form of an open markdown file.
 *
 * One hook, so the two questions asked of a parse — "render the widgets" and
 * "is there anything to withhold, so should the audience toggle appear" — come
 * from one query rather than from two that could disagree.
 *
 * A second request rather than a replacement for the raw contents, because the
 * source toggle and every non-markdown file still need the bytes — and because
 * a parse failure must never cost the reader the file itself. On any error the
 * viewer falls back to rendering the markdown the way it always has, silently:
 * an error banner over a document that displays perfectly well would be noise.
 */
export const useLesson = (
  sessionId: SessionId,
  path: FilePath | null,
  audience: ComponentAudience,
  at: ScrubPoint,
  enabled: boolean,
): Lesson => {
  const { lessons } = useContainer()

  const query = useQuery({
    queryKey: path ? queryKeys.lesson(sessionId, path, audience, at) : ['lesson', 'none'],
    queryFn: () => lessons.parse(sessionId, path!, audience, at),
    enabled: enabled && path !== null && path.isMarkdown,
    retry: false,
  })

  const doc = query.data ?? null
  return { doc, interactive: hasComponents(doc) }
}

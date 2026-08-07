import { FilePath } from '../shared/file-path.ts'
import type { EventIndex } from '../session/event-index.ts'

/** One file in the workspace, as of the point being read. */
export interface WorkspaceFile {
  readonly path: FilePath
  readonly size: number
  readonly revisions: number
}

/** One recorded change to a path.
 *
 * `oldString`/`newString` are present only when the change was an *edit* — the
 * agent's stated intent, recorded at the time. A write records no intent, so
 * the viewer reconstructs a diff against the previous revision instead. Keeping
 * the distinction in the type is what stops that reconstruction from being
 * presented as something the log actually said.
 */
export interface FileRevision {
  readonly index: EventIndex
  readonly type: string
  readonly occurredAt: string
  readonly content: string | null
  readonly oldString: string | null
  readonly newString: string | null
  readonly replaceAll: boolean | null
}

const hasRecordedIntent = (
  revision: FileRevision,
): revision is FileRevision & { oldString: string; newString: string } =>
  typeof revision.oldString === 'string' && typeof revision.newString === 'string'

/** The two texts a revision's diff should be drawn from.
 *
 * Where an edit intent was recorded that is the answer outright. Otherwise the
 * previous revision's contents stand in for "before", so a write is still shown
 * as a change rather than as a wall of unchanged lines — and a creation and a
 * removal are named, because a diff against nothing reads identically in both
 * directions. */
export const diffSubject = (
  revision: FileRevision,
  previous: FileRevision | null,
): { readonly before: string; readonly after: string; readonly note: string | null } => {
  if (hasRecordedIntent(revision)) {
    return { before: revision.oldString, after: revision.newString, note: null }
  }
  const before = previous?.content ?? ''
  const after = revision.content ?? ''
  if (!before && after) return { before, after, note: 'created — full contents:' }
  if (before && !after) return { before, after, note: 'removed' }
  return { before, after, note: null }
}

export const findFile = (
  files: readonly WorkspaceFile[],
  path: FilePath | null,
): WorkspaceFile | null =>
  path === null ? null : (files.find((file) => file.path.equals(path)) ?? null)

import type { FilePath } from '@domain/shared/file-path.ts'
import type { SessionId } from '@domain/shared/identifier.ts'

/** One file a dispatch wrote about a topic. */
export interface TopicDocument {
  readonly path: FilePath
  /** The path relative to the topic's own directory. `understanding.md` today,
   *  and the reason it is not just `path.basename`: a nested file would read
   *  as its bare name and collide with another directory's. */
  readonly name: string
}

/** Everything written about one topic, and where to read it from.
 *
 * **`sessionId` is the load-bearing half.** Every reader of a file in this
 * console is keyed by `(sessionId, path)` — the raw contents, the parsed
 * document with its components, and the attempt route that grades against it.
 * A dispatch writes on a session it creates and releases, and nothing on the
 * research view knows which one that was. The server resolves it once (as the
 * project's *reading head*), so this viewer reuses `useLesson` and `readFile`
 * unchanged rather than growing a project-scoped copy of each beside them.
 *
 * **There is no `at` beside it, and there used to be.** It carried the tip
 * offset, on the argument that a released session may have run on past the tip
 * — and it was measured on 2026-08-27 to name a point at which a document this
 * same response listed did not exist. HEAD is the answer in every branch, so
 * the reader writes `ScrubPoint.head()` at the point of use.
 *
 * `sessionId` is null for a project that has never been joined — which is
 * exactly the project that has no documents either, so a viewer that checks
 * `documents.length` first never has to think about it.
 */
export interface TopicDocuments {
  readonly directory: string
  readonly sessionId: SessionId | null
  readonly documents: readonly TopicDocument[]
}

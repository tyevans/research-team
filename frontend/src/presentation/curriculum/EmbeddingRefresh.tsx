import type { DerivedFrom } from '@domain/knowledge/curriculum.ts'

/** Ask for this project's entities to be embedded again.
 *
 * **Why a person has to ask.** Vectors are written when an entity is
 * extracted, and folding the log at project open must never depend on a live
 * embedding endpoint — a project reopened years from now has to open. So
 * nothing re-embeds on its own, and two states that look identical on screen
 * are not: a project ingested before entity vectors were durable has none at
 * all, and an entity that gained relationships after it was first seen carries
 * a vector that predates them.
 *
 * **The prompt changes with the state and the button does not.** A projection
 * that used no embeddings is missing a whole signal and says so plainly; one
 * that used them is merely out of date, which is a weaker claim and gets a
 * weaker sentence. Offering the action in both cases is deliberate: the graph
 * keeps moving, so "already embedded" is never "finished".
 */
export const EmbeddingRefresh = ({
  derivedFrom,
  pending,
  embedded,
  error,
  onRefresh,
}: {
  derivedFrom: DerivedFrom
  pending: boolean
  embedded: number | null
  error: string | null
  onRefresh: () => void
}) => (
  <div className="flex flex-wrap items-center gap-2 rounded-md border border-line bg-bg-panel p-3">
    <p className="m-0 min-w-0 flex-1 text-xs text-fg-dim">
      {derivedFrom.usedEmbeddings ? (
        <>
          {derivedFrom.semanticEdges} links came from meaning rather than from a stated
          relationship. Embeddings are computed when an entity is extracted, so an entity that has
          gained connections since carries an older reading of itself.
        </>
      ) : (
        <>
          These areas were clustered on the graph alone. Nothing here has been embedded, so two
          entities about the same subject stay apart unless a document named them together.
        </>
      )}
    </p>
    <button
      type="button"
      onClick={onRefresh}
      disabled={pending}
      className="focus-visible:lay-ring-inward shrink-0 rounded-md border border-line bg-bg-raise px-2 py-1 text-xs text-fg hover:bg-bg-hover disabled:opacity-60"
    >
      {pending ? 'Embedding…' : derivedFrom.usedEmbeddings ? 'Re-embed entities' : 'Embed entities'}
    </button>
    {/* The count, and specifically not a bare "done". Zero is a real answer --
        it is what a build with embeddings switched off returns -- and it is
        the one outcome a reader would otherwise read as success. */}
    {embedded !== null && !pending && (
      <p className="m-0 w-full text-xs text-fg-dim">
        {embedded === 0
          ? 'Nothing was embedded. This build has embeddings switched off, or the project has no entities.'
          : `${embedded} entities embedded. The areas below have been reprojected.`}
      </p>
    )}
    {error !== null && <p className="m-0 w-full text-xs text-k-failure">{error}</p>}
  </div>
)

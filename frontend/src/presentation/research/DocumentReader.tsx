import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { ErrorBox, Loading } from '../common/primitives.tsx'

/** One document's text, read fresh rather than reused from the list row --
 *  `DocumentSummary` carries no `text`, on purpose, so this is the only
 *  place in the pane that ever asks the server for it. */
export const DocumentReader = ({
  projectId,
  sourceId,
}: {
  projectId: ProjectId
  sourceId: SourceId
}) => {
  const { documents } = useContainer()

  const query = useQuery({
    queryKey: queryKeys.document(projectId, sourceId),
    queryFn: () => documents.read(projectId, sourceId, undefined),
  })

  if (query.isPending) return <Loading what="document" />

  if (query.isError) {
    return (
      <ErrorBox
        heading="Could not read this document"
        message={query.error instanceof Error ? query.error.message : String(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  const document = query.data

  return (
    // No heading of its own: this renders inside a drawer that already names
    // the document in its header, and two copies of the same title stacked on
    // each other is chrome, not information. The title-or-id fallback moved to
    // the drawer with it, where it is taken from the list row so the heading is
    // right while this component's own fetch is still in flight.
    // Its own padding rather than the drawer's, because this is rendered
    // outside a drawer too. `pb-5` is larger than the top on purpose: prose
    // wants room under its last line where a panel does not.
    //
    // The text gets a measure. Full-width lines across a 640px drawer are the
    // same reason this was hard to read in the old 340px rail, at the other
    // extreme.
    <article className="px-4 pt-[12px] pb-5">
      {document.droppedReason ? (
        <p className="m-0 mb-[8px] text-xs text-k-failure">Dropped: {document.droppedReason}</p>
      ) : null}
      {/* No `m-0`, deliberately: `.document-reader-text` never reset the user
          agent's 1em block margin either, and this build imports no preflight,
          so the paragraph has always had it. Adding the reset here would be an
          undeclared spacing change riding along on a dressing change. */}
      <p className="max-w-[68ch] text-sm leading-[1.65] whitespace-pre-wrap">{document.text}</p>
    </article>
  )
}

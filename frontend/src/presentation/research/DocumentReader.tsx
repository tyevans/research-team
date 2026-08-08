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
        title="Could not read this document"
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
    <article className="document-reader">
      {document.droppedReason ? (
        <p className="document-reader-dropped">Dropped: {document.droppedReason}</p>
      ) : null}
      <p className="document-reader-text">{document.text}</p>
    </article>
  )
}

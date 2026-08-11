import type { ProjectId } from '@domain/shared/identifier.ts'

import { Drawer } from '../common/Drawer.tsx'
import { ErrorBox, Loading } from '../common/primitives.tsx'
import { DocumentBrowser } from './DocumentBrowser.tsx'
import { DocumentReader } from './DocumentReader.tsx'
import { useDocuments } from './use-documents.ts'

/** The project's corpus: a container around `DocumentBrowser`.
 *
 * Owns the two fetch-shaped states and the reader drawer, which needs a
 * `projectId` to fetch the document's text and therefore cannot live in a
 * presentational component.
 */
export const DocumentList = ({ projectId }: { projectId: ProjectId }) => {
  const { query, reading, onClose, readingLabel, browser } = useDocuments(projectId)

  if (query.isPending) return <Loading what="documents" />

  if (query.isError) {
    return (
      <ErrorBox
        heading="Could not read this project's documents"
        message={query.error instanceof Error ? query.error.message : String(query.error)}
        onRetry={() => void query.refetch()}
      />
    )
  }

  return (
    <>
      <DocumentBrowser {...browser} />
      {/* Over the page, not below the list. The list lives in a 340px rail,
          and a document is a wall of prose -- read in that column it was a few
          words per line under a list that had been pushed up out of the way.
          The drawer is the console's existing answer to "read this without
          losing where you were", and a source is exactly that kind of thing:
          you open one, read it, and go back to the graph you were looking
          at. */}
      {reading ? (
        <Drawer
          heading={readingLabel(reading)}
          label={`Reading ${readingLabel(reading)}`}
          onClose={onClose}
        >
          <DocumentReader projectId={projectId} sourceId={reading} />
        </Drawer>
      ) : null}
    </>
  )
}

import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { Drawer } from '../common/Drawer.tsx'
import { ErrorBox, Loading } from '../common/primitives.tsx'
import { DocumentBrowser } from './DocumentBrowser.tsx'
import { DocumentManagePane } from './DocumentManagePane.tsx'
import { DocumentUpload } from './DocumentUpload.tsx'
import { useDocuments } from './use-documents.ts'

/** The project's corpus: a container around `DocumentBrowser`.
 *
 * Owns the two fetch-shaped states and the reader drawer, which needs a
 * `projectId` to fetch the document's text and therefore cannot live in a
 * presentational component.
 */
export const DocumentList = ({
  projectId,
  open = null,
  seekSeconds = null,
  onOpen,
}: {
  projectId: ProjectId
  /** The route's `doc` id. See `useDocuments`, which says what this being
   *  `useState` cost. */
  open?: SourceId | null
  /** The route's `?t=`, passed straight through to `DocumentReader` on the
   *  open document -- this component has no player of its own to seek. */
  seekSeconds?: number | null
  onOpen?: (sourceId: SourceId | null) => void
}) => {
  const { query, reading, onClose, readingLabel, browser, adding, onAddClose } = useDocuments(
    projectId,
    open,
    onOpen,
  )

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
      {/* Beside the reader drawer rather than inside it: adding a document and
          reading one are independent -- a reader mid-add has nothing open yet,
          and the corpus keys `reading`/`adding` off separate state so both can
          never fight over the same drawer slot. */}
      {adding ? <DocumentUpload projectId={projectId} onClose={onAddClose} /> : null}
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
          // `DocumentReader` carries its own 12/14/20 and its own measure, and
          // it is rendered outside a drawer too -- so its padding cannot move
          // here without following it everywhere else.
          flush
        >
          {/* Keyed on the open document rather than left to update in place.
              The rail behind the drawer stays clickable while it's open, so a
              reader can switch documents while `DocumentManagePane` is showing
              the edit form -- and nothing in that pane or `DocumentEditForm`
              resets its own `useState` on a prop change, so the fields would
              keep the old document's values while `document.sourceId` in the
              submit payload silently became the new one. The key remounts
              only this pane, discarding its local `editing`/`dropping` state
              and the edit form's fields with it; `DocumentReader` underneath
              is unaffected either way, since its fetch is already keyed on
              `sourceId` through `queryKeys.document` and refetches on a
              prop change without needing a remount. */}
          <DocumentManagePane
            key={reading}
            projectId={projectId}
            sourceId={reading}
            document={(query.data ?? []).find((row) => row.sourceId === reading) ?? null}
            seekSeconds={seekSeconds}
          />
        </Drawer>
      ) : null}
    </>
  )
}

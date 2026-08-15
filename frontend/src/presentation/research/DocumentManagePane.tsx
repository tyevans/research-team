import { useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { useRestoreDocument } from '@application/research/use-document-writes.ts'
import type { DocumentSummary } from '@domain/research/document.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { DocumentDropDialog } from './DocumentDropDialog.tsx'
import { DocumentEditForm } from './DocumentEditForm.tsx'
import { DocumentReader } from './DocumentReader.tsx'

/** An action bar over `DocumentReader`, in the reader drawer rather than on
 *  the browser row -- the rows are virtualized against a 52px estimate in a
 *  340px rail and already carry two controls whose ring geometry a browser
 *  test pins. The drawer has 640px, and every action here is a decision made
 *  having read the thing.
 *
 * `document` is the summary the list already has from `query.data`, not a
 * second fetch -- `DocumentReader` still does its own read for the text, and
 * `DocumentSummary` is what decides whether this document is live or
 * dropped. It can be `null` while the list is still loading or the row has
 * been filtered out from under an open document, in which case only the
 * reader renders.
 */
export const DocumentManagePane = ({
  projectId,
  sourceId,
  document,
}: {
  projectId: ProjectId
  sourceId: SourceId
  document: DocumentSummary | null
}) => {
  const restore = useRestoreDocument(projectId)
  const [editing, setEditing] = useState(false)
  const [dropping, setDropping] = useState(false)

  const handleRestore = () => {
    restore.mutate(sourceId, {
      onSuccess: () => notify('Document restored'),
      onError: (error) => notify(errorMessage(error), 'bad'),
    })
  }

  return (
    <div className="flex flex-col">
      {document ? (
        <div className="mb-[8px] flex justify-end gap-2 px-4 pt-[12px]">
          {editing ? null : document.droppedReason === null ? (
            <>
              <Button onClick={() => setEditing(true)}>Edit</Button>
              <Button tone="danger" onClick={() => setDropping(true)}>
                Drop
              </Button>
            </>
          ) : (
            // No confirm dialog: restoring is not destructive, and it is the
            // undo for an action that was.
            <Button onClick={handleRestore} disabled={restore.isPending}>
              Restore
            </Button>
          )}
        </div>
      ) : null}

      {editing && document ? (
        <DocumentEditForm
          projectId={projectId}
          document={document}
          onDone={() => setEditing(false)}
        />
      ) : (
        <DocumentReader projectId={projectId} sourceId={sourceId} />
      )}

      {dropping ? (
        <DocumentDropDialog
          projectId={projectId}
          sourceId={sourceId}
          onClose={() => setDropping(false)}
        />
      ) : null}
    </div>
  )
}

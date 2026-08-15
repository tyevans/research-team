import { useId, useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { useDropDocument } from '@application/research/use-document-writes.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { Drawer } from '../common/Drawer.tsx'

/** Built on `Drawer` the way `Confirm.tsx` is, rather than widening `Confirm`
 *  itself: that component takes `lines: readonly string[]` and has no slot
 *  for a field, and adding one for this single caller would put an optional
 *  input on every confirm in the console.
 *
 * The aggregate refuses a blank reason (409). Refused here first too, so the
 * person is told by the field rather than by a toast after a round-trip.
 */
export const DocumentDropDialog = ({
  projectId,
  sourceId,
  onClose,
}: {
  projectId: ProjectId
  sourceId: SourceId
  onClose: () => void
}) => {
  const drop = useDropDocument(projectId)
  const [reason, setReason] = useState('')
  const reasonId = useId()

  const handleDrop = () => {
    const trimmed = reason.trim()
    if (!trimmed) return

    drop.mutate(
      { sourceId, reason: trimmed },
      {
        onSuccess: () => {
          notify('Document dropped')
          onClose()
        },
        onError: (error) => notify(errorMessage(error), 'bad'),
      },
    )
  }

  return (
    <Drawer heading="Drop this document" label="Drop this document" onClose={onClose}>
      <div className="confirm">
        <p>
          The document stops being listed and stops being offered for extraction. Its record and its
          reason are kept, so this can be undone.
        </p>
        <p>
          It is not erased. Anything already extracted from it stays in the graph, and a definition
          written earlier may still quote it.
        </p>

        <label htmlFor={reasonId} className="flex flex-col gap-1 text-sm">
          Reason
          <input
            id={reasonId}
            type="text"
            className="input w-full"
            value={reason}
            onChange={(event) => setReason(event.target.value)}
          />
        </label>

        <div className="confirm-actions">
          <Button onClick={onClose}>Cancel</Button>
          <Button tone="danger" onClick={handleDrop} disabled={drop.isPending}>
            Drop document
          </Button>
        </div>
      </div>
    </Drawer>
  )
}

import { useId, useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { useReviseDocument } from '@application/research/use-document-writes.ts'
import type { DocumentEdit } from '@application/ports/repositories.ts'
import type { DocumentSummary } from '@domain/research/document.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'

/** The upload dialog's fields minus the file picker and minus an editable
 *  identifier -- shown as text rather than a field, because changing it would
 *  create a different document and orphan every citation pointing at the old
 *  one. Initialized from `document` rather than blank, unlike `DocumentUpload`.
 *
 * Only the fields that changed are sent. `DocumentEdit` treats an omitted
 * field as "leave as stored", which is what makes correcting a title not
 * round-trip the prose: sending it back unchanged would cost nothing on the
 * wire, but comparing against the stored value is what proves the omission is
 * deliberate rather than incidental to how the form happens to be built.
 */
export const DocumentEditForm = ({
  projectId,
  document,
  onDone,
}: {
  projectId: ProjectId
  document: DocumentSummary
  onDone: () => void
}) => {
  const revise = useReviseDocument(projectId)

  const [title, setTitle] = useState(document.title ?? '')
  const [uri, setUri] = useState(document.uri ?? '')
  const [note, setNote] = useState(document.note ?? '')
  const [publishedAt, setPublishedAt] = useState(document.publishedAt ?? '')
  const [text, setText] = useState('')

  const titleId = useId()
  const uriId = useId()
  const noteId = useId()
  const publishedAtId = useId()
  const textId = useId()

  const handleSubmit = () => {
    const edit: DocumentEdit = {}
    if (title !== (document.title ?? '')) edit.title = title
    if (uri !== (document.uri ?? '')) edit.uri = uri
    if (note !== (document.note ?? '')) edit.note = note
    if (publishedAt !== (document.publishedAt ?? '')) edit.publishedAt = publishedAt
    // The text field starts blank -- the summary carries no text, and
    // fetching it just to prefill a field most edits never touch would cost a
    // second request for the common case of a metadata-only correction. Left
    // blank, it is never sent; typed into, it is.
    if (text !== '') edit.text = text

    revise.mutate(
      { sourceId: document.sourceId, edit },
      {
        onSuccess: () => {
          notify('Document updated')
          onDone()
        },
        onError: (error) => notify(errorMessage(error), 'bad'),
      },
    )
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-1 text-sm">
        Identifier
        <span className="text-fg-dim">{document.sourceId}</span>
      </div>

      <label htmlFor={titleId} className="flex flex-col gap-1 text-sm">
        Title
        <input
          id={titleId}
          type="text"
          className="input w-full"
          value={title}
          onChange={(event) => setTitle(event.target.value)}
        />
      </label>

      <label htmlFor={uriId} className="flex flex-col gap-1 text-sm">
        URI
        <input
          id={uriId}
          type="text"
          className="input w-full"
          value={uri}
          onChange={(event) => setUri(event.target.value)}
        />
      </label>

      <label htmlFor={noteId} className="flex flex-col gap-1 text-sm">
        Note
        <input
          id={noteId}
          type="text"
          className="input w-full"
          value={note}
          onChange={(event) => setNote(event.target.value)}
        />
      </label>

      <label htmlFor={publishedAtId} className="flex flex-col gap-1 text-sm">
        Published
        <input
          id={publishedAtId}
          type="text"
          className="input w-full"
          value={publishedAt}
          onChange={(event) => setPublishedAt(event.target.value)}
        />
      </label>

      <label htmlFor={textId} className="flex flex-col gap-1 text-sm">
        Text
        <textarea
          id={textId}
          className="input w-full"
          rows={8}
          placeholder="Leave blank to keep the stored text"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </label>

      <div className="flex justify-end gap-2">
        <Button onClick={onDone}>Cancel</Button>
        <Button tone="accent" onClick={handleSubmit} disabled={revise.isPending}>
          Save
        </Button>
      </div>
    </div>
  )
}

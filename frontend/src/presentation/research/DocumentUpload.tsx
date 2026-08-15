import { useId, useRef, useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { useCreateDocument } from '@application/research/use-document-writes.ts'
import type { DocumentDraft } from '@application/ports/repositories.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { Button } from '../common/primitives.tsx'
import { Drawer } from '../common/Drawer.tsx'

/** Lowercase, non-alphanumerics to `-`, collapse and trim `-`. Exported and
 *  covered on its own because it is the default a person overtypes rather
 *  than the identifier itself -- a bad default silently orphaning citations
 *  is worth a direct test, not just the form test that goes through it. */
export const slugify = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

/** The "Add document" dialog: a file picker that reads text client-side, or a
 *  form filled by hand, both landing on the same `DocumentDraft`.
 *
 * The file is read with `await file.text()` rather than posted as multipart.
 * The corpus stores text and nothing in this tree decodes a binary document
 * format, so a multipart endpoint would have spent a server dependency and a
 * second content type to accept a PDF it would then refuse -- after the
 * upload rather than before. The `accept` list says the same limit in the
 * form itself: a PDF has to be converted to text first.
 *
 * The identifier is shown and editable rather than generated silently. It is
 * the citation key the corpus keys on, and it cannot be changed later without
 * orphaning every citation pointing at it -- not a detail to hide behind a
 * slug nobody saw.
 */
export const DocumentUpload = ({
  projectId,
  onClose,
}: {
  projectId: ProjectId
  onClose: () => void
}) => {
  const create = useCreateDocument(projectId)

  const [title, setTitle] = useState('')
  const [sourceId, setSourceId] = useState('')
  const [uri, setUri] = useState('')
  const [note, setNote] = useState('')
  const [publishedAt, setPublishedAt] = useState('')
  const [text, setText] = useState('')

  // Untouched until the reader types in it by hand -- picking a file then
  // fills it, but only while it is still untouched, so someone who typed a
  // title first does not lose it to the next file they pick.
  const titleTouched = useRef(false)
  // The identifier defaults to a slug of the title as the title changes, but
  // stops following it the moment the reader edits the identifier directly --
  // otherwise a deliberate edit would be clobbered by the next keystroke in
  // the title field.
  const sourceIdTouched = useRef(false)

  const titleId = useId()
  const sourceIdId = useId()
  const uriId = useId()
  const noteId = useId()
  const publishedAtId = useId()
  const textId = useId()
  const fileId = useId()

  const handleTitleChange = (value: string) => {
    titleTouched.current = true
    setTitle(value)
    if (!sourceIdTouched.current) {
      setSourceId(slugify(value))
    }
  }

  const handleFile = async (file: File) => {
    const contents = await file.text()
    setText(contents)
    if (!titleTouched.current) {
      // Strip the extension rather than the whole filename: `a-paper.md` ->
      // `a-paper`. Everything after the last dot, so a name with none is left
      // alone instead of losing a trailing character.
      const stem = file.name.replace(/\.[^./\\]+$/, '')
      setTitle(stem)
      if (!sourceIdTouched.current) {
        setSourceId(slugify(stem))
      }
    }
  }

  const handleSubmit = () => {
    const trimmedId = sourceId.trim()
    if (!trimmedId) {
      // The id is the citation key and the corpus keys on it -- refused here
      // rather than spending a round-trip to be told the same thing.
      notify('Identifier is required', 'bad')
      return
    }

    const draft: DocumentDraft = { sourceId: trimmedId, text }
    if (uri.trim()) draft.uri = uri.trim()
    if (title.trim()) draft.title = title.trim()
    if (note.trim()) draft.note = note.trim()
    if (publishedAt.trim()) draft.publishedAt = publishedAt.trim()

    create.mutate(draft, {
      onSuccess: () => {
        notify('Document added')
        onClose()
      },
      onError: (error) => notify(errorMessage(error), 'bad'),
    })
  }

  return (
    <Drawer heading="Add document" label="Add document" onClose={onClose}>
      <div className="flex flex-col gap-3">
        <label htmlFor={fileId} className="flex flex-col gap-1 text-sm">
          Text file
          {/* .txt/.md/.markdown/text/* only: the corpus stores text and this
              build decodes no binary document format, so a PDF has to be
              converted to text before it is picked here rather than being
              accepted and then refused after the round-trip. */}
          <input
            id={fileId}
            type="file"
            accept=".txt,.md,.markdown,text/*"
            className="input w-full"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void handleFile(file)
            }}
          />
        </label>

        <label htmlFor={titleId} className="flex flex-col gap-1 text-sm">
          Title
          <input
            id={titleId}
            type="text"
            className="input w-full"
            value={title}
            onChange={(event) => handleTitleChange(event.target.value)}
          />
        </label>

        <label htmlFor={sourceIdId} className="flex flex-col gap-1 text-sm">
          Identifier
          <input
            id={sourceIdId}
            type="text"
            className="input w-full"
            value={sourceId}
            onChange={(event) => {
              sourceIdTouched.current = true
              setSourceId(event.target.value)
            }}
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
            value={text}
            onChange={(event) => setText(event.target.value)}
          />
        </label>

        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button tone="accent" onClick={handleSubmit} disabled={create.isPending}>
            Add document
          </Button>
        </div>
      </div>
    </Drawer>
  )
}

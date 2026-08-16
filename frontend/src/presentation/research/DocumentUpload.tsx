import { useId, useRef, useState } from 'react'

import { errorMessage } from '@application/ports/errors.ts'
import { notify } from '@application/notifications/toast-store.ts'
import { useCreateDocument, useUploadMedia } from '@application/research/use-document-writes.ts'
import type { DocumentDraft, MediaDraft } from '@application/ports/repositories.ts'
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

/** The "Add document" dialog: a text file read client-side, a form filled by
 *  hand, or a media file posted as multipart.
 *
 * Two pickers rather than one that decides what a file is. The two paths do
 * genuinely different things -- one decodes to a string and stores a document,
 * the other streams bytes to a blob store -- and getting it wrong is silent
 * either way round: `file.text()` on a video stores megabytes of mojibake as
 * prose, and a `.md` sent as media becomes something the graph will never
 * extract. Neither failure raises, so the choice is the reader's rather than a
 * guess made from a mimetype the operating system may not even have.
 *
 * The text file is read with `await file.text()` rather than posted as
 * multipart. The corpus stores text and nothing in this tree decodes a binary
 * *document* format, so a multipart text endpoint would have spent a server
 * dependency and a second content type to accept a PDF it would then refuse --
 * after the upload rather than before. The `accept` list says the same limit
 * in the form itself: a PDF has to be converted to text first.
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
  const upload = useUploadMedia(projectId)

  const [media, setMedia] = useState<File | null>(null)
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
  const mediaId = useId()

  const handleTitleChange = (value: string) => {
    titleTouched.current = true
    setTitle(value)
    if (!sourceIdTouched.current) {
      setSourceId(slugify(value))
    }
  }

  /** Strip the extension rather than the whole filename: `a-paper.md` ->
   *  `a-paper`. Everything after the last dot, so a name with none is left
   *  alone instead of losing a trailing character. */
  const nameFrom = (file: File) => {
    if (titleTouched.current) return
    const stem = file.name.replace(/\.[^./\\]+$/, '')
    setTitle(stem)
    if (!sourceIdTouched.current) {
      setSourceId(slugify(stem))
    }
  }

  const handleFile = async (file: File) => {
    const contents = await file.text()
    setMedia(null)
    setText(contents)
    nameFrom(file)
  }

  const handleMedia = (file: File | null) => {
    // Null is a real event, not a defensive branch: the native picker's own
    // "clear" fires a change with an empty `files`, and a handler that ignored
    // it left `media` set while the control showed nothing -- the Text field
    // stayed hidden and the form still posted multipart with a file the reader
    // believed they had removed.
    if (!file) {
      setMedia(null)
      return
    }
    // The text is cleared rather than left behind a hidden field: it is not
    // sent on this path, and a leftover value would be waiting to be stored
    // under the same id the moment somebody cleared the media picker.
    setText('')
    setMedia(file)
    nameFrom(file)
  }

  const handleSubmit = () => {
    const trimmedId = sourceId.trim()
    if (!trimmedId) {
      // The id is the citation key and the corpus keys on it -- refused here
      // rather than spending a round-trip to be told the same thing.
      notify('Identifier is required', 'bad')
      return
    }

    if (media) {
      const draft: MediaDraft = { sourceId: trimmedId, file: media }
      if (uri.trim()) draft.uri = uri.trim()
      if (title.trim()) draft.title = title.trim()
      if (note.trim()) draft.note = note.trim()
      if (publishedAt.trim()) draft.publishedAt = publishedAt.trim()

      upload.mutate(draft, {
        onSuccess: () => {
          notify('Media added')
          onClose()
        },
        onError: (error) => notify(errorMessage(error), 'bad'),
      })
      return
    }

    if (!text.trim()) {
      // The server has a length cap and no minimum, and `decide` has no
      // opinion, so an empty text area is stored, indexed and listed at
      // `char_count: 0` -- a document that exists and says nothing. Refused
      // the same way as the identifier because it is the same kind of
      // mistake: a form submitted before it was filled in.
      notify('Text is required', 'bad')
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

        <label htmlFor={mediaId} className="flex flex-col gap-1 text-sm">
          Media file
          {/* No `accept` list at all, unlike the text picker above. The server
              stores whatever it is handed and sniffs the type when the browser
              will not name one, so a list here could only refuse something the
              corpus would have taken -- `.mkv` and `.webm` are exactly the
              files a bare machine reports as `application/octet-stream`. */}
          <input
            id={mediaId}
            type="file"
            className="input w-full"
            onChange={(event) => handleMedia(event.target.files?.[0] ?? null)}
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

        {/* Gone once a media file is picked, rather than emptied and left on
            screen: this is the text path's required field, and asking for
            something that is about to be ignored is how a form teaches a
            reader to distrust it. */}
        {media ? null : (
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
        )}

        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button
            tone="accent"
            onClick={handleSubmit}
            disabled={create.isPending || upload.isPending}
          >
            Add document
          </Button>
        </div>
      </div>
    </Drawer>
  )
}

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'

import { queryKeys } from '@application/queries/keys.ts'
import { useContainer } from '@app/container-context.tsx'
import {
  documentLabel,
  formatBytes,
  type MediaSummary,
  type SourceSummary,
} from '@domain/research/document.ts'
import type { ProjectId, SourceId } from '@domain/shared/identifier.ts'

import { ErrorBox, Loading } from '../common/primitives.tsx'

/** Whichever way this source can be shown: its text fetched, or its bytes
 *  handed to the browser.
 *
 * The kind comes in as a prop rather than being discovered by fetching,
 * because the fetch is the thing being decided: `/sources/{id}` answers 404
 * for a media source, so a reader that read first and switched afterwards
 * would show an error where a video belongs. Splitting the two into separate
 * components is what makes that structural rather than a promise -- `TextRead`
 * holds the query, and it is not mounted for media, so there is no code path
 * on which the request happens.
 *
 * `source` may be null: the list is the only thing that knows the kind, and it
 * has no row for an id the corpus does not hold. Falling through to the text
 * read there is deliberate -- its 404 is the honest report of "no such source"
 * and the alternative is a pane that loads forever.
 */
export const DocumentReader = ({
  projectId,
  sourceId,
  source,
}: {
  projectId: ProjectId
  sourceId: SourceId
  source: SourceSummary | null
}) => {
  if (source?.kind === 'media') {
    return <MediaView projectId={projectId} source={source} />
  }
  return <TextRead projectId={projectId} sourceId={sourceId} />
}

/** One document's text, read fresh rather than reused from the list row --
 *  `SourceSummary` carries no `text`, on purpose, so this is the only place in
 *  the pane that ever asks the server for it. */
const TextRead = ({ projectId, sourceId }: { projectId: ProjectId; sourceId: SourceId }) => {
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

/** A media source, played by the browser.
 *
 * Nothing is fetched here: the element takes a URL and the browser does the
 * rest, which is the only way seeking works -- a player asks for byte ranges
 * as the reader scrubs, and a blob this component had downloaded whole would
 * have made a two-hour recording unwatchable to answer one question about its
 * first minute. The content route answers 206 for exactly that reason.
 *
 * Browser-native `controls` and no thumbnail: a thumbnail needs a frame, a
 * frame needs `ffmpeg`, and that is a different sub-project. Deliberately not
 * extracted into a shared player either -- rendering media inside markdown and
 * inside Ask answers needs a reference syntax that does not exist yet, and a
 * general component built now would be designing that syntax by accident.
 */
const MediaView = ({ projectId, source }: { projectId: ProjectId; source: MediaSummary }) => {
  const { documents } = useContainer()
  const url = documents.contentUrl(projectId, source.sourceId)
  const label = documentLabel(source)

  return (
    <article className="flex flex-col gap-[8px] px-4 pt-[12px] pb-5">
      {source.droppedReason ? (
        <p className="m-0 text-xs text-k-failure">Dropped: {source.droppedReason}</p>
      ) : null}
      <Player url={url} label={label} mediaType={source.mediaType} />
      {/* The digest beside the bytes rather than hidden behind an edit form:
          it is what proves the recording being watched is the one on record,
          and this is the one place a reader is looking at both. */}
      <p className="m-0 font-mono text-xs break-all text-fg-dim">
        {source.mediaType} · {formatBytes(source.byteCount)} · {source.sha256}
      </p>
    </article>
  )
}

const Player = ({ url, label, mediaType }: { url: string; label: string; mediaType: string }) => {
  // The one place a dangling reference is met by a person. The port
  // distinguishes "no such source" from "record here, bytes gone" and the
  // content route answers 410 for the second, but a `<video>` handed a 410
  // renders an inert black box and an `<img>` a broken-image glyph -- neither
  // says anything, and both look identical to a network hiccup or a codec
  // this browser will not play. `onError` is the only signal the elements
  // give, so it is what this hangs on.
  //
  // It deliberately does not claim *which* failure it was. The element
  // reports an error with no status code, and re-fetching the URL to read one
  // would be a second request whose answer could differ from the first -- so
  // the message names the likely cause and the digest line below it stays
  // rendered, which is what an operator needs to go and ask the route
  // directly. Naming 410 outright would be a guess wearing a status code.
  //
  // No `onRetry`: retrying re-runs the same request, and the failure this is
  // most often reporting (the blob is gone) does not heal by being asked
  // twice. A reload is one keystroke away for the case that does.
  const [failed, setFailed] = useState(false)
  if (failed) {
    return (
      <ErrorBox
        heading="These bytes could not be loaded. "
        message={`The corpus still holds this source's record; its ${mediaType} bytes did not arrive. They may no longer be stored.`}
      />
    )
  }

  // The stored mimetype's first segment and nothing cleverer. The server
  // already sniffed the bytes once at upload (`_sniff_media_type`) and nothing
  // re-sniffs a stored blob, so guessing again here could only disagree with
  // the `Content-Type` the content route actually answers with.
  if (mediaType.startsWith('video/')) {
    return (
      // `jsx-a11y/media-has-caption` off, and this is the cost being accepted
      // rather than a rule being dodged: a caption track needs a transcript,
      // and nothing in this build produces one -- transcription is the same
      // sub-project as thumbnails, both of which need to decode the media.
      // An empty `<track>` would satisfy the rule and help nobody, which is
      // worse than the honest gap. Revisit when transcription lands.
      // eslint-disable-next-line jsx-a11y/media-has-caption
      <video
        data-testid="media-player"
        controls
        src={url}
        onError={() => setFailed(true)}
        className="bg-black max-h-[60vh] w-full rounded-md"
      />
    )
  }
  if (mediaType.startsWith('audio/')) {
    return (
      // Same trade as the video above, for the same missing transcript.
      // eslint-disable-next-line jsx-a11y/media-has-caption
      <audio
        data-testid="media-player"
        controls
        src={url}
        onError={() => setFailed(true)}
        className="w-full"
      />
    )
  }
  if (mediaType.startsWith('image/')) {
    return (
      <img
        src={url}
        alt={label}
        onError={() => setFailed(true)}
        className="max-h-[60vh] max-w-full rounded-md object-contain"
      />
    )
  }
  // A `<video>` pointed at a zip renders an empty black box and reports
  // nothing, so the pane would look broken rather than honest. Saying what is
  // stored and offering the bytes is the whole of what this build can do for a
  // type it cannot play.
  return (
    <p className="m-0 text-sm">
      This build cannot play {mediaType} in the browser.{' '}
      <a href={url} className="underline">
        Open the stored bytes
      </a>
      .
    </p>
  )
}

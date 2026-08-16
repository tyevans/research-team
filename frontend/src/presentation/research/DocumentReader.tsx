import { useEffect, useRef, useState } from 'react'
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

import { Markdown } from '../common/content.tsx'
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
  seekSeconds = null,
}: {
  projectId: ProjectId
  sourceId: SourceId
  source: SourceSummary | null
  /** The moment a citation pointed at, carried in from the `?t=` query on the
   *  `doc` route -- see `references.ts`'s `expandReferences` and
   *  `GraphDetail`'s citation links, which are the two things that produce
   *  it. `null` for the ordinary "just opened the document" case, and for
   *  every text source: there is nothing to seek in prose. */
  seekSeconds?: number | null
}) => {
  if (source?.kind === 'media') {
    return <MediaView projectId={projectId} source={source} seekSeconds={seekSeconds} />
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
      {/* Rendered, not shown raw. The corpus stores markdown -- pages arrive
          converted, and the extraction prompt is written against that -- so a
          `whitespace-pre-wrap` paragraph was showing `##`, `[text](url)` and
          table pipes as literal characters on the one screen whose whole job
          is reading the document.

          **This changes what a document with no markdown in it looks like.**
          `whitespace-pre-wrap` honoured every newline; `marked` runs with
          `breaks: false`, so a single newline inside a paragraph now folds
          into a space and only a blank line starts a new one. For markdown
          that is correct and is the point. For a plain-text source whose line
          breaks were meaningful -- a poem, a log -- it is a regression, and
          the fix if one turns up is a per-document choice about which it is,
          not `breaks: true`, which would break every real markdown document
          instead.

          `md-bare` because the `<article>` above already owns the padding and
          the measure; see `markdown.css`. The measure moves here from the old
          paragraph, unchanged. */}
      <Markdown className="md-bare max-w-[68ch] text-sm leading-[1.65]" source={document.text} />
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
const MediaView = ({
  projectId,
  source,
  seekSeconds,
}: {
  projectId: ProjectId
  source: MediaSummary
  seekSeconds: number | null
}) => {
  const { documents } = useContainer()
  const url = documents.contentUrl(projectId, source.sourceId)
  const label = documentLabel(source)

  return (
    <article className="flex flex-col gap-[8px] px-4 pt-[12px] pb-5">
      {source.droppedReason ? (
        <p className="m-0 text-xs text-k-failure">Dropped: {source.droppedReason}</p>
      ) : null}
      <Player url={url} label={label} mediaType={source.mediaType} seekSeconds={seekSeconds} />
      {/* The digest beside the bytes rather than hidden behind an edit form:
          it is what proves the recording being watched is the one on record,
          and this is the one place a reader is looking at both. */}
      <p className="m-0 font-mono text-xs break-all text-fg-dim">
        {source.mediaType} · {formatBytes(source.byteCount)} · {source.sha256}
      </p>
    </article>
  )
}

const Player = ({
  url,
  label,
  mediaType,
  seekSeconds,
}: {
  url: string
  label: string
  mediaType: string
  seekSeconds: number | null
}) => {
  // `currentTime` rather than `#t=<n>` on the `src`: this element's `src` is
  // the content route, and a media fragment appended there would ask the
  // *server* to satisfy the range with `Range`/`Accept-Ranges`, which the
  // route already supports but only by re-requesting the whole element from
  // scratch. Setting `currentTime` on the already-mounted element seeks the
  // one request that is already in flight instead.
  //
  // Effect runs once per mount (empty deps), not once per `seekSeconds`
  // change: this reader is unmounted and remounted when the open document
  // changes (its `key` is the source id, in the callers), so "seek on mount"
  // is the whole of what "seek to the cited moment" means here. Re-seeking
  // on every prop change would fight a reader who has since scrubbed
  // elsewhere in the same clip.
  // `HTMLMediaElement` -- the base both `<video>` and `<audio>` share -- kept
  // in a plain mutable ref rather than one from `useRef<HTMLVideoElement>`:
  // that type is specific to `<video>`'s own `ref` prop and rejects an
  // `<audio>` element structurally, even though both share `currentTime`.
  const el = useRef<HTMLMediaElement | null>(null)
  const setRef = (node: HTMLMediaElement | null) => {
    el.current = node
  }
  useEffect(() => {
    if (seekSeconds === null) return
    if (el.current) el.current.currentTime = seekSeconds
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
        ref={setRef}
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
        ref={setRef}
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

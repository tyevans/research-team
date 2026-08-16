import type { SourceId } from '../shared/identifier.ts'

/** What every source carries whatever its bytes are: who it is, where it came
 *  from, and whether the corpus still counts it.
 *
 * Split out of the two summaries below rather than repeated in both, so a
 * field added to the wire lands in one place -- and so the helpers that read
 * only provenance (`isDropped`, `documentLabel`) can say in their signature
 * that they do not care which kind they were handed. */
interface SourceProvenance {
  readonly sourceId: SourceId
  readonly sha256: string
  readonly uri: string | null
  readonly title: string | null
  readonly publishedAt: string | null
  readonly note: string | null
  /** Provenance for by-reference content the corpus did not create -- when the
   *  console (or an agent) fetched the bytes at `uri`, not when the record was
   *  written. `null` for a document with no `uri`, or one stored before this
   *  field existed. Carried through unconditionally by `revise` and `restore`,
   *  so a form built over this type can show whether an edit disturbed it. */
  readonly fetchedAt: string | null
  /** `null` for a live source, set for one the corpus kept only as an audit
   *  trail.
   *
   * The corpus never actually deletes a source; dropping it just records why.
   * A browser that hid dropped rows would misreport what the project holds, so
   * this carries the reason rather than a boolean -- there being a reason is
   * what "dropped" means here, and the boolean would be redundant with it. */
  readonly droppedReason: string | null
  /** Whether this source's text has been folded into the project's graph.
   *
   * Not a property of the source record and deliberately cannot be: extraction
   * lives on another aggregate's stream, and the corpus projection joins the
   * two. See `source_view`. False on every row of a database that predates the
   * column until that projection is rebuilt, which is why the wire schema
   * defaults it rather than requiring it -- and false unconditionally on
   * media, which nothing extracts yet. */
  readonly extracted: boolean
}

/** A source whose bytes are text: a paper, a page, a note. */
export interface TextSummary extends SourceProvenance {
  readonly kind: 'text'
  readonly charCount: number
  /** The media source this was perceived from, `null` for a document somebody
   *  fetched or typed.
   *
   * On the text arm rather than on `SourceProvenance`, mirroring the server:
   * a transcript *is* text for every purpose a reader has, and media is the
   * thing that gets derived *from*, never the derived thing. */
  readonly derivedFrom: string | null
  /** What the perception could not do, in words. Empty for a fetched document
   *  and for a complete perception alike -- `derivedFrom` is what separates
   *  those, so nothing has to read an empty list as "unknown". */
  readonly degradations: readonly string[]
}

/** A source whose bytes are not text: a recording, a scan, a slide deck.
 *
 * `mediaType` is the stored mimetype rather than one sniffed at render time --
 * the server decided it once, at upload, and nothing re-sniffs a stored blob,
 * so a viewer that guessed again could disagree with the `Content-Type` the
 * content route actually answers with. */
export interface MediaSummary extends SourceProvenance {
  readonly kind: 'media'
  readonly mediaType: string
  readonly byteCount: number
}

/** One row of a project's document browser, whichever shape its bytes are.
 *
 * Discriminated on `kind` rather than left as an optional-fields widening: a
 * `charCount` that is `null` for media invites a component to render "0
 * characters", which reads as an empty document rather than as a video -- a
 * plausible-looking wrong answer, which is worse than a crash. The union makes
 * the compiler ask which one is being rendered, and it mirrors the wire, where
 * `char_count` and `media_type`/`byte_count` are *absent* on the other kind
 * rather than null. See `_record_view`. */
export type SourceSummary = TextSummary | MediaSummary

/** One source's text, with the offsets that make a quote from it checkable.
 *
 * Extends `TextSummary` and not `SourceSummary`, which is the type-level
 * statement of what the route does: `/sources/{id}` answers 404 for a media
 * source, because its bytes live in the blob store rather than the event log.
 * A `DocumentText` built over the union would let a caller believe reading
 * text out of a video is a thing that can succeed.
 *
 * `start`/`end` describe what the server actually returned, not what was
 * asked for -- a range past the end of the document is clamped rather than
 * refused, so a reader paging through a document reads the real bound off
 * the response instead of trusting its own request. */
export interface DocumentText extends TextSummary {
  readonly text: string
  readonly start: number
  readonly end: number
}

export const isDropped = (source: SourceSummary): boolean => source.droppedReason !== null

/** A source's own label: its title if it has one, its source id otherwise.
 *  Both the list and the reader need this, and deriving it twice is how they
 *  would end up disagreeing about what a titleless source is called. Takes
 *  either kind, for the same reason -- a media row is titleless exactly as
 *  often as a text one. */
export const documentLabel = (source: SourceSummary): string => source.title ?? source.sourceId

/** Which medium each derived text source came from, keyed by the medium.
 *
 * The join has to happen on this side because the wire carries the edge only
 * one way: `derived_from` is on the text arm, mirroring the server, where
 * media is the thing that gets derived *from* and never the derived thing.
 * A media row therefore cannot say whether anything has been perceived out of
 * it, and the listing is the only place both ends are visible at once.
 *
 * Computed over the *whole* corpus rather than the filtered view, for the same
 * reason `extractableCount` is: a filter matching the recording and not its
 * transcript would otherwise make a transcribed medium offer to be transcribed
 * again, which is real duplicated work rather than a cosmetic error.
 *
 * **A dropped transcript still counts its medium as perceived**, and that is
 * deliberate rather than an oversight of the `kind === 'text'` test below: this
 * is the same rule `MediaPerceiver.unperceived` applies on the server, whose
 * comment says it in as many words -- a dropped transcript still counts its
 * parent as perceived. So a medium whose transcript was dropped shows
 * "Transcript" here and would be excluded from batch perception there, and the
 * two ends agree. *Would be*: `unperceived` has no caller yet -- there is no
 * batch-perceive route in this slice -- so the agreement is between this
 * function and a rule the server has written down rather than one it currently
 * runs. Named because they agree by coincidence of shape and
 * nothing else says so: a future reader "fixing" this to skip dropped rows
 * would make the console offer to re-transcribe exactly the media the batch
 * path refuses to touch, and neither side would report a conflict.
 *
 * Last one wins on a duplicate, which the server should never produce -- the
 * derived id is the medium's plus `#perceived`, so there is one per medium.
 * Nothing here refuses a second: a `Map` picking one arbitrarily is a strictly
 * better answer than a throw on a listing the reader wanted to see. */
export const derivedSources = (rows: readonly SourceSummary[]): ReadonlyMap<string, SourceId> => {
  const derived = new Map<string, SourceId>()
  for (const row of rows) {
    if (row.kind === 'text' && row.derivedFrom !== null) derived.set(row.derivedFrom, row.sourceId)
  }
  return derived
}

/** A byte count a person can read, in decimal units.
 *
 * Decimal (1000) rather than binary (1024), matching how the operating systems
 * a reader is likely to be comparing against report the same file -- a 12.5 MB
 * recording that this called "11.9 MiB" would look like a different file.
 *
 * Always one decimal place above a kilobyte, rather than switching to whole
 * numbers past 10: the alternative reads better in isolation and worse in a
 * list, where "9.7 MB" above "13 MB" makes the column ragged for no gain. */
export const formatBytes = (bytes: number): string => {
  if (bytes < 1000) return `${String(bytes)} B`
  const units = ['kB', 'MB', 'GB', 'TB']
  let value = bytes / 1000
  let unit = 0
  while (value >= 1000 && unit < units.length - 1) {
    value /= 1000
    unit += 1
  }
  return `${value.toFixed(1)} ${units[unit] ?? 'TB'}`
}

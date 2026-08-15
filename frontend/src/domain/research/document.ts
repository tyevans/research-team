import type { SourceId } from '../shared/identifier.ts'

/** One row of a project's document browser: what a source is, not what it
 *  says. Mirrors `source_view` on the wire -- `char_count`, `sha256` and the
 *  rest -- except `droppedReason`, which is `null` for a live document and
 *  set for one the corpus kept only as an audit trail.
 *
 * The corpus never actually deletes a source; dropping it just records why.
 * A browser that hid dropped rows would misreport what the project holds, so
 * this type carries the reason rather than a boolean -- there being a reason
 * is what "dropped" means here, and the boolean would be redundant with it. */
export interface DocumentSummary {
  readonly sourceId: SourceId
  readonly charCount: number
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
  readonly droppedReason: string | null
  /** Whether this document's text has been folded into the project's graph.
   *
   * Not a property of the source record and deliberately cannot be: extraction
   * lives on another aggregate's stream, and the corpus projection joins the
   * two. See `source_view`. False on every row of a database that predates the
   * column until that projection is rebuilt, which is why the wire schema
   * defaults it rather than requiring it. */
  readonly extracted: boolean
}

/** One source's text, with the offsets that make a quote from it checkable.
 *
 * `start`/`end` describe what the server actually returned, not what was
 * asked for -- a range past the end of the document is clamped rather than
 * refused, so a reader paging through a document reads the real bound off
 * the response instead of trusting its own request. */
export interface DocumentText extends DocumentSummary {
  readonly text: string
  readonly start: number
  readonly end: number
}

export const isDropped = (document: DocumentSummary): boolean => document.droppedReason !== null

/** A document's own label: its title if it has one, its source id otherwise.
 *  Both the list and the reader need this, and deriving it twice is how they
 *  would end up disagreeing about what a titleless source is called. */
export const documentLabel = (document: DocumentSummary): string =>
  document.title ?? document.sourceId

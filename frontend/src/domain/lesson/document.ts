import type { ComponentId } from '../shared/identifier.ts'

/** A markdown artifact parsed into blocks by the server.
 *
 * The parse happens server-side and that is the whole point: which fields come
 * back is the server's decision, so the answer key can be withheld from a
 * learner's projection rather than merely hidden by a client that was sent it.
 * Nothing in this layer can grade, and nothing here should be given the chance
 * to try.
 */
export interface LessonDocument {
  readonly blocks: readonly DocumentBlock[]
}

export type DocumentBlock = MarkdownBlock | ComponentBlock

export interface MarkdownBlock {
  readonly kind: 'markdown'
  readonly text: string
}

/** An interactive widget, in one of three conditions.
 *
 * `unknown` — a fenced block naming a type this build does not implement.
 * `errors` — a block of a known type whose fields did not parse.
 * Otherwise it is renderable, and `data` is the widget's own shape.
 *
 * All three are carried on one type rather than split into three, because a
 * renderer has to handle all three anyway and the degradations are *per block*:
 * neither takes the rest of the document down with it.
 */
export interface ComponentBlock {
  readonly kind: 'component'
  readonly id: ComponentId
  readonly type: string
  readonly data: Readonly<Record<string, unknown>>
  readonly raw: string
  readonly lang: string | null
  readonly unknown: boolean
  readonly errors: readonly ComponentError[]
  /** Field names the learner projection stripped. Non-empty means an answer key
   *  exists and is being graded on the server rather than in this page. */
  readonly withheld: readonly string[]
  /** Whether this component fetches its data from the project rather than
   *  carrying it, as the server classified it.
   *
   * **The renderer does not read this**, and that is deliberate rather than an
   * omission. `LessonDocument` spreads `projectId` into every renderer
   * unconditionally: a widget that does not resolve simply ignores the prop,
   * which costs nothing, whereas gating the spread on this flag would make a
   * resolved widget's ability to fetch depend on the server having classified
   * it correctly. A mis-flagged component would then render `unavailable`
   * forever with nothing raising -- the same silent-empty failure CLAUDE.md
   * describes for a missing projection. Unconditional threading has one
   * behaviour whether the flag is right or wrong.
   *
   * **Nothing in `frontend/src` reads it today.** All five resolved widgets
   * shipped without it, for the reason above -- they take `projectId`
   * unconditionally and never ask whether they were classified as resolved --
   * so an earlier version of this docstring promising "Tasks 3-7 are its
   * first readers" turned out to be wrong about its own feature.
   *
   * Kept rather than deleted, and the case is narrow: it is the server's
   * classification, already emitted, already validated by the block schema
   * and already mapped, and it is the only thing on the client that can tell
   * a reference component from a content one without a hardcoded type list.
   * A surface that needs that distinction -- a print or export view that
   * cannot fetch, say -- gets it for free. The cost of being wrong about that
   * guess is one boolean on the wire. Grep before writing the first reader:
   * if this paragraph is still the only mention, it is dead and should go. */
  readonly resolved: boolean
}

export interface ComponentError {
  readonly path: string | null
  readonly message: string
}

export const isComponentBlock = (block: DocumentBlock): block is ComponentBlock =>
  block.kind === 'component'

export const componentBlocks = (document: LessonDocument | null): readonly ComponentBlock[] =>
  document?.blocks.filter(isComponentBlock) ?? []

/** Whether a document is worth rendering through the component pipeline at all.
 *
 * A markdown file with no widgets renders through the plain path, which keeps
 * the common case free of a second render tree — and keeps the author/learner
 * toggle off a header where it would do nothing. */
export const hasComponents = (document: LessonDocument | null): boolean =>
  componentBlocks(document).length > 0

/** Which projection of a document was asked for.
 *
 * `author` sees the answer key; `learner` asks the server to withhold it. The
 * console defaults to `author` because its reader is the person building the
 * course — the learner view is a preview of somebody else's screen. */
export type ComponentAudience = 'author' | 'learner'

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

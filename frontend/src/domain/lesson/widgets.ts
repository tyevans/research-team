import type { ComponentBlock } from './document.ts'
import type { EntityReference } from './resolved.ts'
import { readEntityReference } from './resolved.ts'

/** The four widget shapes this build renders, read out of a block's `data`.
 *
 * The server hands back `data` as an open record because the set of widget
 * types is open. These readers narrow it at the one boundary where a renderer
 * needs it, defaulting rather than throwing: a deck with no `cards` key is an
 * empty deck, which renders as "this deck has no cards" — a far better failure
 * for a *viewer* than a blank page.
 */

export interface Flashcard {
  readonly front: string
  readonly back: string
}

export interface FlashcardDeck {
  readonly title: string | null
  readonly cards: readonly Flashcard[]
}

export const readFlashcards = (block: ComponentBlock): FlashcardDeck => ({
  title: str(block.data['title']),
  cards: list(block.data['cards']).map((card) => ({
    front: str(rec(card)['front']) ?? '',
    back: str(rec(card)['back']) ?? '',
  })),
})

export interface McqOption {
  readonly text: string
}

export interface Mcq {
  readonly prompt: string
  readonly options: readonly McqOption[]
  /** Multiple-answer changes the control from radio to checkbox *and* changes
   *  what a submission means, so it is read once here rather than at both. */
  readonly multiple: boolean
}

export const readMcq = (block: ComponentBlock): Mcq => ({
  prompt: str(block.data['prompt']) ?? '',
  options: list(block.data['options']).map((option) => ({
    text: str(rec(option)['text']) ?? '',
  })),
  multiple: block.data['multiple'] === true,
})

/** One run of a cloze passage: either literal text, or a numbered blank. */
export type ClozeSegment =
  | { readonly kind: 'text'; readonly text: string }
  | { readonly kind: 'blank'; readonly blank: number; readonly hint: string | null }

export interface Cloze {
  readonly segments: readonly ClozeSegment[]
  /** One-at-a-time is what makes the mode mean anything: the learner reads
   *  forward instead of scanning the passage for the easy gaps first. */
  readonly oneAtATime: boolean
}

export const readCloze = (block: ComponentBlock): Cloze => ({
  oneAtATime: block.data['mode'] !== 'all-at-once',
  segments: list(block.data['segments']).map((raw): ClozeSegment => {
    const segment = rec(raw)
    const blank = segment['blank']
    if (typeof blank === 'number') {
      return { kind: 'blank', blank, hint: str(segment['hint']) }
    }
    return { kind: 'text', text: str(segment['text']) ?? '' }
  }),
})

export const clozeBlanks = (cloze: Cloze): readonly Extract<ClozeSegment, { kind: 'blank' }>[] =>
  cloze.segments.filter(
    (segment): segment is Extract<ClozeSegment, { kind: 'blank' }> => segment.kind === 'blank',
  )

/** The blank a one-at-a-time passage will accept input into next: the first
 *  that has nothing typed in it. Every blank is open once they are all filled,
 *  so a learner can go back and revise before submitting. */
export const activeBlank = (cloze: Cloze, typed: Readonly<Record<number, string>>): number => {
  for (const blank of clozeBlanks(cloze)) {
    if (!String(typed[blank.blank] ?? '').trim()) return blank.blank
  }
  return Number.POSITIVE_INFINITY
}

export interface ChecklistItem {
  readonly text: string
  readonly note: string | null
  readonly required: boolean
}

export interface Checklist {
  readonly title: string | null
  readonly items: readonly ChecklistItem[]
  /** Persisted checklists post every tick to the session's progress log. */
  readonly persist: boolean
}

export const readChecklist = (block: ComponentBlock): Checklist => ({
  title: str(block.data['title']),
  persist: block.data['persist'] === true,
  items: list(block.data['items']).map((raw) => {
    const item = rec(raw)
    return {
      text: str(item['text']) ?? '',
      note: str(item['note']),
      required: item['required'] === true,
    }
  }),
})

/** A `definition` widget's reference. A thin alias over the shared reader
 *  rather than its own parse: every resolved widget reads the same two
 *  fields, and five copies of that would be five places to forget
 *  `entity_id`. Re-exported here so a renderer imports its reader from the
 *  module every other renderer imports one from. */
export { readEntityReference as readDefinitionRef } from './resolved.ts'

/** One passage an `evidence` claim rests on. Offsets are nullable rather
 *  than defaulted to 0: absent means "from the start" / "to the end", and
 *  `{start: 0, end: 0}` would be a request for nothing. */
export interface EvidenceSource {
  readonly source: string
  readonly start: number | null
  readonly end: number | null
}

export interface Evidence {
  readonly claim: string
  readonly sources: readonly EvidenceSource[]
}

export const readEvidence = (block: ComponentBlock): Evidence => ({
  claim: str(block.data['claim']) ?? '',
  sources: list(block.data['sources']).map((raw) => {
    const entry = rec(raw)
    return {
      source: str(entry['source']) ?? '',
      start: num(entry['start']),
      end: num(entry['end']),
    }
  }),
})

/** A `graph` widget's reference, plus how far out to draw. */
export interface GraphRef extends EntityReference {
  readonly depth: number
}

export const readGraphRef = (block: ComponentBlock): GraphRef => ({
  ...readEntityReference(block),
  // The server defaults this too, so a body that reached here without one is
  // a body the registry did not normalise -- a hand-built test block, in
  // practice. 1 is the same default the registry writes.
  depth: num(block.data['depth']) ?? 1,
})

/** A `timeline` widget's window. Nullable rather than defaulted throughout:
 *  an omitted bound is an open end, and a default would silently narrow a
 *  request the author left wide.
 *
 * No entity or topic field, and that absence is deliberate rather than
 * pending: `GET /timeline` filters by type and range only, so an `entity`
 * here would be a field that read cleanly and did nothing. */
export interface TimelineWindow {
  readonly entityType: string | null
  readonly from: string | null
  readonly to: string | null
  readonly limit: number | null
}

export const readTimelineQuery = (block: ComponentBlock): TimelineWindow => ({
  entityType: str(block.data['entity_type']),
  from: str(block.data['from']),
  to: str(block.data['to']),
  limit: num(block.data['limit']),
})

const rec = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {}

const list = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : [])

const str = (value: unknown): string | null => (typeof value === 'string' ? value : null)

/** `Number.isFinite` and not a bare `typeof`: YAML's `.nan` and `.inf` parse
 *  to real numbers here, and either one reaches the range query as the string
 *  "NaN" -- a query param the route reads as a nonsense offset rather than as
 *  the absent one the author effectively wrote. */
const num = (value: unknown): number | null =>
  typeof value === 'number' && Number.isFinite(value) ? value : null

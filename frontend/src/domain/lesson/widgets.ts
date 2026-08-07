import type { ComponentBlock } from './document.ts'

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

const rec = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' ? (value as Record<string, unknown>) : {}

const list = (value: unknown): readonly unknown[] => (Array.isArray(value) ? value : [])

const str = (value: unknown): string | null => (typeof value === 'string' ? value : null)

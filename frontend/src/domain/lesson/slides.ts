import type { ComponentBlock, LessonDocument } from './document.ts'

/** A lesson, paced: the same parsed document read as a deck.
 *
 * **Pure, and deliberately not in `presentation/`.** Segmentation is the whole
 * of the slideshow's design -- `docs/design/lesson-slideshow.md` argues it --
 * and a rule that lives inside a React component is a rule that can only be
 * tested by rendering one. This module touches no DOM, no `window` and no
 * React, so `slides.test.ts` runs it over four real authored lesson files
 * checked in at `fixtures/` and reads the answer directly.
 *
 * **Slides are derived, never authored.** Every lesson this system has ever
 * written gains a deck the moment this ships, and there is one source of
 * truth for what a lesson says. What is given up: the deck's pacing is a
 * mechanical consequence of the prose's shape, so a lesson written as one
 * unbroken argument presents as a few dense slides. The design document has
 * the alternatives and what each would have cost.
 */

/** One slide's worth of content. Five kinds, and the kind is what the view
 *  dresses -- not a hint, a decision the segmenter already made. */
export type Slide = TitleSlide | ProseSlide | QuoteSlide | ComponentSlide

interface SlideBase {
  /** Position in the deck, from 0. This is also the deep link -- see the
   *  design document for why identity is a position rather than a slug, and
   *  what that costs when a lesson is re-authored. */
  readonly index: number
  /** The section this slide belongs to, as its heading text, or null for
   *  content that precedes every heading. */
  readonly section: string | null
  /** Whether this slide *opens* its section. A section spanning three slides
   *  prints its heading at full weight once and small twice, so a reader who
   *  joins at slide 9 still knows where they are. */
  readonly opensSection: boolean
  /** Presenter-visible text lifted out of the prose. Empty on every lesson
   *  that exists today: nothing authors `<!-- notes: -->` yet, and this is
   *  the reader half waiting for the writer half. Deliberately *not* a
   *  checkpoint -- no notes renders no notes and nothing fails, so the
   *  "assertion is half a contract" failure CLAUDE.md describes cannot
   *  happen here. */
  readonly notes: readonly string[]
}

export interface TitleSlide extends SlideBase {
  readonly kind: 'title'
  readonly title: string
  /** The prose between the H1 and the first section heading, if any. */
  readonly text: string
}

export interface ProseSlide extends SlideBase {
  readonly kind: 'prose'
  readonly text: string
}

/** A blockquote alone in its paragraph -- the cited passage these lessons are
 *  built on, and the one place the deck spends display type. Its own kind
 *  rather than a flag on `prose`, because the view renders it differently
 *  enough that a caller checking a boolean would be a `switch` in disguise. */
export interface QuoteSlide extends SlideBase {
  readonly kind: 'quote'
  readonly text: string
}

export interface ComponentSlide extends SlideBase {
  readonly kind: 'component'
  readonly block: ComponentBlock
}

export interface Deck {
  /** The document's first H1, or null. The *frontmatter* title never reaches
   *  the client -- `project()` sends it and `toLessonDocument` drops it -- so
   *  the heading is what the deck has. Three of the four fixtures repeat the
   *  frontmatter title verbatim as their H1. */
  readonly title: string | null
  readonly slides: readonly Slide[]
}

/** How many characters of prose fit on one slide before the next paragraph
 *  starts a new one.
 *
 * **A paragraph is never split**, whatever this is set to: prose cut
 * mid-sentence is worse than a dense slide, and a paragraph over budget gets a
 * slide of its own, whole.
 *
 * 900 was chosen by running the rule over the four fixtures at 600, 900 and
 * 1200 and reading the result in a browser at 1440x900. 600 separates
 * three-sentence paragraphs that belong together; 1200 overflows the measure.
 * The measured corpus is 44 paragraphs with a median of 379 characters and a
 * maximum of 725, so this packs two typical paragraphs and refuses three.
 *
 * `slides.test.ts` asserts the *properties* that hold at any budget rather
 * than a slide count, which would freeze this number and make retuning it a
 * test edit. */
export const SLIDE_BUDGET = 900

/** Headings at this level or shallower open a slide. H4 and below are content.
 *
 * Nothing in the corpus uses an H4, and promoting one would make a deck out of
 * a footnote. */
const STRUCTURAL_HEADING_DEPTH = 3

const HEADING = /^(#{1,6})\s+(.*)$/
/** A fence opener or closer, at the start of a line with up to three spaces of
 *  indent -- the same rule `components.py`'s `_scan` uses, because a `# ` inside
 *  a shell example is not a heading and a markdown block genuinely contains
 *  non-component fences. */
const FENCE = /^ {0,3}(`{3,}|~{3,})/
/** `<!-- notes: ... -->`, possibly spanning lines. Case-insensitive on the
 *  keyword only; the note's own text is preserved as written. */
const NOTES = /<!--\s*notes:\s*([\s\S]*?)-->/gi

/** What a markdown chunk breaks into before it is packed onto slides. */
interface Piece {
  readonly heading: { readonly depth: number; readonly text: string } | null
  readonly text: string
  readonly quote: boolean
}

/** The deck for a parsed document. Total: an empty document is an empty deck,
 *  a document with no headings is one section of packed prose, and a document
 *  of one component is one slide. */
export const deckOf = (document: LessonDocument | null): Deck => {
  if (document === null) return { title: null, slides: [] }

  const draft: Omit<Slide, 'index'>[] = []
  let title: string | null = null
  let section: string | null = null
  /** Prose waiting for a slide, and how long it is. Flushed by a heading, a
   *  quote, a component, a budget overrun, or the end of the document. */
  let pending: string[] = []
  let pendingLength = 0
  let pendingNotes: string[] = []
  /** Whether the *next* slide emitted is the first of its section. Tracked
   *  rather than compared against the previous slide's `section`, because two
   *  adjacent sections can share a heading text and a comparison would call
   *  the second one a continuation. */
  let opensSection = false

  const flush = () => {
    if (pending.length === 0) {
      // Notes with no prose to carry them attach to the next slide rather
      // than being dropped -- a note written above a component fence is the
      // obvious way to annotate that component.
      return
    }
    draft.push({
      kind: 'prose',
      section,
      opensSection,
      notes: pendingNotes,
      text: pending.join('\n\n'),
    } as Omit<ProseSlide, 'index'>)
    opensSection = false
    pending = []
    pendingLength = 0
    pendingNotes = []
  }

  for (const block of document.blocks) {
    if (block.kind === 'component') {
      flush()
      draft.push({
        kind: 'component',
        section,
        opensSection,
        notes: pendingNotes,
        block,
      } as Omit<ComponentSlide, 'index'>)
      opensSection = false
      pendingNotes = []
      continue
    }

    for (const piece of pieces(block.text)) {
      if (piece.heading !== null) {
        flush()
        const { depth, text } = piece.heading
        if (depth === 1 && title === null) {
          title = text
          section = text
          opensSection = false
          draft.push({
            kind: 'title',
            section: text,
            opensSection: true,
            notes: pendingNotes,
            title: text,
            text: '',
          } as Omit<TitleSlide, 'index'>)
          pendingNotes = []
          continue
        }
        section = text
        opensSection = true
        continue
      }

      const { text, notes } = liftNotes(piece.text)
      pendingNotes = [...pendingNotes, ...notes]
      if (text === '') continue

      if (piece.quote) {
        flush()
        draft.push({
          kind: 'quote',
          section,
          opensSection,
          notes: pendingNotes,
          text,
        } as Omit<QuoteSlide, 'index'>)
        opensSection = false
        pendingNotes = []
        continue
      }

      // Over budget only when something is already on the slide: a single
      // paragraph longer than the budget goes on alone rather than being cut.
      if (pending.length > 0 && pendingLength + text.length > SLIDE_BUDGET) flush()
      pending.push(text)
      pendingLength += text.length
    }
  }

  flush()

  // Notes that never met a slide -- a `<!-- notes: -->` at the very end of a
  // file. Attaching them to the last slide beats dropping them; a deck with a
  // note in the wrong place is fixable by an author, and a note that vanishes
  // silently is the failure this repository keeps writing entries about.
  const trailing = pendingNotes
  const slides = draft.map((slide, index) => ({ ...slide, index }) as Slide)
  if (trailing.length > 0 && slides.length > 0) {
    const last = slides[slides.length - 1]!
    slides[slides.length - 1] = { ...last, notes: [...last.notes, ...trailing] }
  }

  // The lead paragraph belongs *on* the title slide rather than after it: a
  // title alone followed by its own opening sentence is two slides that each
  // say half of one thing.
  const first = slides[0]
  const second = slides[1]
  if (first?.kind === 'title' && second?.kind === 'prose' && second.section === first.section) {
    return {
      title,
      slides: [
        { ...first, text: second.text, notes: [...first.notes, ...second.notes] },
        ...slides.slice(2).map((slide, offset) => ({ ...slide, index: offset + 1 })),
      ],
    }
  }

  return { title, slides }
}

/** Split a markdown chunk into headings and paragraphs, leaving fenced regions
 *  intact.
 *
 * The server has already lifted every `component:` fence out, so a fence
 * reaching here is a code block, a diagram or an example -- and its contents
 * must not be read for headings or split at a blank line. Both would be
 * silent: a shell example beginning `# install` would open a section, and a
 * code block with a blank line in it would become two slides of broken code.
 */
const pieces = (text: string): Piece[] => {
  const out: Piece[] = []
  const lines = text.split('\n')
  let buffer: string[] = []
  let fence: string | null = null

  const closeParagraph = () => {
    const joined = buffer.join('\n').trim()
    buffer = []
    if (joined === '') return
    out.push({
      heading: null,
      text: joined,
      // A blockquote *alone* in its paragraph. A paragraph that merely starts
      // with a quote and continues in prose is prose: the pull-quote treatment
      // is for the passage, not for anything that opens with one.
      quote: joined.split('\n').every((line) => line.trimStart().startsWith('>')),
    })
  }

  for (const line of lines) {
    const opener = FENCE.exec(line)
    if (fence !== null) {
      buffer.push(line)
      if (opener && line.trim().startsWith(fence)) fence = null
      continue
    }
    if (opener) {
      fence = opener[1]!.slice(0, 3)
      buffer.push(line)
      continue
    }

    const heading = HEADING.exec(line)
    if (heading && heading[1]!.length <= STRUCTURAL_HEADING_DEPTH) {
      closeParagraph()
      out.push({
        heading: { depth: heading[1]!.length, text: heading[2]!.trim() },
        text: '',
        quote: false,
      })
      continue
    }

    if (line.trim() === '') {
      closeParagraph()
      continue
    }
    buffer.push(line)
  }
  closeParagraph()
  return out
}

/** Pull `<!-- notes: … -->` out of a paragraph, returning what is left to show.
 *
 * The comment is removed rather than hidden by CSS: `Markdown` sanitises and
 * would drop it anyway, so leaving it in would mean the note is invisible in
 * both views and readable in neither. */
const liftNotes = (text: string): { text: string; notes: string[] } => {
  NOTES.lastIndex = 0
  if (!text.includes('<!--')) return { text, notes: [] }
  const notes: string[] = []
  const stripped = text.replace(NOTES, (_match, body: string) => {
    const note = body.trim()
    if (note !== '') notes.push(note)
    return ''
  })
  return { text: stripped.trim(), notes }
}

/** Where a slide index lands, given a deck. Out of range clamps rather than
 *  failing, because a stale deep link into a re-authored lesson should land
 *  somewhere in it -- `parseRoute`'s own answer for a malformed *filter*, and
 *  the opposite of its answer for a malformed facet, for the same stated
 *  reason: a bad slide number still leaves a page that answers most of what
 *  was asked. */
export const clampSlide = (deck: Deck, index: number): number => {
  if (deck.slides.length === 0) return 0
  if (!Number.isFinite(index) || index < 0) return 0
  return Math.min(Math.trunc(index), deck.slides.length - 1)
}

/** The rail's rows: every slide, with the section label printed only where a
 *  section begins.
 *
 * Derived here rather than in the rail component so the "printed once per
 * section" rule is testable without rendering, and so the overview and the
 * rail cannot disagree about where a section starts. */
export const railRows = (
  deck: Deck,
): readonly { readonly index: number; readonly label: string | null }[] =>
  deck.slides.map((slide) => ({
    index: slide.index,
    label: slide.opensSection ? slide.section : null,
  }))

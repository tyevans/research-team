import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

import { ComponentId } from '../shared/identifier.ts'
import type { ComponentBlock, DocumentBlock, LessonDocument } from './document.ts'
import { clampSlide, deckOf, railRows, SLIDE_BUDGET } from './slides.ts'

/** The four fixtures are **real authored output**, not written for this test.
 *
 * Lifted verbatim from the `FileWritten` events in `~/.research-team/sessions.db`
 * on 2026-08-29 -- three `lesson-*.md` from three different courses and one
 * `unit.md`. This matters more than it looks: CLAUDE.md's rule is that a
 * fixture written in the same hour as the rule it exercises supplies the
 * contract the rule was supposed to discover. These were written by
 * `lesson-drafter` weeks before the segmenter existed and none of them can
 * have been shaped to it.
 *
 * The parse below is a *reimplementation* of the server's `_scan`, and that is
 * the one piece of dishonesty in this file, stated rather than hidden: the real
 * blocks come from `components.py`. It is fenced-block splitting and nothing
 * more -- the fields inside a component are never read by the segmenter, which
 * only ever asks "is this block a component". `deck-widgets.test.tsx` drives
 * the real parse's shape through the real renderer.
 */
const FIXTURES = join(dirname(fileURLToPath(import.meta.url)), 'fixtures')

const readFixture = (name: string): string => readFileSync(join(FIXTURES, name), 'utf8')

const LESSONS = [
  'knowledge-graph-lesson-01.md',
  'agent-interaction-log-lesson-02.md',
  'resolution-lesson-03.md',
] as const

/** The fixtures that open with an H1 -- three of the four. The fourth does
 *  not, and that is a fact about the corpus rather than a gap in it: the
 *  design document's §2 asserted every lesson has one until this list was
 *  needed. */
const TITLED = [
  'knowledge-graph-lesson-01.md',
  'resolution-lesson-03.md',
  'knowledge-graph-unit.md',
] as const

const ALL_FIXTURES = [...LESSONS, 'knowledge-graph-unit.md'] as const

const FENCE = /^ {0,3}(`{3,}|~{3,})(.*)$/

/** Frontmatter off, `component:` fences into component blocks, everything else
 *  into markdown blocks -- the shape `project()` puts on the wire. */
const parse = (source: string): LessonDocument => {
  const body = source.replace(/^---\n[\s\S]*?\n---\n/, '')
  const blocks: DocumentBlock[] = []
  let pending: string[] = []
  const lines = body.split('\n')
  let index = 0
  let componentIndex = 0

  const flush = () => {
    const text = pending.join('\n')
    pending = []
    if (text.trim() !== '') blocks.push({ kind: 'markdown', text })
  }

  while (index < lines.length) {
    const opener = FENCE.exec(lines[index]!)
    if (!opener) {
      pending.push(lines[index]!)
      index += 1
      continue
    }
    const marker = opener[1]!
    const info = opener[2]!.trim()
    const raw: string[] = [lines[index]!]
    index += 1
    while (index < lines.length && !lines[index]!.trim().startsWith(marker)) {
      raw.push(lines[index]!)
      index += 1
    }
    if (index < lines.length) {
      raw.push(lines[index]!)
      index += 1
    }
    if (!info.startsWith('component:')) {
      pending.push(...raw)
      continue
    }
    flush()
    blocks.push(component(info.slice('component:'.length), raw.join('\n'), componentIndex))
    componentIndex += 1
  }
  flush()
  return { blocks }
}

const component = (type: string, raw: string, index: number): ComponentBlock => ({
  kind: 'component',
  id: ComponentId(`c-${index}`),
  type,
  data: {},
  raw,
  lang: `component:${type}`,
  unknown: false,
  errors: [],
  withheld: [],
  resolved: false,
})

const markdown = (text: string): DocumentBlock => ({ kind: 'markdown', text })

const paragraph = (length: number, word = 'word'): string =>
  Array.from({ length: Math.ceil(length / (word.length + 1)) }, () => word).join(' ')

describe('deckOf, over the lessons this system has actually written', () => {
  it.each(ALL_FIXTURES)('gives %s a deck with slides in it', (name) => {
    const deck = deckOf(parse(readFixture(name)))
    expect(deck.slides.length).toBeGreaterThan(3)
  })

  it('gives a lesson that opens with prose no title and no title slide', () => {
    // Not a degradation to work around: `agent-interaction-log-lesson-02.md`
    // is real authored output whose first heading is an `##`. The view falls
    // back to the file name, and nothing here invents a title.
    const deck = deckOf(parse(readFixture('agent-interaction-log-lesson-02.md')))
    expect(deck.title).toBeNull()
    expect(deck.slides.some((slide) => slide.kind === 'title')).toBe(false)
  })

  it.each(TITLED)('opens %s with a title slide carrying the H1', (name) => {
    const deck = deckOf(parse(readFixture(name)))
    const first = deck.slides[0]
    expect(first?.kind).toBe('title')
    expect(first?.kind === 'title' && first.title).toBe(deck.title)
  })

  it.each(ALL_FIXTURES)('puts every component of %s on a slide of its own', (name) => {
    const document = parse(readFixture(name))
    const deck = deckOf(document)
    const components = document.blocks.filter((block) => block.kind === 'component')
    const slides = deck.slides.filter((slide) => slide.kind === 'component')
    expect(slides.map((slide) => slide.block.id)).toEqual(components.map((block) => block.id))
  })

  it.each(ALL_FIXTURES)('carries every paragraph of %s onto exactly one slide', (name) => {
    // The property that makes this deck a reading of the lesson rather than an
    // extract: nothing is dropped and nothing is shown twice. Written over
    // whole paragraphs rather than a character count because a heading is
    // deliberately *not* carried as prose -- it becomes a section label.
    const source = readFixture(name)
    const deck = deckOf(parse(source))
    const shown = deck.slides
      .flatMap((slide) => (slide.kind === 'component' ? [] : [slide.text]))
      .join('\n\n')
    const paragraphs = source
      .replace(/^---\n[\s\S]*?\n---\n/, '')
      .replace(/```[\s\S]*?```/g, '')
      .split(/\n\s*\n/)
      .map((chunk) => chunk.trim())
      .filter((chunk) => chunk !== '' && !chunk.startsWith('#'))

    expect(paragraphs.length).toBeGreaterThan(5)
    for (const chunk of paragraphs) expect(shown).toContain(chunk)
  })

  it.each(ALL_FIXTURES)('never splits a paragraph of %s across two slides', (name) => {
    const deck = deckOf(parse(readFixture(name)))
    for (const slide of deck.slides) {
      if (slide.kind === 'component') continue
      // Every slide's text is a whole number of paragraphs: no slide ends
      // mid-sentence. The tell for a mid-paragraph cut is a final line that
      // does not end in terminal punctuation, a fence, or a list marker.
      const last = slide.text.trimEnd().split('\n').at(-1) ?? ''
      if (last === '') continue
      expect(last).toMatch(/[.!?:")\]`>-]$|^\s*[-*|]|^\s*\d+\./)
    }
  })

  it.each(ALL_FIXTURES)('labels each section of %s exactly once in the rail', (name) => {
    const deck = deckOf(parse(readFixture(name)))
    const labelled = railRows(deck).filter((row) => row.label !== null)
    expect(labelled.length).toBeGreaterThan(1)
    expect(railRows(deck)).toHaveLength(deck.slides.length)
    // Every slide after a labelled one, up to the next label, shares that
    // label's section -- which is what makes a continuation slide readable.
    let current: string | null = null
    for (const row of railRows(deck)) {
      if (row.label !== null) current = row.label
      expect(deck.slides[row.index]!.section).toBe(current)
    }
  })

  it('numbers slides from zero, densely', () => {
    const deck = deckOf(parse(readFixture(LESSONS[0])))
    expect(deck.slides.map((slide) => slide.index)).toEqual(
      deck.slides.map((_slide, index) => index),
    )
  })

  it('finds the cited passages and gives each one a slide', () => {
    // The pull-quote is the one slide kind that is a judgement about this
    // corpus rather than a general rule, so it is asserted against the corpus.
    const deck = deckOf(parse(readFixture(LESSONS[0])))
    const quotes = deck.slides.filter((slide) => slide.kind === 'quote')
    expect(quotes.length).toBeGreaterThan(0)
    for (const quote of quotes) expect(quote.text.startsWith('>')).toBe(true)
  })
})

describe('the segmentation rule, on the cases the corpus does not reach', () => {
  it('is empty for a null document, and for one with no blocks', () => {
    expect(deckOf(null)).toEqual({ title: null, slides: [] })
    expect(deckOf({ blocks: [] })).toEqual({ title: null, slides: [] })
  })

  it('makes one slide of a document that is a single component', () => {
    const block = component('mcq', '```component:mcq\nid: x\n```', 0)
    const deck = deckOf({ blocks: [block] })
    expect(deck.slides).toHaveLength(1)
    expect(deck.slides[0]!.kind).toBe('component')
    expect(deck.title).toBeNull()
  })

  it('packs prose with no headings at all into slides', () => {
    const deck = deckOf({ blocks: [markdown([paragraph(400), paragraph(400)].join('\n\n'))] })
    expect(deck.slides).toHaveLength(1)
    expect(deck.slides[0]!.section).toBeNull()
  })

  it('starts a new slide rather than exceeding the budget', () => {
    const deck = deckOf({
      blocks: [markdown([paragraph(600), paragraph(600), paragraph(600)].join('\n\n'))],
    })
    expect(deck.slides).toHaveLength(3)
  })

  it('gives an over-budget paragraph a slide of its own, whole', () => {
    // The rule that is not a tuning parameter. Would fail with any
    // implementation that cut prose to fit -- and passes trivially with one
    // that never packs at all, which is why the budget test above is beside it.
    const long = paragraph(SLIDE_BUDGET * 2)
    const deck = deckOf({ blocks: [markdown(long)] })
    expect(deck.slides).toHaveLength(1)
    expect(deck.slides[0]!.kind === 'prose' && deck.slides[0]!.text).toBe(long)
  })

  it('reads a heading inside a fence as code, not as a section', () => {
    // A markdown block genuinely contains non-component fences -- the server
    // hands them back verbatim -- so a shell example opening `# install` would
    // otherwise start a section. Silent: the deck would simply have a slide
    // titled after a comment.
    const deck = deckOf({
      blocks: [markdown('## Real section\n\n```sh\n# install the thing\nnpm i\n```')],
    })
    expect(railRows(deck).filter((row) => row.label !== null)).toHaveLength(1)
    expect(deck.slides[0]!.section).toBe('Real section')
  })

  it('does not split a fenced block at the blank line inside it', () => {
    const deck = deckOf({ blocks: [markdown('```py\na = 1\n\nb = 2\n```')] })
    expect(deck.slides).toHaveLength(1)
    expect(deck.slides[0]!.kind === 'prose' && deck.slides[0]!.text).toContain('b = 2')
  })

  it('treats an H4 as content rather than as structure', () => {
    const deck = deckOf({ blocks: [markdown('## Section\n\n#### Aside\n\nBody.')] })
    expect(railRows(deck).filter((row) => row.label !== null)).toHaveLength(1)
    expect(deck.slides[0]!.kind === 'prose' && deck.slides[0]!.text).toContain('#### Aside')
  })

  it('keeps a paragraph that merely opens with a quote as prose', () => {
    // The distinguishing case, chosen the way CLAUDE.md asks: a rule matching
    // "starts with `>`" and one matching "is entirely `>`" agree on every
    // pull-quote in the corpus and differ only here.
    const deck = deckOf({ blocks: [markdown('> quoted line\nand then prose.')] })
    expect(deck.slides[0]!.kind).toBe('prose')
    expect(deckOf({ blocks: [markdown('> quoted line\n> more quote.')] }).slides[0]!.kind).toBe(
      'quote',
    )
  })

  it('lifts speaker notes off the prose and onto the slide', () => {
    const deck = deckOf({
      blocks: [markdown('Visible prose.\n<!-- notes: say the thing slowly -->')],
    })
    expect(deck.slides[0]!.notes).toEqual(['say the thing slowly'])
    expect(deck.slides[0]!.kind === 'prose' && deck.slides[0]!.text).toBe('Visible prose.')
  })

  it('attaches a note written above a component to that component', () => {
    const deck = deckOf({
      blocks: [markdown('<!-- notes: ask before revealing -->'), component('mcq', '```', 0)],
    })
    expect(deck.slides).toHaveLength(1)
    expect(deck.slides[0]!.notes).toEqual(['ask before revealing'])
  })

  it('finds no notes in any lesson that exists, which is the point', () => {
    // Stated as a test rather than as a comment: nothing authors
    // `<!-- notes: -->` today, so this is the reader half of a contract whose
    // writer half is not written. If this ever goes red, the writer half
    // landed and this test should be replaced by one that reads it.
    for (const name of ALL_FIXTURES) {
      const deck = deckOf(parse(readFixture(name)))
      expect(deck.slides.flatMap((slide) => slide.notes)).toEqual([])
    }
  })

  it('folds the lead paragraph onto the title slide', () => {
    const deck = deckOf({ blocks: [markdown('# Title\n\nThe opening.\n\n## Next\n\nMore.')] })
    expect(deck.slides[0]!.kind === 'title' && deck.slides[0]!.text).toBe('The opening.')
    expect(deck.slides).toHaveLength(2)
    expect(deck.slides[1]!.index).toBe(1)
  })

  it('clamps a slide index rather than failing on it', () => {
    const deck = deckOf({ blocks: [markdown('# T\n\nA.\n\n## B\n\nC.')] })
    expect(clampSlide(deck, 99)).toBe(deck.slides.length - 1)
    expect(clampSlide(deck, -4)).toBe(0)
    expect(clampSlide(deck, Number.NaN)).toBe(0)
    expect(clampSlide({ title: null, slides: [] }, 3)).toBe(0)
  })
})

import { describe, expect, it } from 'vitest'

import { ComponentId } from '../shared/identifier.ts'
import type { ComponentBlock } from './document.ts'
import {
  activeBlank,
  clozeBlanks,
  readChecklist,
  readCloze,
  readFlashcards,
  readMcq,
} from './widgets.ts'

const block = (data: Record<string, unknown>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId('c1'),
  type: 'test',
  data,
  raw: '',
  lang: null,
  unknown: false,
  errors: [],
  withheld: [],
  resolved: false,
})

/** `data` is an open record because the set of widget types is open. These
 *  readers narrow it at the one place a renderer needs it — and they default
 *  rather than throw, because an empty deck rendering as "no cards" is a far
 *  better failure for a *viewer* than a blank page. */
describe('readFlashcards', () => {
  it('reads a deck', () => {
    const deck = readFlashcards(block({ title: 'Terms', cards: [{ front: 'a', back: 'b' }] }))
    expect(deck).toEqual({ title: 'Terms', cards: [{ front: 'a', back: 'b' }] })
  })

  it('treats a missing or malformed deck as empty rather than throwing', () => {
    expect(readFlashcards(block({})).cards).toEqual([])
    expect(readFlashcards(block({ cards: 'nope' })).cards).toEqual([])
    expect(readFlashcards(block({ cards: [null] })).cards).toEqual([{ front: '', back: '' }])
  })
})

describe('readMcq', () => {
  it('reads multiple-answer only from an explicit true', () => {
    expect(readMcq(block({ multiple: true })).multiple).toBe(true)
    expect(readMcq(block({ multiple: 'yes' })).multiple).toBe(false)
    expect(readMcq(block({})).multiple).toBe(false)
  })

  it('reads options and prompt', () => {
    const mcq = readMcq(block({ prompt: 'Which?', options: [{ text: 'a' }, { text: 'b' }] }))
    expect(mcq.prompt).toBe('Which?')
    expect(mcq.options.map((o) => o.text)).toEqual(['a', 'b'])
  })
})

describe('readCloze', () => {
  const passage = block({
    segments: [{ text: 'The ' }, { blank: 0, hint: 'colour' }, { text: ' cat' }, { blank: 1 }],
  })

  it('separates text runs from numbered blanks', () => {
    const cloze = readCloze(passage)
    expect(cloze.segments.map((s) => s.kind)).toEqual(['text', 'blank', 'text', 'blank'])
    expect(clozeBlanks(cloze).map((b) => b.blank)).toEqual([0, 1])
  })

  it('defaults to one-at-a-time, which is what makes the mode mean anything', () => {
    expect(readCloze(block({})).oneAtATime).toBe(true)
    expect(readCloze(block({ mode: 'all-at-once' })).oneAtATime).toBe(false)
  })

  describe('activeBlank', () => {
    it('is the first blank with nothing typed in it', () => {
      const cloze = readCloze(passage)
      expect(activeBlank(cloze, {})).toBe(0)
      expect(activeBlank(cloze, { 0: 'black' })).toBe(1)
    })

    it('treats whitespace as unanswered', () => {
      expect(activeBlank(readCloze(passage), { 0: '   ' })).toBe(0)
    })

    it('opens every blank once they are all filled, so a learner can revise', () => {
      expect(activeBlank(readCloze(passage), { 0: 'a', 1: 'b' })).toBe(Number.POSITIVE_INFINITY)
    })
  })
})

describe('readChecklist', () => {
  it('reads items, and required only from an explicit true', () => {
    const list = readChecklist(
      block({ items: [{ text: 'a', required: true }, { text: 'b' }, { text: 'c', required: 1 }] }),
    )
    expect(list.items.map((i) => i.required)).toEqual([true, false, false])
  })

  it('persists only when the author asked for it', () => {
    expect(readChecklist(block({ persist: true })).persist).toBe(true)
    expect(readChecklist(block({})).persist).toBe(false)
  })
})

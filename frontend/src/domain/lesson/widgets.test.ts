import { describe, expect, it } from 'vitest'

import { ComponentId } from '../shared/identifier.ts'
import type { ComponentBlock } from './document.ts'
import {
  activeBlank,
  clozeBlanks,
  readChecklist,
  readCloze,
  readExplorerQuery,
  readFlashcards,
  readMcq,
  varies,
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

/** What `readExplorerQuery` narrows out of an open record.
 *
 * The server's `data` is `Readonly<Record<string, unknown>>` because the set of
 * widget types is open, so every field here is a narrowing that must default
 * rather than throw -- a block that reached the browser malformed should draw
 * a degraded widget, not take the answer down.
 */
describe('readExplorerQuery', () => {
  it('reads the author’s fixed window and the axes they opened', () => {
    const spec = readExplorerQuery(
      block({
        over: 'timeline',
        prompt: 'Narrow to Emperors.',
        vary: ['entity_type', 'window'],
        entity_type: 'Person',
        from: '0300-01-01',
        to: '0400-01-01',
        limit: 40,
      }),
    )

    expect(spec.over).toBe('timeline')
    expect(spec.prompt).toBe('Narrow to Emperors.')
    expect(spec.vary).toEqual(['entity_type', 'window'])
    expect(spec.window).toEqual({
      entityType: 'Person',
      from: '0300-01-01',
      to: '0400-01-01',
      limit: 40,
    })
  })

  it('drops an axis it does not implement rather than carrying it to a control', () => {
    // The registry rejects an unknown axis, so this shape only reaches here from
    // a hand-built block or from a *newer server* -- and the newer server is the
    // real case: an older bundle meeting `vary: [topic]` must draw the controls
    // it has, not crash or draw a dead third. Red against a reader that casts.
    const spec = readExplorerQuery(
      block({ over: 'timeline', prompt: 'Look.', vary: ['window', 'topic', 7] }),
    )

    expect(spec.vary).toEqual(['window'])
  })

  it('leaves every bound open when the author fixed none', () => {
    // An omitted bound is an open end, matching `readTimelineQuery`. Red against
    // a reader that defaults `from` to anything: the request would silently
    // narrow and the reader would explore a window nobody chose.
    const spec = readExplorerQuery(block({ over: 'timeline', prompt: 'Look.', vary: ['window'] }))

    expect(spec.window).toEqual({ entityType: null, from: null, to: null, limit: null })
  })

  it('reports an unsupported backing read as itself rather than defaulting it', () => {
    // `over` is warned about on the server and not rejected, so this body is
    // valid and reaches the widget. The widget renders prose naming what is
    // supported, and it can only do that if the reader passes the value through.
    // Red against `over: str(...) ?? 'timeline'`, which would silently run a
    // graph explorer's invitation against the timeline.
    const spec = readExplorerQuery(block({ over: 'graph', prompt: 'Look.', vary: ['window'] }))

    expect(spec.over).toBe('graph')
  })

  it('says an axis is closed when the author did not open it', () => {
    const spec = readExplorerQuery(block({ over: 'timeline', prompt: 'Look.', vary: ['window'] }))

    expect(varies(spec, 'window')).toBe(true)
    expect(varies(spec, 'entity_type')).toBe(false)
  })
})

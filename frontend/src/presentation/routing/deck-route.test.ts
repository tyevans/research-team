import { describe, expect, it } from 'vitest'

import { parseDeck, parseRoute, parseSeekSeconds, withDeck } from './routes.ts'

/** `?deck=&slide=` -- the second half of "a slide is a linkable thing".
 *
 * Its own file rather than a block in `routes.test.ts` for the reason the deck
 * is its own parser: it is a query over whatever route is showing, not an arm
 * of the route grammar, and mixing the two suites would invite an assertion
 * that treats it as a facet.
 *
 * **Proved red** by returning `null` from `parseDeck` unconditionally (nine
 * fail) and by dropping the `params.delete('deck')` in `withDeck` (the
 * round-trip and the two "leaves the rest alone" tests fail, and only those).
 */

describe('reading a deck off a hash', () => {
  it('is null when nothing is being presented', () => {
    expect(parseDeck('#/p/abc/course/knowledge-graph')).toBeNull()
    expect(parseDeck('#/')).toBeNull()
  })

  it('reads the lesson path and defaults to the first slide', () => {
    expect(parseDeck('#/p/abc/course/kg?deck=/course/areas/kg/lesson-01.md')).toEqual({
      path: '/course/areas/kg/lesson-01.md',
      slide: 0,
    })
  })

  it('reads the slide when the link carries one', () => {
    expect(parseDeck('#/p/abc/course/kg?deck=/l.md&slide=7')).toEqual({ path: '/l.md', slide: 7 })
  })

  it('treats a malformed slide as the first one rather than as NaN', () => {
    // The failure this guards reaches an array index and renders nothing at
    // all, which looks like an empty lesson rather than like a bad link.
    for (const bad of ['', 'seven', '-3', 'NaN', 'Infinity']) {
      expect(parseDeck(`#/p/a/course/k?deck=/l.md&slide=${bad}`)?.slide).toBe(0)
    }
  })

  it('truncates a fractional slide rather than indexing between two', () => {
    expect(parseDeck('#/p/a/course/k?deck=/l.md&slide=2.7')?.slide).toBe(2)
  })

  it('is not a deck without a path, however much else the query carries', () => {
    expect(parseDeck('#/p/a/course/k?slide=4')).toBeNull()
    expect(parseDeck('#/p/a/course/k?deck=&slide=4')).toBeNull()
  })

  it('leaves the route underneath it exactly as it was', () => {
    // The whole argument for a query rather than a route segment: the page
    // behind the deck is unchanged and stays unchanged.
    const route = parseRoute('#/p/abc/course/kg?deck=/l.md&slide=3')
    expect(route).toEqual(parseRoute('#/p/abc/course/kg'))
  })
})

describe('writing a deck onto a hash', () => {
  it('round-trips every position it can print', () => {
    for (const slide of [0, 1, 42]) {
      const href = withDeck('#/p/abc/course/kg', { path: '/l.md', slide })
      expect(parseDeck(href)).toEqual({ path: '/l.md', slide })
    }
  })

  it('prints the first slide without a slide parameter, so it has one spelling', () => {
    expect(withDeck('#/p/abc/course/kg', { path: '/l.md', slide: 0 })).toBe(
      '#/p/abc/course/kg?deck=%2Fl.md',
    )
  })

  it('returns the hash it was given when the deck closes', () => {
    const opened = withDeck('#/p/abc/course/kg', { path: '/l.md', slide: 5 })
    expect(withDeck(opened, null)).toBe('#/p/abc/course/kg')
  })

  it('keeps a query the route already carried', () => {
    // `?t=` is a citation's own moment, and closing a deck must not throw it
    // away. Rebuilding the hash from a `Route` would have done exactly that,
    // which is why `withDeck` rewrites the hash it is handed.
    const opened = withDeck('#/p/abc/doc/src-1?t=252.5', { path: '/l.md', slide: 2 })
    expect(parseSeekSeconds(opened)).toBe(252.5)
    expect(parseSeekSeconds(withDeck(opened, null))).toBe(252.5)
    expect(parseDeck(withDeck(opened, null))).toBeNull()
  })

  it('replaces rather than repeats when a deck is already open', () => {
    const first = withDeck('#/p/abc/course/kg', { path: '/one.md', slide: 3 })
    const second = withDeck(first, { path: '/two.md', slide: 1 })
    expect(parseDeck(second)).toEqual({ path: '/two.md', slide: 1 })
    expect(second.match(/deck=/g)).toHaveLength(1)
  })

  it('encodes a path so its slashes stay inside one parameter', () => {
    const href = withDeck('#/p/a/course/k', {
      path: '/course/areas/kg/lesson-01.md',
      slide: 0,
    })
    expect(href).not.toContain('deck=/course')
    expect(parseDeck(href)?.path).toBe('/course/areas/kg/lesson-01.md')
  })
})

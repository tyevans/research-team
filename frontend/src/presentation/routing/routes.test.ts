import { describe, expect, it } from 'vitest'

import { EventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { SessionId } from '@domain/shared/identifier.ts'

import { parseRoute, sessionHref } from './routes.ts'

describe('parseRoute', () => {
  it('reads the tree for an empty or unknown hash', () => {
    expect(parseRoute('')).toEqual({ name: 'tree' })
    expect(parseRoute('#/')).toEqual({ name: 'tree' })
    expect(parseRoute('#/nonsense')).toEqual({ name: 'tree' })
  })

  it('reads a session at HEAD', () => {
    const route = parseRoute('#/s/abc')
    expect(route).toMatchObject({ name: 'session', id: 'abc', path: null })
    expect(route.name === 'session' && route.at.kind).toBe('head')
  })

  it('reads a scrub position', () => {
    const route = parseRoute('#/s/abc/at/12')
    expect(route.name === 'session' && route.at).toEqual({ kind: 'historical', at: 12 })
  })

  it('falls back to HEAD rather than a nonsense position', () => {
    const route = parseRoute('#/s/abc/at/zero')
    expect(route.name === 'session' && route.at.kind).toBe('head')
  })

  it('keeps directories in a file route', () => {
    const route = parseRoute(`#/s/abc/file/${encodeURIComponent('docs/design/plan.md')}`)
    expect(route.name === 'session' && route.path?.value).toBe('docs/design/plan.md')
  })

  it('reads a course by project', () => {
    expect(parseRoute('#/p/proj-1/course')).toEqual({ name: 'course', id: 'proj-1' })
  })
})

describe('sessionHref', () => {
  const id = SessionId('abc')

  it('round-trips a scrub position', () => {
    const href = sessionHref(id, ScrubPoint.at(EventIndex(7)))
    expect(parseRoute(href)).toMatchObject({ at: { kind: 'historical', at: 7 } })
  })

  it('round-trips a path with a slash in it', () => {
    const href = sessionHref(id, undefined, FilePath.of('a/b c.md'))
    const route = parseRoute(href)
    expect(route.name === 'session' && route.path?.value).toBe('a/b c.md')
  })

  it('omits the position at HEAD', () => {
    expect(sessionHref(id, ScrubPoint.head())).toBe('#/s/abc')
  })
})

describe('a session route carrying both a position and a file', () => {
  const id = SessionId('abc')

  it('round-trips them together', () => {
    const href = sessionHref(id, ScrubPoint.at(EventIndex(6)), FilePath.of('/course/plan.md'))
    const route = parseRoute(href)
    expect(route.name === 'session' && route.at).toEqual({ kind: 'historical', at: 6 })
    expect(route.name === 'session' && route.path?.value).toBe('/course/plan.md')
  })

  it('keeps the file when the position is HEAD', () => {
    const route = parseRoute(sessionHref(id, ScrubPoint.head(), FilePath.of('a.md')))
    expect(route.name === 'session' && route.at.kind).toBe('head')
    expect(route.name === 'session' && route.path?.value).toBe('a.md')
  })

  it('keeps the position when no file is open', () => {
    const route = parseRoute(sessionHref(id, ScrubPoint.at(EventIndex(3)), null))
    expect(route.name === 'session' && route.at).toEqual({ kind: 'historical', at: 3 })
    expect(route.name === 'session' && route.path).toBeNull()
  })
})

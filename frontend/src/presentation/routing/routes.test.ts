import { describe, expect, it } from 'vitest'

import { EventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { courseHref, parseRoute, researchHref, sessionHref } from './routes.ts'

describe('parseRoute', () => {
  it('reads the tree for an empty or unknown hash', () => {
    expect(parseRoute('')).toEqual({ name: 'home' })
    expect(parseRoute('#/')).toEqual({ name: 'home' })
    expect(parseRoute('#/nonsense')).toEqual({ name: 'home' })
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
    expect(parseRoute('#/p/proj-1/course')).toEqual({
      name: 'course',
      id: 'proj-1',
      watching: null,
    })
  })

  it('parses a research route', () => {
    // Sits under the project the way `course` does: what it shows outlives any
    // one session, so it is keyed the way the material is stored.
    expect(parseRoute('#/p/abc/research')).toEqual({
      name: 'research',
      id: ProjectId('abc'),
      entity: null,
    })
  })

  it('builds a research href', () => {
    expect(researchHref(ProjectId('abc'))).toBe('#/p/abc/research')
  })

  it('carries the selected entity in the research route, both ways', () => {
    expect(parseRoute('#/p/abc/research/entity/e1')).toEqual({
      name: 'research',
      id: ProjectId('abc'),
      entity: 'e1',
    })
    expect(researchHref(ProjectId('abc'), 'e1')).toBe('#/p/abc/research/entity/e1')
  })

  it('lands on an empty canvas when the entity segment has no id after it', () => {
    expect(parseRoute('#/p/abc/research/entity')).toEqual({
      name: 'research',
      id: ProjectId('abc'),
      entity: null,
    })
  })
})

describe('the watched session', () => {
  it('reads a watched session out of the course route', () => {
    const route = parseRoute(
      '#/p/11111111-1111-1111-1111-111111111111/course/watching/22222222-2222-2222-2222-222222222222',
    )

    expect(route).toEqual({
      name: 'course',
      id: '11111111-1111-1111-1111-111111111111',
      watching: '22222222-2222-2222-2222-222222222222',
    })
  })

  it('leaves it null on a plain course route', () => {
    const route = parseRoute('#/p/11111111-1111-1111-1111-111111111111/course')
    expect(route).toEqual({
      name: 'course',
      id: '11111111-1111-1111-1111-111111111111',
      watching: null,
    })
  })

  it('ignores a watching segment with no session after it', () => {
    // A hand-truncated URL is still a course route. Falling through to the
    // tree would send somebody somewhere they did not ask for.
    const route = parseRoute('#/p/11111111-1111-1111-1111-111111111111/course/watching')
    expect(route).toEqual({
      name: 'course',
      id: '11111111-1111-1111-1111-111111111111',
      watching: null,
    })
  })

  it('round-trips through courseHref', () => {
    const href = courseHref(
      ProjectId('11111111-1111-1111-1111-111111111111'),
      SessionId('22222222-2222-2222-2222-222222222222'),
    )
    expect(parseRoute(href)).toEqual({
      name: 'course',
      id: '11111111-1111-1111-1111-111111111111',
      watching: '22222222-2222-2222-2222-222222222222',
    })
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

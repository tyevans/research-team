import { describe, expect, it } from 'vitest'

import { EventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import {
  FACETS,
  parseRoute,
  projectHref,
  sessionHref,
  sessionSelection,
  type Facet,
  type Route,
  type Selection,
} from './routes.ts'

const PROJECT = ProjectId('abc')

describe('parseRoute', () => {
  it('reads the picker for an empty or unknown hash', () => {
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

  it('reads a project page with nothing selected', () => {
    expect(parseRoute('#/p/abc')).toEqual({ name: 'project', id: PROJECT, selection: null })
  })
})

/** The grammar itself: every facet the proposal names, parsed and rebuilt.
 *
 * Table-driven because the claim is about the *set* — "one grammar covering
 * every linkable state" is false if seven of eight work. Adding a member to
 * `Facet` without adding it here leaves it untested, so the last case in this
 * block asserts the table is complete. */
describe('the facet grammar', () => {
  const cases: ReadonlyArray<{ facet: Facet; selection: Selection; hash: string }> = [
    {
      facet: 'session',
      selection: sessionSelection(SessionId('s1')),
      hash: '#/p/abc/session/s1',
    },
    { facet: 'topic', selection: { facet: 'topic', id: 't1' }, hash: '#/p/abc/topic/t1' },
    { facet: 'stage', selection: { facet: 'stage', id: 'design' }, hash: '#/p/abc/stage/design' },
    { facet: 'entity', selection: { facet: 'entity', id: 'e1' }, hash: '#/p/abc/entity/e1' },
    { facet: 'doc', selection: { facet: 'doc', id: 'd1' }, hash: '#/p/abc/doc/d1' },
    {
      facet: 'file',
      selection: { facet: 'file', id: FilePath.of('a/b.md') },
      hash: `#/p/abc/file/${encodeURIComponent('a/b.md')}`,
    },
    {
      facet: 'artifact',
      selection: { facet: 'artifact', id: 'findings.md' },
      hash: '#/p/abc/artifact/findings.md',
    },
    { facet: 'finding', selection: { facet: 'finding', id: 'f1' }, hash: '#/p/abc/finding/f1' },
  ]

  it.each(cases)('builds $facet', ({ selection, hash }) => {
    expect(projectHref(PROJECT, selection)).toBe(hash)
  })

  it.each(cases)('parses $facet', ({ selection, hash }) => {
    expect(parseRoute(hash)).toEqual({ name: 'project', id: PROJECT, selection })
  })

  it.each(cases)('round-trips $facet through its builder', ({ selection }) => {
    expect(parseRoute(projectHref(PROJECT, selection))).toEqual({
      name: 'project',
      id: PROJECT,
      selection,
    })
  })

  it.each(cases)('keeps $facet selectable with no id', ({ facet, selection }) => {
    // The truncation rule the two old routes had: a hand-edited URL with the
    // facet and nothing after it stays on the page with that facet open and
    // nothing chosen. Load-bearing, not tidiness -- the facet is also what
    // chooses the view, so "the graph, empty" has no other spelling.
    const empty = { ...selection, id: null } as Selection
    expect(projectHref(PROJECT, empty)).toBe(`#/p/abc/${facet}`)
    expect(parseRoute(`#/p/abc/${facet}`)).toEqual({
      name: 'project',
      id: PROJECT,
      selection: empty,
    })
  })

  it('covers every facet the module declares', () => {
    // Fails when someone changes `FACETS` and not this table, which is the
    // failure the three blocks above cannot have: they iterate the table, so
    // an untested facet is invisible to them. Against `FACETS` itself rather
    // than a hand-copied list, which would be a second thing to forget.
    expect([...cases.map((c) => c.facet)].sort()).toEqual([...FACETS].sort())
  })
})

describe('an unrecognised facet', () => {
  it('falls to the picker rather than throwing', () => {
    expect(() => parseRoute('#/p/abc/nonsense/1')).not.toThrow()
    expect(parseRoute('#/p/abc/nonsense/1')).toEqual({ name: 'home' })
    expect(parseRoute('#/p/abc/nonsense')).toEqual({ name: 'home' })
  })

  it('does not quietly become the project page', () => {
    // The tempting fallback, and the wrong one: a dead link would then answer
    // a question nobody asked, and look like it worked.
    expect(parseRoute('#/p/abc/course')).not.toMatchObject({ name: 'project' })
  })
})

describe('the three states this grammar exists to make linkable', () => {
  it('addresses a topic', () => {
    // Was component state in `TopicList`'s Manage, so "look at this topic"
    // could not be sent to anybody.
    expect(parseRoute('#/p/abc/topic/t1')).toEqual({
      name: 'project',
      id: PROJECT,
      selection: { facet: 'topic', id: 't1' },
    })
  })

  it('addresses an artifact without naming a session', () => {
    // Was a link into whichever session happened to hold the project, so the
    // link died when the holder changed. The project is what owns an artifact.
    const route = parseRoute(projectHref(PROJECT, { facet: 'artifact', id: 'plan.md' }))
    expect(route).toEqual({
      name: 'project',
      id: PROJECT,
      selection: { facet: 'artifact', id: 'plan.md' },
    })
    expect(projectHref(PROJECT, { facet: 'artifact', id: 'plan.md' })).not.toContain('/s/')
  })

  it('addresses a stage', () => {
    // Was one string in `CourseView`'s state, which is why a course page
    // always loaded fully collapsed.
    expect(parseRoute('#/p/abc/stage/design')).toEqual({
      name: 'project',
      id: PROJECT,
      selection: { facet: 'stage', id: 'design' },
    })
  })
})

describe('the session facet and the short form', () => {
  const id = SessionId('s1')

  it('carries a position and a file under a project', () => {
    const href = projectHref(
      PROJECT,
      sessionSelection(id, ScrubPoint.at(EventIndex(12)), FilePath.of('a.md')),
    )
    expect(href).toBe('#/p/abc/session/s1/at/12/file/a.md')
    expect(parseRoute(href)).toEqual({
      name: 'project',
      id: PROJECT,
      selection: sessionSelection(id, ScrubPoint.at(EventIndex(12)), FilePath.of('a.md')),
    })
  })

  it('still reads the short form', () => {
    // `#/s/<id>` stays a top-level route: every link into a transcript from
    // outside the console has a session id and no project id.
    const route = parseRoute('#/s/s1/at/12/file/a.md')
    expect(route.name).toBe('session')
    expect(route.name === 'session' && route.at).toEqual({ kind: 'historical', at: 12 })
    expect(route.name === 'session' && route.path?.value).toBe('a.md')
  })

  it('omits the position at HEAD in both forms', () => {
    expect(sessionHref(id, ScrubPoint.head())).toBe('#/s/s1')
    expect(projectHref(PROJECT, sessionSelection(id, ScrubPoint.head()))).toBe('#/p/abc/session/s1')
  })

  it('keeps a path with slashes in one segment under a project', () => {
    const href = projectHref(PROJECT, sessionSelection(id, undefined, FilePath.of('a/b c.md')))
    const route = parseRoute(href)
    expect(
      route.name === 'project' &&
        route.selection?.facet === 'session' &&
        route.selection.path?.value,
    ).toBe('a/b c.md')
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

  it('keeps the position when no file is open', () => {
    const route = parseRoute(sessionHref(id, ScrubPoint.at(EventIndex(3)), null))
    expect(route.name === 'session' && route.at).toEqual({ kind: 'historical', at: 3 })
    expect(route.name === 'session' && route.path).toBeNull()
  })

  it('keeps the file when the position is HEAD', () => {
    const route = parseRoute(sessionHref(id, ScrubPoint.head(), FilePath.of('a.md')))
    expect(route.name === 'session' && route.at.kind).toBe('head')
    expect(route.name === 'session' && route.path?.value).toBe('a.md')
  })
})

describe('a hand-typed path, unescaped', () => {
  // The builders percent-encode, so a round-trip test cannot see the rejoin at
  // all -- an encoded path arrives as one segment either way. This is the case
  // that distinguishes them: somebody typing or pasting a path into the bar.
  it('keeps directories on the file facet', () => {
    const route = parseRoute('#/p/abc/file/docs/design/plan.md')
    expect(
      route.name === 'project' && route.selection?.facet === 'file' && route.selection.id,
    ).toMatchObject({ value: 'docs/design/plan.md' })
  })

  it('keeps directories on the session facet', () => {
    const route = parseRoute('#/p/abc/session/s1/at/4/file/docs/plan.md')
    expect(
      route.name === 'project' &&
        route.selection?.facet === 'session' &&
        route.selection.path?.value,
    ).toBe('docs/plan.md')
  })

  it('keeps directories on the standalone session route', () => {
    const route = parseRoute('#/s/s1/file/docs/plan.md')
    expect(route.name === 'session' && route.path?.value).toBe('docs/plan.md')
  })
})

describe('projectHref', () => {
  it('builds the bare project page', () => {
    expect(projectHref(PROJECT)).toBe('#/p/abc')
    expect(projectHref(PROJECT, null)).toBe('#/p/abc')
  })

  it('encodes an id that would otherwise open a segment', () => {
    const href = projectHref(PROJECT, { facet: 'entity', id: 'a/b' })
    expect(href).toBe(`#/p/abc/entity/${encodeURIComponent('a/b')}`)
    const route: Route = parseRoute(href)
    expect(route.name === 'project' && route.selection?.id).toBe('a/b')
  })
})

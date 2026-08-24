import { describe, expect, it } from 'vitest'

import { EventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { FilePath } from '@domain/shared/file-path.ts'
import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { expandReferences } from '../../infrastructure/rendering/references.ts'

import {
  FACETS,
  parseRoute,
  parseSeekSeconds,
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

  // `wouter`'s `useHashLocation` hands the whole hash to this function, query
  // string and all -- `?t=252` is not stripped anywhere upstream. Before
  // `splitQuery` existed, `parts = hash.split('/')` folded that query onto
  // the end of whatever segment came last, because `?t=252` contains no `/`
  // for the split to catch. A citation's own `?t=252` link corrupted the id
  // it pointed at: this is the regression that would reintroduce.
  it('does not let a `?t=` query corrupt the id it trails', () => {
    const route = parseRoute(`#/p/abc/doc/${encodeURIComponent('wiki-trajan')}?t=252`)
    expect(route).toEqual({
      name: 'project',
      id: PROJECT,
      selection: { facet: 'doc', id: 'wiki-trajan' },
    })
  })
})

describe('parseSeekSeconds', () => {
  it('reads a whole-second offset', () => {
    expect(parseSeekSeconds('#/p/abc/doc/x?t=252')).toBe(252)
  })

  // The falsy trap, at the URL boundary rather than the render boundary:
  // `0` is a real requested second and `if (parseSeekSeconds(hash))` at any
  // call site would silently discard it.
  it('reads a zero offset rather than treating it as absent', () => {
    expect(parseSeekSeconds('#/p/abc/doc/x?t=0')).toBe(0)
  })

  // `GraphDetail` formats a definition citation's `atSeconds` -- a float --
  // with plain `String()`, so a genuine fraction reaches this query and has
  // to survive the round trip rather than truncate.
  it('reads a fractional offset', () => {
    expect(parseSeekSeconds('#/p/abc/doc/x?t=252.5')).toBe(252.5)
  })

  it('is null with no query at all', () => {
    expect(parseSeekSeconds('#/p/abc/doc/x')).toBeNull()
  })

  it('is null for a `t` that is not a well-formed non-negative number', () => {
    // Hand-edited or model-influenced junk, each covering a different way a
    // naive parse would misbehave: `NaN` reaching `HTMLMediaElement.
    // currentTime` throws, so every one of these has to come back `null`
    // rather than a number a caller would seek to blindly.
    expect(parseSeekSeconds('#/p/abc/doc/x?t=')).toBeNull()
    expect(parseSeekSeconds('#/p/abc/doc/x?t=soon')).toBeNull()
    expect(parseSeekSeconds('#/p/abc/doc/x?t=-5')).toBeNull()
    // A range, not a moment. This *was* documented here as a shape
    // `expandReferences` never emits -- false: it emitted exactly this for
    // `[[src:x@5-10]]` until references.ts collapsed a range to its start,
    // and every reference with an end seeked nowhere as a result. `,` is
    // still rejected -- there is no second field for an end to occupy -- but
    // it is rejected because a comma-bearing `t` is invalid input, not
    // because this app never produces one.
    expect(parseSeekSeconds('#/p/abc/doc/x?t=5,10')).toBeNull()
  })

  it('accepts a range reference expansion and seeks to its start', () => {
    // Pins the round trip BLOCKER 2 was about: expandReferences(id@252-310)
    // -> a URL -> parseSeekSeconds. Importing expandReferences here (rather
    // than hand-writing the query) is deliberate -- a hand-written `?t=252`
    // would pass even if the two files drifted again.
    const html = expandReferences('[[src:x@252-310]]', ProjectId('abc'))
    const href = /href="([^"]+)"/.exec(html)?.[1]
    expect(href).toBeDefined()
    expect(parseSeekSeconds(href!)).toBe(252)
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
    {
      facet: 'timeline',
      selection: { facet: 'timeline', id: 'e1' },
      hash: '#/p/abc/timeline/e1',
    },
    {
      facet: 'tree',
      selection: { facet: 'tree', id: 'e1' },
      hash: '#/p/abc/tree/e1',
    },
    {
      // Carries an id like every other plain facet even though the classes view
      // selects nothing today: the grammar gives every facet an id slot, and
      // the round trip has to hold for the slot whether or not a view uses it.
      facet: 'ontology',
      selection: { facet: 'ontology', id: 'c1' },
      hash: '#/p/abc/ontology/c1',
    },
    {
      // An area slug, not a uuid: the id is derived from the area's top anchor
      // and is the same string that names its directory under `/course/areas/`.
      // Worth a case of its own for that reason -- every other plain facet's id
      // is opaque, and this one is a value a person may type.
      facet: 'area',
      selection: { facet: 'area', id: 'the-principate' },
      hash: '#/p/abc/area/the-principate',
    },
    {
      // Shares the Curriculum tab with `area` rather than having one of its
      // own (see `MATERIAL_TABS`), and is still a facet: which reading somebody
      // is looking at is a linkable state, which is the whole grammar's point.
      facet: 'path',
      selection: { facet: 'path', id: 'the-principate' },
      hash: '#/p/abc/path/the-principate',
    },
    {
      // The Curriculum tab's default reading. `id` here is a category key, not
      // an area slug -- a different namespace from `area` above even though
      // both are strings a person might type.
      facet: 'catalog',
      selection: { facet: 'catalog', id: 'antiquity' },
      hash: '#/p/abc/catalog/antiquity',
    },
    {
      // A candidate slug, not a category key -- `catalog`'s own comment
      // above states why this is a facet of its own rather than folded into
      // `catalog`'s id.
      facet: 'course',
      selection: { facet: 'course', id: 'the-fall-of-rome' },
      hash: '#/p/abc/course/the-fall-of-rome',
    },
    { facet: 'doc', selection: { facet: 'doc', id: 'd1' }, hash: '#/p/abc/doc/d1' },
    { facet: 'media', selection: { facet: 'media', id: 'p1' }, hash: '#/p/abc/media/p1' },
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
    // The only facet with nothing to select: the ask page is one ephemeral
    // conversation, and there is no id that would name a part of it. Its
    // entry here is `id: null` rather than a stand-in, so the four cases
    // below describe the URL that actually exists.
    { facet: 'ask', selection: { facet: 'ask', id: null }, hash: '#/p/abc/ask' },
    // Unlike `ask` above it, this one has something to select: a dialogue id is
    // minted by the server and is a row key, so it is a URL segment worth
    // building. The truncation case below still has to hold -- `#/p/abc/dialogue`
    // with nothing after it is a reader about to start one.
    { facet: 'dialogue', selection: { facet: 'dialogue', id: 'd1' }, hash: '#/p/abc/dialogue/d1' },
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
    expect(parseRoute('#/p/abc/wonderland')).not.toMatchObject({ name: 'project' })
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

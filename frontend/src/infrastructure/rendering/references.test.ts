import { describe, expect, it } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { expandReferences } from './references.ts'

const projectId = ProjectId('proj-1')

describe('expandReferences', () => {
  it('links a bare source reference', () => {
    expect(expandReferences('see [[src:wiki-trajan]] for more', projectId)).toContain(
      'href="#/p/' + projectId + '/doc/wiki-trajan"',
    )
  })

  it('carries a point offset as a query parameter on the hash route', () => {
    // Not a media fragment: a hash-routed href already has its one fragment
    // spent on the route itself, so a second `#t=` would just be inert
    // characters inside it. `?t=` is the hash route's own query string.
    expect(expandReferences('[[src:keynote@252]]', projectId)).toContain('?t=252')
  })

  it('carries a range offset', () => {
    expect(expandReferences('[[src:keynote@252-310]]', projectId)).toContain('?t=252,310')
  })

  it.each([
    ['[[src:]]', 'empty id'],
    ['[[src:a b]]', 'space in id'],
    ['[[src:../../etc/passwd]]', 'traversal'],
    ['[[src:x"onmouseover=y]]', 'quote breaking out of the attribute'],
    ['[[src:x@notanumber]]', 'non-integer offset'],
    ['[[src:x@-5]]', 'negative offset'],
  ])('renders %s as literal text (%s)', (input) => {
    const out = expandReferences(input, projectId)
    expect(out).toBe(input)
    expect(out).not.toContain('<a')
  })

  it('leaves a reference inside a code fence alone', () => {
    // A code block showing the syntax is documentation, not a link. Fails if
    // the pre-pass regexes the whole string without tracking fences.
    const source = '```\n[[src:keynote@252]]\n```'
    expect(expandReferences(source, projectId)).toBe(source)
  })

  it('leaves a reference in inline code alone', () => {
    expect(expandReferences('`[[src:keynote]]`', projectId)).toBe('`[[src:keynote]]`')
  })

  it('does not touch text with no references', () => {
    expect(expandReferences('nothing to see here', projectId)).toBe('nothing to see here')
  })

  it('never interpolates the id into the href unescaped', () => {
    // The id charset already forbids `<`/`>`/`"`, but this pins the promise at
    // the level the security argument is made at: the href comes from
    // encodeURIComponent(id), not from splicing model text into a string.
    const out = expandReferences('[[src:a.b_c-9]]', projectId)
    expect(out).toContain('href="#/p/' + projectId + '/doc/a.b_c-9"')
  })
})

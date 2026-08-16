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

  it('runs an unclosed fence to the end of the input, per CommonMark', () => {
    // Found in review: with only the closed-fence alternative, an unclosed
    // ``` falls through to the inline-code alternative (which eats two of
    // the three backticks as an empty span), and the reference inside gets
    // scanned as ordinary text and turned into a live link -- exactly the
    // guarantee this function exists to give code blocks. CommonMark's own
    // rule for an unterminated fence is that it runs to end of input.
    const source = '```\n[[src:keynote@252]]'
    expect(expandReferences(source, projectId)).toBe(source)
  })

  it('leaves everything after an unclosed fence alone too', () => {
    const source = '```\n[[src:keynote@252]]\nstill fenced [[src:other]]'
    expect(expandReferences(source, projectId)).toBe(source)
  })

  it('leaves a reference inside a markdown link label alone', () => {
    // Transforming this would nest an <a> the pre-pass built inside the <a>
    // `marked` builds for the surrounding [label](url) -- invalid markup.
    // The lookaround is same-line and single-level (see references.ts); this
    // pins the bounded case it actually catches.
    const source = 'see [context [[src:keynote@252]] here](https://example.com)'
    expect(expandReferences(source, projectId)).toBe(source)
  })

  it('does not touch text with no references', () => {
    expect(expandReferences('nothing to see here', projectId)).toBe('nothing to see here')
  })

  it('links a fetch_media id, which contains a colon', () => {
    // fetch_media.py mints ids as f"fetch:{digest}" -- ID_CHARS excluded `:`
    // until this was found in review, so every source the agent acquires
    // through its own fetch tool had an id the parser silently rejected: a
    // reference to one rendered as literal text, no error, nothing to grep
    // for but the visible `[[src:...]]` itself.
    const id = 'fetch:9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08'
    expect(expandReferences(`[[src:${id}]]`, projectId)).toContain(
      'href="#/p/' + projectId + '/doc/' + encodeURIComponent(id) + '"',
    )
  })

  it('never interpolates the id into the href unescaped', () => {
    // The id charset already forbids `<`/`>`/`"`, but this pins the promise at
    // the level the security argument is made at: the href comes from
    // encodeURIComponent(id), not from splicing model text into a string.
    const out = expandReferences('[[src:a.b_c-9]]', projectId)
    expect(out).toContain('href="#/p/' + projectId + '/doc/a.b_c-9"')
  })
})

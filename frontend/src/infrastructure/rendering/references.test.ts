import { describe, expect, it } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { renderMarkdown } from './markdown.ts'
import { expandReferences } from './references.ts'

const projectId = ProjectId('proj-1')

describe('expandReferences', () => {
  it('links a bare source reference', () => {
    expect(expandReferences('see [[src:wiki-trajan]] for more', projectId)).toContain(
      'href="#/p/' + projectId + '/doc/wiki-trajan"',
    )
  })

  it('shows a number, not the id', () => {
    // The defect this replaced: a fifty-character slug printed inline, in
    // monospace, mid-sentence. Fails if the anchor's text node is the id.
    const out = expandReferences('see [[src:wiki-trajan]] for more', projectId)
    expect(out).toContain('>1</a>')
    expect(out).not.toContain('>wiki-trajan</a>')
  })

  it('keeps the id readable without a click, in title and aria-label', () => {
    // The module's promise is that a reference stays reportable and greppable.
    // The id leaving the text node would break that for the *valid* case --
    // the title is what keeps it, and the aria-label is what stops a bare
    // numeral being read aloud as a stray digit.
    const out = expandReferences('[[src:wiki-trajan]]', projectId)
    expect(out).toContain('title="wiki-trajan"')
    expect(out).toContain('aria-label="Source 1: wiki-trajan"')
  })

  it('gives a repeated id the same number and a new id the next one', () => {
    const out = expandReferences('[[src:a]] [[src:b]] [[src:a]]', projectId)
    expect(out.match(/>(\d+)<\/a>/g)).toEqual(['>1</a>', '>2</a>', '>1</a>'])
  })

  it('numbers an id by its source, not by its offset', () => {
    // Two moments in one recording are one source. Fails if the counter is
    // keyed on the whole match rather than on the id.
    const out = expandReferences('[[src:keynote@10]] [[src:keynote@99]]', projectId)
    expect(out.match(/>(\d+)<\/a>/g)).toEqual(['>1</a>', '>1</a>'])
  })

  it('restarts numbering on each call', () => {
    // Per call is per markdown block, which is per lesson: a page showing a
    // unit and three lessons shows four independent sequences. Fails if the
    // counter is module-level state instead of a local.
    expect(expandReferences('[[src:b]]', projectId)).toContain('>1</a>')
    expect(expandReferences('[[src:c]]', projectId)).toContain('>1</a>')
  })

  it('carries a point offset as a query parameter on the hash route', () => {
    // Not a media fragment: a hash-routed href already has its one fragment
    // spent on the route itself, so a second `#t=` would just be inert
    // characters inside it. `?t=` is the hash route's own query string.
    expect(expandReferences('[[src:keynote@252]]', projectId)).toContain('?t=252')
  })

  it('carries a range offset as its start, in the form parseSeekSeconds accepts', () => {
    // `expandReferences` used to emit `?t=252,310` for a range, and
    // `parseSeekSeconds` (routes.ts) reads one number with `Number(raw)` --
    // `Number('252,310')` is `NaN`, so that URL seeked nowhere. A range
    // reference now collapses to its start, the same shape a point offset
    // produces, so the two ends of this round trip agree.
    const html = expandReferences('[[src:keynote@252-310]]', projectId)
    expect(html).toContain('?t=252"')
    expect(html).not.toContain(',')
    expect(html).not.toContain('310')
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

  it('survives the sanitiser that runs over it, tags and attributes both', () => {
    // The two halves of this pipeline are in different files with different
    // allow-lists, and `content.tsx` is the only place they meet. Neither
    // half's own tests can see the join: `expandReferences` emitting a `<sup>`
    // that `ALLOWED_TAGS` omits, or an `aria-label` that `ALLOWED_ATTR` omits,
    // would be stripped here with nothing raised and no test red. Fails if
    // either allow-list is narrowed back.
    const html = renderMarkdown(expandReferences('a claim [[src:wiki-trajan]]', projectId))
    expect(html).toContain('<sup')
    expect(html).toContain('aria-label="Source 1: wiki-trajan"')
    expect(html).toContain('title="wiki-trajan"')
    expect(html).toContain('href="#/p/' + projectId + '/doc/wiki-trajan"')
  })

  it('never interpolates the id into the href unescaped', () => {
    // The id charset already forbids `<`/`>`/`"`, but this pins the promise at
    // the level the security argument is made at: the href comes from
    // encodeURIComponent(id), not from splicing model text into a string.
    const out = expandReferences('[[src:a.b_c-9]]', projectId)
    expect(out).toContain('href="#/p/' + projectId + '/doc/a.b_c-9"')
  })
})

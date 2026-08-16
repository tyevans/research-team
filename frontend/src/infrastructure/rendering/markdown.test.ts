import { describe, expect, it } from 'vitest'

import { renderMarkdown } from './markdown.ts'

/** The one place in the application that turns untrusted text into markup.
 *
 * Everything rendered through it is model- or tool-authored: file contents, an
 * assistant's reply, a lesson's prose. These tests are the contract that makes
 * that safe, and they are deliberately adversarial rather than illustrative. */
describe('renderMarkdown — sanitisation', () => {
  it('strips a script tag', () => {
    const html = renderMarkdown('hello <script>alert(1)</script> world')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('alert(1)')
  })

  it('strips inline event handlers', () => {
    const html = renderMarkdown('<div onclick="alert(1)">click</div>')
    expect(html).not.toContain('onclick')
  })

  it('strips an img with an onerror payload', () => {
    const html = renderMarkdown('<img src=x onerror="alert(1)">')
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('<img')
  })

  it('strips an iframe', () => {
    const html = renderMarkdown('<iframe src="https://example.com"></iframe>')
    expect(html).not.toContain('<iframe')
  })

  it('does not execute a javascript: link — it keeps the text and drops the href', () => {
    const html = renderMarkdown('[click me](javascript:alert(1))')
    expect(html).not.toContain('javascript:')
    expect(html).toContain('click me')
    expect(html).toContain('md-link-inert')
  })

  it('drops a data: URI the same way', () => {
    const html = renderMarkdown('[x](data:text/html;base64,PHNjcmlwdD4=)')
    expect(html).not.toContain('data:text/html')
    expect(html).toContain('md-link-inert')
  })

  it('keeps an http link, and opens it safely', () => {
    const html = renderMarkdown('[docs](https://example.com/a)')
    expect(html).toContain('href="https://example.com/a"')
    expect(html).toContain('rel="noopener noreferrer"')
    expect(html).toContain('target="_blank"')
  })

  it('keeps an in-app hash-route link, without the external-link decoration', () => {
    // Exercises the same hook a `[[src:...]]` reference relies on
    // (`content.tsx` expands one into exactly this href shape before this
    // function ever sees the source) — written against raw markdown here
    // because that hook has no other coverage of the safe, non-http case.
    const html = renderMarkdown('[keynote](#/p/1/doc/keynote?t=252)')
    expect(html).toContain('href="#/p/1/doc/keynote?t=252"')
    expect(html).not.toContain('target="_blank"')
    expect(html).not.toContain('rel="noopener')
    // Distinct from an external `.md-link`, not reused outright — see the
    // class comment in markdown.css.
    expect(html).toContain('md-link-internal')
  })

  // Guards against the widened hash-route rule swallowing this case: '#'
  // alone isn't the distinguishing feature, '#/' -- the leading slash -- is.
  // A scheme this hook does not know about must still lose its href, exactly
  // as it did before the hash-route case existed.
  it('still drops an unknown scheme once #/ hrefs are allowed', () => {
    const html = renderMarkdown('[x](weird-scheme:something)')
    expect(html).not.toContain('weird-scheme:')
    expect(html).toContain('md-link-inert')
  })

  it('keeps a mailto link', () => {
    const html = renderMarkdown('<mailto:a@b.com>')
    expect(html).toContain('href="mailto:a@b.com"')
  })
})

describe('renderMarkdown — coverage the hand-rolled renderer did not have', () => {
  it('renders a fenced code block without interpreting what is inside it', () => {
    const html = renderMarkdown('```js\nconst a = **not bold**\n```')
    expect(html).toContain('<code')
    expect(html).not.toContain('<strong>')
  })

  it('renders a GFM table', () => {
    const html = renderMarkdown('| a | b |\n| - | - |\n| 1 | 2 |')
    expect(html).toContain('<table>')
    expect(html).toContain('<th>')
  })

  it('renders a nested list', () => {
    const html = renderMarkdown('- one\n  - two\n- three')
    expect(html.match(/<ul>/g)).toHaveLength(2)
  })

  it('renders a task list', () => {
    const html = renderMarkdown('- [x] done\n- [ ] todo')
    expect(html).toContain('type="checkbox"')
  })

  it('renders strikethrough, which GFM has and the old renderer only half did', () => {
    expect(renderMarkdown('~~gone~~')).toContain('<del>')
  })

  it('escapes text that merely looks like markup', () => {
    const html = renderMarkdown('a < b && c > d')
    expect(html).toContain('&lt;')
    expect(html).toContain('&gt;')
  })

  it('is empty for empty input rather than throwing', () => {
    expect(renderMarkdown('')).toBe('')
  })
})

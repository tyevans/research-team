// `node:fs`'s sync API rather than `node:fs/promises`, matching `theme.test.ts`
// and `stacking.test.ts`, and for the reason stated there: eslint type-checks
// this directory against a program that resolves `node:fs` but not the
// `node:fs/promises` subpath.
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

import { compareStylesheets } from './check-deleted.mjs'

/** That the stylesheet manifest stays a decision made in a diff.
 *
 * **What it guards.** The spec's phase 5 planned to port 22 stylesheets to
 * Tailwind utilities file by file. That plan was replaced on 2026-08-10 with a
 * policy — new and rewritten surfaces use utilities, existing stylesheets are
 * deleted and never ported — which until now lived in nobody's file. The
 * manifest in `check-deleted.mjs` is that policy made checkable, and this is
 * what fails if the manifest and the directory drift apart.
 *
 * **Why a unit test against an exported function rather than spawning the
 * script.** A subprocess would assert on an exit code and a string, which
 * tells you the script failed and not which half was wrong; and it makes the
 * build test suite fork a node process that walks all of `src/`, which is
 * slower than the assertion is worth. The comparison is the part that can be
 * wrong silently — a filter written the wrong way round reports every present
 * file as added and still exits non-zero, looking like a working check — so it
 * is exported and tested directly, the same split `mutate.test.ts` makes for
 * `classify`. The script's own guard (`process.argv[1]?.endsWith(...)`) is what
 * keeps that import from running the CLI, and if it regressed this file would
 * not merely fail, it would exit the test process.
 *
 * The first test is the one that fires on real drift; the rest pin the
 * comparison's direction. Proved red by adding `src/styles/zz-scratch.css`,
 * which fails the first case with `zz-scratch.css` named as added, and by
 * inverting each filter in `compareStylesheets`, which fails the last two.
 */
describe('the stylesheet manifest', () => {
  const STYLES = fileURLToPath(new URL('../src/styles', import.meta.url))

  /** Read out of the script's source rather than imported, because the array is
   *  the artefact under test: a manifest that this test could not see would be
   *  free to be generated from the directory it is supposed to be frozen
   *  against, and then it would agree with anything. */
  const manifest = (() => {
    const source = readFileSync(
      fileURLToPath(new URL('./check-deleted.mjs', import.meta.url)),
      'utf8',
    )
    const block = /const STYLESHEETS = \[([^\]]*)\]/.exec(source)
    expect(block, 'STYLESHEETS is no longer a literal array in check-deleted.mjs').not.toBeNull()
    // `flatMap` rather than `map`, because a capture group is `string |
    // undefined` to the type checker even when the pattern cannot match without
    // it. Dropping the empty case is honest here: an entry that did not capture
    // is not a filename and has no business in the manifest either way.
    return [...(block?.[1] ?? '').matchAll(/'([^']+)'/g)].flatMap((match) =>
      match[1] === undefined ? [] : [match[1]],
    )
  })()

  it('lists exactly the stylesheets that are on disk', () => {
    const present = readdirSync(STYLES).filter((name) => name.endsWith('.css'))
    // Both directions in one assertion on purpose: the message a reader gets
    // should name the file, and `toEqual` on two sorted arrays does that
    // better than two separate emptiness checks would.
    expect(compareStylesheets(present, manifest)).toEqual({ added: [], removed: [] })
  })

  it('ignores the browser tests and screenshots that share the directory', () => {
    // Not a restatement of the filter above: it asserts that the *directory*
    // holds non-CSS entries, so that a future reader who deletes the
    // `.endsWith('.css')` guard as redundant finds out here rather than by
    // failing the freeze on a new browser test.
    expect(readdirSync(STYLES).some((name) => !name.endsWith('.css'))).toBe(true)
  })

  it('reports a stylesheet that is on disk and not in the manifest', () => {
    expect(compareStylesheets(['a.css', 'b.css'], ['a.css'])).toEqual({
      added: ['b.css'],
      removed: [],
    })
  })

  it('reports a stylesheet that is in the manifest and not on disk', () => {
    expect(compareStylesheets(['a.css'], ['a.css', 'b.css'])).toEqual({
      added: [],
      removed: ['b.css'],
    })
  })
})

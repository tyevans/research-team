// `node:fs`'s sync API rather than `node:fs/promises`, matching
// `theme.test.ts` and `check-deleted.test.ts`, and for the reason stated
// there: eslint type-checks this directory against a program that resolves
// `node:fs` but not the `node:fs/promises` subpath.
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

import { findSilentUtilities } from './check-tailwind.mjs'

/** That a Tailwind utility generating no CSS fails the build.
 *
 * **Why a unit test against the exported comparison rather than spawning the
 * script.** The same split `check-deleted.test.ts` makes and for the same
 * reason: a subprocess asserts on an exit code, which tells you the check
 * failed and not which half was wrong. The part that can be wrong *silently*
 * is the comparison — a filter written the wrong way round reports every
 * emitted utility as missing and still exits non-zero, looking like a working
 * check — so it is exported and tested directly. The script's own
 * `process.argv[1]?.endsWith(...)` guard is what keeps this import from
 * running the CLI; if that regressed, this file would not merely fail, it
 * would exit the test process.
 *
 * The end-to-end half is not covered here and is covered by the gate itself:
 * `npm run verify` runs `build` and then `check-tailwind`, so a real
 * regression fails CI whether or not this file exists.
 *
 * Proved red three ways before being trusted green: by inverting the filter in
 * `findSilentUtilities`, by renaming `--spacing-0` in `theme.css` and
 * rebuilding (which reports `m-0` at seven sites and `p-0` at three, with the
 * line numbers the defect was originally filed against), and by restoring
 * `py-1.5` in `Menu.tsx`. */
describe('the silent-utility comparison', () => {
  const used = new Map([
    ['m-0', new Set(['session/Approvals.tsx:119'])],
    ['p-3', new Set(['session/GateReview.tsx:84'])],
  ])

  it('reports a utility the stylesheet has no rule for', () => {
    expect(findSilentUtilities(used, (name) => name !== 'm-0')).toEqual([
      { name: 'm-0', where: ['session/Approvals.tsx:119'] },
    ])
  })

  it('reports nothing when every utility emits', () => {
    expect(findSilentUtilities(used, () => true)).toEqual([])
  })

  it('names every site a silent utility is written at, sorted', () => {
    // The sites are the actionable half. A check that says "`m-0` does
    // nothing" without saying where leaves the reader to grep, and the whole
    // point is that this defect is invisible to a reader who is not already
    // looking for it.
    const many = new Map([['m-0', new Set(['b.tsx:2', 'a.tsx:9', 'a.tsx:1'])]])
    expect(findSilentUtilities(many, () => false)[0]?.where).toEqual([
      'a.tsx:1',
      'a.tsx:9',
      'b.tsx:2',
    ])
  })
})

/** That the check is actually wired into the gate.
 *
 * A check nobody runs is a comment. `check-size.mjs` and `check-deleted.mjs`
 * are both in the `verify` chain and this one has to be too — and it has to
 * come *after* `build`, because it reads the built stylesheet and would
 * otherwise answer about whatever was on disk from last time.
 *
 * Proved red by moving `check:tailwind` ahead of `build` in the chain. */
describe('the verify chain', () => {
  const scripts = JSON.parse(
    readFileSync(fileURLToPath(new URL('../package.json', import.meta.url)), 'utf8'),
  ).scripts as Record<string, string>

  it('runs the check, after the build it reads', () => {
    const chain = scripts.verify ?? ''
    expect(chain).toContain('check:tailwind')
    expect(chain.indexOf('run build')).toBeLessThan(chain.indexOf('check:tailwind'))
  })
})

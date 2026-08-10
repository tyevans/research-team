import { describe, expect, it } from 'vitest'

import { classify } from './mutate.mjs'

/** The one part of the mutation harness that can be wrong silently.
 *
 * Applying a mutation and restoring it is either right or obviously broken.
 * *Reading the result* is where the harness lied twice: a mutant that failed
 * to compile made vitest fail at file level, which emits no
 * `FAIL … > test name` line, so a parser counting per-test failures saw zero
 * and reported "survived". That is the worst available answer — it does not
 * just fail to inform, it points the reader at assertions that already exist
 * and says they are missing.
 *
 * So the classifier is a pure function and these are its tests. Proved red by
 * removing the `unparsed` branch, at which point the compile-error case
 * classifies as `survived` — reproducing the original defect exactly.
 */

const KILLED = `
 ❯ |app| src/presentation/entity/EntityStatus.test.tsx (5 tests | 1 failed)
 FAIL  |app| src/presentation/entity/EntityStatus.test.tsx > paints a failure with the failing tone
      Tests  1 failed | 44 passed (45)
`

const SURVIVED = `
 RUN  v4.1.10
 Test Files  6 passed (6)
      Tests  45 passed (45)
`

/** What a syntax error in a mutant actually produces: a suite that never ran,
 *  with no per-test line anywhere in the output. */
const UNPARSED = `
 ❯ src/presentation/entity/EntityStatus.tsx (0 test)
⎯⎯⎯ Failed Suites 1 ⎯⎯⎯
 FAIL  src/presentation/entity/EntityStatus.tsx [ src/presentation/entity/EntityStatus.tsx ]
Error: Transform failed with 1 error: Unexpected token
`

describe('classify', () => {
  it('reports the tests that killed a mutant, by name', () => {
    const { verdict, killedBy } = classify(KILLED)
    expect(verdict).toBe('killed')
    expect(killedBy).toEqual(['paints a failure with the failing tone'])
  })

  it('reports a mutant nothing caught', () => {
    expect(classify(SURVIVED).verdict).toBe('survived')
  })

  it('never reports a mutant that did not compile as survived', () => {
    // The assertion this file exists for. `UNPARSED` contains no
    // `FAIL … > name` line and no failing-test count, so every naive reading
    // of it says "nothing failed".
    expect(classify(UNPARSED).verdict).toBe('unparsed')
    expect(classify(UNPARSED).verdict).not.toBe('survived')
  })

  it('does not mistake output it cannot read for a passing run', () => {
    // An empty or truncated run is unknown, not survived. Defaulting to
    // `survived` is the same class of mistake as the one above: it invents a
    // finding out of an absence of information.
    expect(classify('').verdict).toBe('unknown')
  })

  it('prefers killed over survived when a run reports both', () => {
    // vitest prints the passing count alongside the failures. A classifier
    // checking "N passed" before checking for failures would call this run a
    // survival.
    expect(classify(KILLED).verdict).toBe('killed')
  })
})

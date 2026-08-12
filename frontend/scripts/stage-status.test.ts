// `node:fs`'s sync API rather than `node:fs/promises`, for the reason
// `theme.test.ts` and `stacking.test.ts` both give: eslint type-checks this
// directory against a program that resolves `node:fs` but not the
// `node:fs/promises` subpath.
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

import type { StageStatus } from '../src/domain/project/course.ts'

/** That every stage status the console can hold is a status it can draw.
 *
 * `StageRail` renders `stage.status` straight into two class names --
 * `rail-${status}` on the dot and, through `Chip`, `chip-${status}` on the
 * label. So the union in `course.ts` and the rules in `course.css` are one
 * vocabulary written twice, in two languages, with nothing between them.
 *
 * They had already drifted, which is what this closes rather than predicts.
 * The type read `'done' | 'current' | 'todo' | (string & {})` while the
 * stylesheet was written for `done`, `current`, `upcoming` and `unknown` --
 * the four the server actually sends. Both were internally consistent, both
 * compiled, and the two names in the type that no rule matched (`todo`, plus
 * whatever the escape hatch admitted) drew an unstyled chip claiming a state
 * that did not exist. Nothing could have reported that: TypeScript does not
 * read CSS, and jsdom applies no stylesheet, so a class matching no rule looks
 * exactly like a class matching one.
 *
 * The list below is duplicated from the union deliberately -- a test deriving
 * its expectation from the thing under test asserts nothing. `STATUSES` is
 * typed as `StageStatus[]`, so widening the union without extending this list
 * fails to compile, and extending this list without adding the two rules fails
 * here. Adding a fifth status therefore costs a stylesheet edit, which is the
 * price it should cost.
 *
 * Deliberately not checked: what the rules *say*. That is a design decision
 * per status and belongs in the browser, not in a regex.
 */
const STATUSES: StageStatus[] = ['done', 'current', 'upcoming', 'unknown']

const css = readFileSync(
  fileURLToPath(new URL('../src/styles/course.css', import.meta.url)),
  'utf8',
)

describe('stage status', () => {
  it.each(STATUSES)('%s has a dot rule and a chip rule', (status) => {
    expect(css).toContain(`.rail-${status} {`)
    expect(css).toContain(`.chip-${status} {`)
  })
})

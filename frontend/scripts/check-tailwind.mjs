#!/usr/bin/env node
/* That a Tailwind utility this codebase writes actually generates a rule.
 *
 * `theme.css` omits Tailwind's default theme on purpose, and says why: with it
 * out, "the only colours, sizes and spacings that exist are the ones declared
 * below, and a typo is a class that generates no CSS rather than a second
 * palette". That is the right trade. What the same file already admits, twice,
 * is the cost -- "it will fail silently, which is the bad way to fail" -- and
 * the failure it predicted duly happened: `m-0` and `p-0` resolve through the
 * *base* `--spacing` step rather than the `--spacing-1..6` keys this project
 * declares, so they emitted nothing and five shipped elements silently kept
 * their user-agent margins for as long as anyone had been reading them.
 *
 * A missing utility has no error, no warning and no visual tell -- the element
 * simply looks like an element nobody styled, which is indistinguishable from
 * one nobody meant to style. It is exactly the class of defect this repository
 * answers with a build-failing check rather than a note: `check-size.mjs` for
 * the bundle, `check-deleted.mjs` for the migration promise, `apply_schema`'s
 * column reconciliation for the read models.
 *
 * **What it does not do, and why it is narrow.** It does not check every class
 * name. It checks names matching a prefix in `FAMILIES` below, because
 * distinguishing a Tailwind utility from one of this project's own class names
 * (`sub`, `chip`, `row`) is not decidable from the string, and a check that
 * fires on correct code is a check somebody turns off -- `check-deleted.mjs`
 * makes the same argument about its own patterns and narrows them for the same
 * reason. So this is a list that grows when a family bites, and it starts as
 * the spacing families because those are the ones that have.
 *
 * The honest gap that leaves: a *colour* or *breakpoint* typo is still silent.
 * Breakpoints in particular are the next one to fail this way -- `theme.css`
 * declares none, so `md:` generates nothing today -- and they are covered here
 * only when they prefix a family below.
 */
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath, URL } from 'node:url'

const SRC = fileURLToPath(new URL('../src', import.meta.url))
const ASSETS = fileURLToPath(
  new URL('../../research_team/interfaces/web/static/assets', import.meta.url),
)

/** Utility prefixes whose bare-number form resolves through Tailwind's spacing
 *  scale. Every one of these is `calc(var(--spacing) * N)` for a step with no
 *  explicit `--spacing-N` key, which is the whole defect. Written out rather
 *  than pattern-matched on `-\d` because `border-2`, `z-10` and `opacity-50`
 *  are all bare numbers on scales that have nothing to do with spacing. */
const FAMILIES = `
  m mx my ms me mt mr mb ml
  p px py ps pe pt pr pb pl
  gap gap-x gap-y space-x space-y
  inset inset-x inset-y start end top right bottom left
  size w h min-w min-h max-w max-h basis
  translate translate-x translate-y indent
`
  .trim()
  .split(/\s+/)

/** A candidate is `[-]family-value`, optionally behind variants (`hover:`,
 *  `md:`, `data-[open]:`). The value half is left deliberately loose: an
 *  arbitrary value, a fraction, a keyword and a bare step all have to reach the
 *  emission check, because "is this a real value" is the question the built
 *  stylesheet answers and this regex must not pre-empt. */
const CANDIDATE = new RegExp(`^-?(?:${FAMILIES.join('|')})-[^\\s]+$`)

/** Values that are not utilities and never emit: `w-full` is one, but so is a
 *  string like `p-` from a truncated template. A token containing any of these
 *  came from an interpolation, a selector or prose, not from a `className`. */
const NOT_A_CLASS = /[${}<>()\\/;=]/

const sources = []
const walk = (dir) => {
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry)
    if (statSync(path).isDirectory()) walk(path)
    else if (/\.tsx?$/.test(path) && !/\.(test|stories)\.tsx?$/.test(path)) sources.push(path)
  }
}
walk(SRC)

/** String literals, with comments stripped first.
 *
 *  Stripping comments is not tidiness -- this file's own subject matter gets
 *  discussed in prose, and `AutonomyAllowAll.tsx` has a paragraph containing
 *  the words `m-0` and `p-0` in backticks that would otherwise be reported as
 *  four defects. Tailwind's scanner does read those, but a name it generates
 *  from a comment is one nothing applies, so it is not this check's business.
 *
 *  Literals rather than `className=` attributes specifically, because a class
 *  name is as often assembled in a `cva` table or a `clsx` argument two
 *  functions away as written inline. */
const candidates = new Map()
for (const file of sources) {
  // The block-comment replacement keeps the newlines it removes. Collapsing a
  // 30-line comment to nothing shifts every line number after it, which makes
  // the report point at the wrong line -- checked, and it named
  // `Approvals.tsx:73` for a `m-0` on line 119.
  const text = readFileSync(file, 'utf8')
    .replace(/\/\*[\s\S]*?\*\//g, (comment) => comment.replace(/[^\n]/g, ''))
    .replace(/(^|[^:])\/\/[^\n]*/g, '$1')
  const lines = text.split('\n')
  lines.forEach((line, index) => {
    for (const match of line.matchAll(/(['"`])((?:(?!\1)[^\\])*)\1/g)) {
      for (const token of match[2].split(/\s+/)) {
        const bare = token.split(':').pop()
        if (!token || NOT_A_CLASS.test(token) || !CANDIDATE.test(bare)) continue
        if (!candidates.has(token)) candidates.set(token, new Set())
        candidates.get(token).add(`${relative(SRC, file)}:${String(index + 1)}`)
      }
    }
  })
}

/** The built stylesheet, or a message naming the command that produces it.

    **Read here rather than at module scope, and that is load-bearing.** This
    file is imported by `check-tailwind.test.ts` to unit-test
    `findSilentUtilities`, and `npm run verify` runs `test:coverage` *before*
    `build` -- so at import time during a test run the stylesheet legitimately
    does not exist yet. With the read at module scope the `process.exit(1)`
    below fired during the import and killed the vitest process, reported as
    "process.exit unexpectedly called with 1" against a suite that had nothing
    to do with it. That was invisible while `static/` was committed, because
    the file was then always present; untracking it made every run of the
    frontend job fail. `check-tailwind.test.ts`'s own docstring predicted this
    shape and blamed the `process.argv[1]` guard -- the guard was fine, the
    filesystem work simply sat outside it.

    `index.css`, exactly, rather than the `index-*.css` glob this arrived
    with. The glob was written against hashed filenames, which this build does
    not produce, so it matched nothing and exited 1 before reading anything.
    Naming the file outright is also the stronger check: the glob existed to
    fail on a *second* stylesheet left beside the fresh one, and with a stable
    name there is only ever one, because a stale build overwrites rather than
    accumulates. */
const readStylesheet = () => {
  const stylesheet = join(ASSETS, 'index.css')
  if (!existsSync(stylesheet)) {
    console.error(
      `No ${stylesheet}. Run \`npm run build\` first -- this check reads the built stylesheet, ` +
        'and has nothing to say about a tree that has not been built.',
    )
    process.exit(1)
  }
  return readFileSync(stylesheet, 'utf8')
}

/** CSS escapes every character that cannot appear bare in an identifier, which
 *  is why `.m-[0px]` is written `.m-\[0px\]` and `.py-1.5` is `.py-1\.5`. A
 *  grep that forgets this reports every arbitrary value as missing. */
const escape = (name) => name.replace(/[.[\]/():%!#,*+>~^$@&?=|'"`{} ]/g, (char) => `\\${char}`)

/** Whether a rule exists for this class, against `css`. The trailing character
 *  has to be checked: a substring search for `.p-3` also finds `.p-32`, and
 *  one for `.m-0` finds `.m-0\.5`. */
const emitsARuleIn = (css) => (name) => {
  const selector = `.${escape(name)}`
  for (let at = css.indexOf(selector); at !== -1; at = css.indexOf(selector, at + 1)) {
    const next = css[at + selector.length]
    if (next !== undefined && !/[-\w\\]/.test(next)) return true
  }
  return false
}

export const findSilentUtilities = (used, emits) =>
  [...used.entries()]
    .filter(([name]) => !emits(name))
    .map(([name, where]) => ({ name, where: [...where].sort() }))
    .sort((a, b) => a.name.localeCompare(b.name))

if (process.argv[1]?.endsWith('check-tailwind.mjs')) {
  const silent = findSilentUtilities(candidates, emitsARuleIn(readStylesheet()))
  for (const { name, where } of silent) {
    console.log(`✗ ${name} generates no rule — ${where.join(', ')}`)
  }
  if (silent.length) {
    console.error(
      (silent.length === 1
        ? '\n1 utility name in src/ generates no CSS.\n'
        : `\n${String(silent.length)} utility names in src/ generate no CSS.\n`) +
        'This is silent: the element keeps whatever the user agent gave it.\n' +
        'Either the value is off this project’s scale and belongs on it, or the\n' +
        'step it needs is missing from `theme.css` and should be declared there.',
    )
    process.exit(1)
  }
  console.log(
    `· ${String(candidates.size)} spacing-family utilities in src/, all of them emitting a rule.`,
  )
}

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
 * reason. So this is a list that grows when a family bites, and it started as
 * the spacing families because those were the ones that had.
 *
 * **The colour families bit next, and this is where they were added.** The
 * paragraph above used to end by naming a colour typo as "the honest gap", and
 * the gap was occupied the whole time it said so. Measured on 2026-08-27, by
 * adding the families below and running against `origin/main`: `text-fg-muted`
 * at seven sites, `text-k-warning` at two, `text-danger`, `bg-bg-muted`,
 * `bg-black` and `rounded-sm` at one each -- plus a bare `rounded`, which is
 * not a static utility in this build because `--radius` is not declared. Every
 * one of them was in the attribute and absent from the bundle, and the two
 * radius ones had been drawing square corners for as long as they had shipped.
 *
 * **Which families are checked, and which are deliberately not.** Checked:
 * the spacing families, and the appearance families whose every value comes
 * from a token declared in `theme.css` -- radius, colour on `text`/`bg`/
 * `border`/`ring`/`outline`/`fill`/`stroke`/`divide`/`accent`/`caret`/
 * `decoration`, and `shadow`. That set was run over the whole of `src/` before
 * being committed and produced no false positive, which is the bar: a family
 * goes on this list once somebody has watched it stay quiet on correct code.
 *
 * **`font-*` was the reason this list had a "not checked" section, and it is
 * now checked.** The paragraph that used to sit here recorded the defect and
 * declined to fix it: `font-medium`, `font-semibold` and `font-normal`
 * generated nothing across **29 sites** (16, 12 and 1), because font weights
 * live in Tailwind's default theme and `theme.css` omits it -- so the console
 * had no bold text anywhere it thought it had some. It declined because the
 * only fix was to declare `--font-weight-*`, and declaring a token to make an
 * existing class valid is growing the palette to bless a typo, which is the
 * move `theme.css` exists to refuse.
 *
 * That reasoning was right and its conclusion had an expiry date, which is the
 * commit that decides the type scale on purpose. `theme.css` now declares three
 * weights -- normal, medium, semibold, and no more -- with the argument for
 * each, so the 29 sites resolve and `font-bold` is still a name that generates
 * nothing. Turning the family on here is what stops that being reversible by
 * accident: a fourth weight now has to be declared deliberately or the class
 * that reaches for it fails the build.
 *
 * Watched on correct code before being committed, which is this list's bar: it
 * reports nothing across `src/`. `font-mono` and `font-sans` pass because
 * `--font-mono` and `--font-sans` are declared; that is the family's static
 * half and it was already emitting.
 *
 * Still not checked, and each for a stated reason rather than an oversight:
 *
 * - **Gradient stops (`from-*`, `via-*`, `to-*`).** `to-` in particular is a
 *   common prefix in ordinary strings, this console draws no gradients, and a
 *   family with nothing to catch is only a false-positive surface.
 * - **Breakpoints.** `theme.css` declares none, so `md:` generates nothing
 *   today. A variant is not a class name, so it is covered here only when it
 *   prefixes a family above -- `md:p-3` is caught, a bare `md:flex` is not.
 * - **Bare family names other than `rounded`.** `text`, `bg` and `font` alone
 *   are not utilities at all, so a string containing the word would be
 *   reported as a defect. `rounded` is the one worth the exception, because it
 *   reads as a complete class and silently is not.
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
 *  are all bare numbers on scales that have nothing to do with spacing.
 *
 *  Below them, the radius and colour families, which fail the same way for the
 *  other half of the same omission: no default theme means no `--radius-lg`
 *  and no `--color-red-500`, so `rounded-lg` and `bg-red-500` are names with
 *  no rule. Their static values (`rounded-full`, `outline-none`, `text-center`)
 *  are emitted by `utilities.css` regardless of the theme and so pass this
 *  check without being listed anywhere. */
const FAMILIES = `
  m mx my ms me mt mr mb ml
  p px py ps pe pt pr pb pl
  gap gap-x gap-y space-x space-y
  inset inset-x inset-y start end top right bottom left
  size w h min-w min-h max-w max-h basis
  translate translate-x translate-y indent
  rounded rounded-t rounded-r rounded-b rounded-l
  rounded-s rounded-e rounded-ss rounded-se rounded-ee rounded-es
  rounded-tl rounded-tr rounded-br rounded-bl
  text bg border border-t border-r border-b border-l border-x border-y
  ring ring-offset outline divide decoration accent caret
  fill stroke shadow inset-shadow drop-shadow text-shadow
  font
`
  .trim()
  .split(/\s+/)

/** Families that are also a complete utility name on their own. Only
 *  `rounded`: in a build with the default theme it is `border-radius: .25rem`
 *  from `--radius`, and with the theme omitted it is nothing at all --
 *  measured, `.rounded{` appears zero times in the built stylesheet, and
 *  `MediaProposalCard` had been drawing a square thumbnail because of it. The
 *  other families are not utilities bare (`text`, `bg`, `border` is a static
 *  width and needs no check), so listing them here would report English. */
const BARE = new Set(['rounded'])

/** A candidate is `[-]family-value`, optionally behind variants (`hover:`,
 *  `md:`, `data-[open]:`). The value half is left deliberately loose: an
 *  arbitrary value, a fraction, a keyword and a bare step all have to reach the
 *  emission check, because "is this a real value" is the question the built
 *  stylesheet answers and this regex must not pre-empt. */
const CANDIDATE = new RegExp(`^-?(?:${FAMILIES.join('|')})-[^\\s]+$|^(?:${[...BARE].join('|')})$`)

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
    `· ${String(candidates.size)} checked-family utilities in src/, all of them emitting a rule.`,
  )
}

// `node:fs`'s sync API rather than `node:fs/promises`, matching
// `build-config.test.ts`. Not a preference: eslint type-checks this directory
// against an inferred program (see `allowDefaultProject` in
// `eslint.config.js`), and that program resolves `node:fs` but not the
// `node:fs/promises` subpath, so the promise version lints as eight
// `no-unsafe-*` errors while type-checking cleanly under
// `tsconfig.node.json`. Reading two small files synchronously in a test costs
// nothing and keeps the two tools agreeing.
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

import { BREAKPOINTS, RAIL_WIDTH_PX } from '../src/presentation/layout/layout-tokens.ts'

/** That `theme.css` and `tokens.css` still say the same thing.
 *
 * `tokens.css` opens with the rule this file enforces: "a second literal hex
 * would be a second palette, discoverable only by looking at both". Phase 0
 * creates exactly that second literal, on purpose and temporarily -- the old
 * stylesheets read `var(--bg)` and Tailwind's utilities read `--color-bg`, and
 * during coexistence both have to exist.
 *
 * Duplication that a comment asks you not to break is the arrangement
 * `tokens.css` itself records catching twice. So this is the mechanical
 * version: every token that appears in both files must carry the same value,
 * and a change to one that is not made to the other fails here rather than
 * showing up as a chip that is the wrong green on one page.
 *
 * Proved red by changing `--color-accent` in `theme.css` by one hex digit.
 *
 * It lives in `scripts/` because it reads files off disk, which is what the
 * `build` vitest project exists for. Phase 5 deletes `tokens.css`'s `:root`
 * block, at which point this file has nothing left to compare and should go
 * with it. */

const read = (name: string) =>
  readFileSync(fileURLToPath(new URL(`../src/styles/${name}`, import.meta.url)), 'utf8')

/** Declarations from the first `:root`/`@theme` block, as a name -> value map.
 *  Comments are stripped first: both files are heavily commented and a `--x:`
 *  inside prose would otherwise read as a declaration. */
const declarations = (css: string, opener: RegExp): ReadonlyMap<string, string> => {
  const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const start = withoutComments.search(opener)
  if (start === -1) throw new Error(`no block matching ${String(opener)}`)
  const body = withoutComments.slice(start, withoutComments.indexOf('}', start))
  return new Map(
    Array.from(body.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g), (match) => [
      match[1]!,
      match[2]!.trim(),
    ]),
  )
}

/** `theme.css` has to spell some names differently, because Tailwind's
 *  namespaces are what turn a variable into a utility: a colour must be
 *  `--color-*` to yield `bg-*`, and the type scale must be `--text-*` to yield
 *  `text-*`. These are the renames, and listing them here rather than deriving
 *  them is deliberate -- a rename nobody wrote down is how the two files would
 *  drift while still passing a cleverer test. */
const RENAMED: Readonly<Record<string, string>> = {
  '--t-xs': '--text-xs',
  '--t-sm': '--text-sm',
  '--t-md': '--text-md',
  '--t-lg': '--text-lg',
  '--t-xl': '--text-xl',
  '--t-2xl': '--text-2xl',
  '--radius': '--radius-md',
  '--mono': '--font-mono',
  '--sans': '--font-sans',
  '--space-0': '--spacing-0',
  '--space-1': '--spacing-1',
  '--space-2': '--spacing-2',
  '--space-3': '--spacing-3',
  '--space-4': '--spacing-4',
  '--space-5': '--spacing-5',
  '--space-6': '--spacing-6',
}

/** Layout constants, not theme values, and kept out of `@theme` on purpose:
 *  there is no such thing as a `topbar-h` utility or a `z-overlay` one, and
 *  putting them in the theme block would offer both.
 *
 *  The z-scale in particular must not become a utility. Its whole value is
 *  that there are three levels and that every dismissable layer shares one of
 *  them; a `z-overlay` class is an invitation to write a fourth. */
const NOT_PORTED = new Set([
  '--topbar-h',
  '--rail-w',
  '--bp-wide',
  '--bp-narrow',
  '--bp-tight',
  '--z-sticky',
  '--z-overlay',
  '--z-toast',
])

/** Everything not renamed above is a colour and takes Tailwind's `--color-*`
 *  namespace; `--shadow-1` is already in a namespace Tailwind understands. */
const themeNameFor = (token: string) =>
  RENAMED[token] ?? (token === '--shadow-1' ? token : `--color-${token.slice('--'.length)}`)

describe('theme.css and tokens.css', () => {
  it('agree on the value of every token that was ported', () => {
    const tokens = declarations(read('tokens.css'), /:root\s*\{/)
    const theme = declarations(read('theme.css'), /@theme\s*\{/)

    const disagreements: string[] = []
    for (const [token, value] of tokens) {
      if (NOT_PORTED.has(token)) continue
      const themed = theme.get(themeNameFor(token))
      if (themed === undefined) {
        disagreements.push(
          `${token} is in tokens.css and has no ${themeNameFor(token)} in theme.css`,
        )
      } else if (themed !== value) {
        disagreements.push(`${token} is ${value} but ${themeNameFor(token)} is ${themed}`)
      }
    }

    expect(disagreements).toEqual([])
  })

  it('adds no value to the theme that the palette does not have', () => {
    const tokens = declarations(read('tokens.css'), /:root\s*\{/)
    const theme = declarations(read('theme.css'), /@theme\s*\{/)
    const ported = new Set(
      Array.from(tokens.keys())
        .filter((token) => !NOT_PORTED.has(token))
        .map(themeNameFor),
    )

    // The direction that matters less but is still worth holding: a token
    // invented in `theme.css` is a colour with no entry in the palette file
    // every existing stylesheet reads, which is the same drift from the other
    // end. Breakpoints will be the first legitimate exception -- when phase 5
    // adds them, they belong on this exemption list with a note, not silently.
    expect(Array.from(theme.keys()).filter((name) => !ported.has(name))).toEqual([])
  })
})

/** The layout constants exist twice for a reason neither language can avoid,
 *  so the agreement is checked rather than trusted.
 *
 *  A stylesheet cannot import a TypeScript constant and `matchMedia` cannot
 *  read a CSS custom property without `getComputedStyle`, which returns
 *  nothing under jsdom. So the numbers are written in both places. That is the
 *  arrangement `tokens.css` opens by warning about — and it is exactly what
 *  the console has today, unchecked: `34px` in a hook and twice in a
 *  stylesheet, and one breakpoint spelled `1180` in CSS and `1181` in
 *  JavaScript.
 *
 *  Proved red by changing `--bp-wide` to `1180px`, which is the specific
 *  historical drift this is aimed at. */
describe('the layout constants', () => {
  const tokens = () => declarations(read('tokens.css'), /:root\s*\{/)

  it('match the breakpoints the JavaScript asks matchMedia about', () => {
    const css = tokens()
    const disagreements = Object.entries(BREAKPOINTS)
      .map(([name, px]) => {
        const declared = css.get(`--bp-${name}`)
        return declared === `${String(px)}px`
          ? null
          : `--bp-${name} is ${String(declared)} in tokens.css and ${String(px)}px in layout-tokens.ts`
      })
      .filter((entry) => entry !== null)

    expect(disagreements).toEqual([])
  })

  it('match the rail width', () => {
    // `Split` writes the rail as `var(--rail-w)` rather than as a number, so
    // this pair is only consulted by code that has to compare widths. It is
    // held anyway: the number existing twice is the thing that goes wrong, not
    // the number being read twice.
    expect(tokens().get('--rail-w')).toBe(`${String(RAIL_WIDTH_PX)}px`)
  })

  it('keeps the z-scale to three levels', () => {
    // Not a style rule. Four values with one written-down ordering rule is
    // what the console has today, and the stylesheet contradicts the rule --
    // the agent dock's popover at 40 paints over an `aria-modal` backdrop at
    // 20. A fourth level is a decision to make deliberately, and this fails
    // until someone does.
    const scale = Array.from(tokens().keys()).filter((name) => name.startsWith('--z-'))
    expect(scale).toEqual(['--z-sticky', '--z-overlay', '--z-toast'])
  })

  /** A media query cannot read a custom property, so every `@media` prelude
   *  that names a breakpoint writes the number out. The two tests above hold
   *  `--bp-*` against `BREAKPOINTS`; this holds the *queries* against them,
   *  which is the third copy and the one that has already gone wrong once --
   *  `responsive.css` asks `max-width: 1180px` about the boundary
   *  `use-panes.ts` asked `min-width: 1181px` about.
   *
   *  Scoped to the two files the layout system owns. The rest of
   *  `responsive.css` still spells its boundaries the old way, on purpose:
   *  rewriting rules this phase does not otherwise touch would be a diff with
   *  no test behind it. Those are listed as unprotected rather than silently
   *  included.
   *
   *  Proved red by changing `layout.css`'s stacking query to 820px. */
  it('spells its media queries with the same numbers, in the files it owns', () => {
    const legal = new Set(Object.values(BREAKPOINTS).map((px) => `${String(px)}px`))
    const offenders = ['layout.css', 'responsive.css'].flatMap((name) =>
      Array.from(read(name).matchAll(/@media[^{]+/g))
        .flatMap((match) =>
          Array.from(match[0].matchAll(/(?:min-width:\s*|width\s*[<>]=?\s*)(\d+px)/g)),
        )
        .map((match) => match[1]!)
        .filter((px) => !legal.has(px))
        .map((px) => `${name} asks about ${px}, which is not a breakpoint`),
    )

    // `responsive.css`'s untouched rules still use the `max-width: N - 1`
    // spelling, which this pattern deliberately does not match -- it looks for
    // the min-width and range forms, which are the ones the layout system
    // writes. Widening it is the follow-up, not this phase.
    expect(offenders).toEqual([])
  })
})

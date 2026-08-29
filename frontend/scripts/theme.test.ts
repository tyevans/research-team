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
import { THEME_CHOICES, THEME_STORAGE_KEY } from '../src/presentation/shell/theme-choice.ts'

/** **What this file used to be, and why it is not that any more.**
 *
 * It compared `theme.css`'s `@theme` block against `tokens.css`'s `:root`
 * block and failed if any shared token disagreed. That existed because the
 * palette was written twice, on purpose and temporarily, and its own docstring
 * named the exit: *"Phase 5 deletes `tokens.css`'s `:root` block, at which
 * point this file has nothing left to compare and should go with it."*
 *
 * Phase 5 landed and the prediction was half right. There is nothing left to
 * compare -- every line in `tokens.css`'s `:root` block is now
 * `--bg: var(--color-bg)`, so a value disagreement is not caught by a test,
 * it is unrepresentable. That assertion is deleted rather than weakened.
 *
 * The file stays, because the *rename* it used to encode in a lookup table is
 * now the thing that can go wrong. `--fg-dim: var(--color-fg-dm)` is a typo
 * that types, lints, builds, emits a rule, and paints magenta -- and magenta is
 * only visible if somebody looks at the page it is on. So the first test below
 * is the old `RENAMED` map turned the other way up: every alias must point at a
 * token that exists.
 *
 * Deleting the file outright was considered and rejected for that reason. The
 * alternative -- trusting the browser suite to notice a magenta token -- means
 * a colour defect is caught by whichever measurement happens to read that
 * token, and thirty of the thirty-six are read by nothing.
 */

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

/** Layout constants, not theme values, and kept out of `@theme` on purpose:
 *  there is no such thing as a `topbar-h` utility or a `z-overlay` one, and
 *  putting them in the theme block would offer both.
 *
 *  The z-scale in particular must not become a utility. Its whole value is
 *  that there are three levels and that every dismissable layer shares one of
 *  them; a `z-overlay` class is an invitation to write a fourth. */
const NOT_ALIASES = new Set([
  '--topbar-h',
  '--rail-w',
  '--bp-wide',
  '--bp-narrow',
  '--bp-tight',
  '--z-sticky',
  '--z-overlay',
  '--z-toast',
])

describe('the alias block in tokens.css', () => {
  const aliases = () => declarations(read('tokens.css'), /:root\s*\{/)
  const theme = () => declarations(read('theme.css'), /@theme\s*\{/)

  it('holds no value of its own', () => {
    // The claim `tokens.css` now opens with, made mechanical: there is exactly
    // one place a colour is written in this repository, and it is not here.
    //
    // Stated as "every declaration is a bare `var()`" rather than as "no hex
    // appears", because the second is satisfied by `rgb(11 13 16)` and by
    // `color-mix(…)` and by any other spelling somebody reaches for. The first
    // admits nothing but an alias.
    //
    // Proved red by restoring `--accent: #e2a457`.
    const offenders = [...aliases()]
      .filter(([name]) => !NOT_ALIASES.has(name))
      .filter(([, value]) => !/^var\(--[\w-]+\)$/.test(value))
      .map(([name, value]) => `${name} is ${value}, which is not an alias`)

    expect(offenders).toEqual([])
  })

  it('points every alias at a token that exists', () => {
    // **The defect this file exists for since the collapse.**
    // `--fg-dim: var(--color-fg-dm)` types, lints, builds and emits a rule. It
    // paints `#ff00ff`, because the alias is a registered `<color>` whose
    // declaration is invalid at computed-value time and falls back to the
    // sentinel `initial-value` -- which is visible only to somebody looking at
    // the page that token dresses, and thirty of the thirty-six are read by no
    // test at all.
    //
    // Proved red by misspelling `--color-fg-faint` as `--color-fg-fant`.
    const declared = theme()
    const offenders = [...aliases()]
      .filter(([name]) => !NOT_ALIASES.has(name))
      .map(([name, value]) => [name, /^var\((--[\w-]+)\)$/.exec(value)?.[1]] as const)
      .filter(([, target]) => target !== undefined && !declared.has(target))
      .map(
        ([name, target]) => `${name} points at ${String(target)}, which theme.css does not declare`,
      )

    expect(offenders).toEqual([])
  })

  it('aliases every colour the theme declares', () => {
    // The other direction, and the one that goes wrong silently in the other
    // way: a colour added to `@theme` and not aliased here is a colour every
    // hand-written stylesheet cannot reach, so the first person to write
    // `var(--new-thing)` gets nothing and no build step objects.
    //
    // Colours only. `--text-*`, `--spacing-*`, `--font-*` and `--radius-md` are
    // aliased under different names and are covered by the previous test from
    // the alias side; `--shadow-1` is deliberately not aliased at all, because
    // its `@theme` name is already the name consumers use and an alias would be
    // a self-reference. `tokens.css` says so where the alias would have gone.
    const aliased = new Set(
      [...aliases()]
        .map(([, value]) => /^var\((--[\w-]+)\)$/.exec(value)?.[1])
        .filter((name) => name !== undefined),
    )
    const missing = [...theme().keys()]
      .filter((name) => name.startsWith('--color-'))
      .filter((name) => !aliased.has(name))

    expect(missing).toEqual([])
  })
})

describe('the colour registrations', () => {
  const registered = () =>
    Array.from(
      read('tokens.css')
        .replace(/\/\*[\s\S]*?\*\//g, '')
        .matchAll(/@property\s+(--[\w-]+)\s*\{([^}]*)\}/g),
      (match) => [match[1]!, match[2]!] as const,
    )

  it('registers every colour alias and nothing else', () => {
    // `tokens.css` argues why registration is not decoration: an unregistered
    // custom property hands `getComputedStyle` the scheme expression rather
    // than a colour, and the three canvases that read the palette at runtime
    // would silently keep painting in the previous colour.
    //
    // Registering *every* colour alias rather than the nine read today is the
    // decision this test holds. Proved red by deleting `@property --tint-ok`,
    // which nothing reads and which is exactly the one a subset would have
    // missed.
    const colourAliases = [...declarations(read('tokens.css'), /:root\s*\{/)]
      .filter(([name]) => !NOT_ALIASES.has(name))
      .filter(([, value]) => /^var\(--color-/.test(value))
      .map(([name]) => name)

    expect(
      registered()
        .map(([name]) => name)
        .sort(),
    ).toEqual([...colourAliases].sort())
  })

  it('falls back to a sentinel rather than to a plausible colour', () => {
    // A registered property whose declaration is invalid falls back to its
    // `initial-value` silently. Magenta on screen means "this token did not
    // resolve" and cannot be mistaken for a design decision; a plausible grey
    // there would mean nothing at all, and the alias-typo defect above would
    // ship looking like a slightly-off shade.
    //
    // Proved red by changing one registration's initial value to `#111418`.
    const offenders = registered()
      .filter(([, body]) => !/initial-value:\s*#ff00ff/i.test(body))
      .map(([name]) => name)

    expect(offenders).toEqual([])
  })

  it('registers them as inheriting colours', () => {
    // `inherits: false` would leave every descendant reading the initial value
    // -- a magenta console -- and `syntax: "*"` would give up the resolution
    // the registration exists for while still looking like a registration.
    const offenders = registered()
      .filter(([, body]) => !/syntax:\s*'<color>'/.test(body) || !/inherits:\s*true/.test(body))
      .map(([name]) => name)

    expect(offenders).toEqual([])
  })
})

describe('the pre-paint script', () => {
  const html = () => readFileSync(fileURLToPath(new URL('../index.html', import.meta.url)), 'utf8')

  it('reads the key the application writes', () => {
    // `index.html` duplicates the storage key and two of the state names,
    // because importing them would be a network round trip and the whole value
    // of that script is that it runs before one. `theme-choice.ts` says so.
    // This is the pin that makes the duplication safe: renaming the key without
    // touching the HTML would leave the console flashing the wrong theme on
    // every load, and nothing else would notice.
    //
    // Proved red by changing `THEME_STORAGE_KEY` to `rt.colour-theme`.
    expect(html()).toContain(`localStorage.getItem('${THEME_STORAGE_KEY}')`)
    for (const choice of THEME_CHOICES.filter((name) => name !== 'system')) {
      expect(html(), choice).toContain(`'${choice}'`)
    }
  })

  it('starts the document in a defined scheme', () => {
    // Without this the document has no `data-theme` until the script runs, and
    // `theme.css`'s `dark:` variant -- which can only match an attribute that
    // is present -- would be inert for the first frame and for any page whose
    // script was blocked.
    expect(html()).toContain('data-theme="system"')
  })
})

/** The layout constants exist twice for a reason neither language can avoid,
 *  so the agreement is checked rather than trusted.
 *
 *  A stylesheet cannot import a TypeScript constant and `matchMedia` cannot
 *  read a CSS custom property without `getComputedStyle`, which returns
 *  nothing under jsdom. So the numbers are written in both places. That is the
 *  arrangement `tokens.css` opens by warning about — and it is exactly what
 *  the console had, unchecked: `34px` in a hook and twice in a stylesheet, and
 *  one breakpoint spelled `1180` in CSS and `1181` in JavaScript.
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
    // what the console had, and the stylesheet contradicted the rule -- the
    // agent dock's popover at 40 painted over an `aria-modal` backdrop at 20.
    // A fourth level is a decision to make deliberately, and this fails until
    // someone does.
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

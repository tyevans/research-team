// `node:fs`'s sync API rather than `node:fs/promises`, matching
// `stacking.test.ts` and `theme.test.ts`, and for the reason they give:
// eslint type-checks this directory against an inferred program that resolves
// `node:fs` but not the `node:fs/promises` subpath.
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

/** That the palette, the weight scale and the radius stay decisions made in
 *  `theme.css`, which is what `STYLE_GUIDE.md` says they are.
 *
 * **The defect this closes.** Fourteen colour literals were sitting in nine
 * stylesheets, and every one of them was a *dark-scheme* shade — written when
 * the console had only a dark scheme, and left behind when `light-dark()`
 * arrived. A literal applies in both schemes, so in light mode the scrollbar
 * thumb was slate grey on cream, the historical scrub bar faded from near
 * black, the connection pill's border was a dark green, and the primary
 * button turned pale amber under near-white ink the moment a pointer touched
 * it. Nothing was red: the value is valid CSS, every gate passed, and the
 * only symptom was that half the schemes looked wrong to somebody who had to
 * be in light mode to see it.
 *
 * **Why this rather than eyes.** The whole population is grep-able and small,
 * which is the case a test wins. Reviewing for it does not scale — the
 * literals arrived one reasonable-looking hex at a time, each beside a
 * `var(--…)` that made it read as deliberate, and three of them carried a
 * comment explaining the shade.
 *
 * **What is exempt, and why each.** `theme.css` is the palette and is where
 * every literal belongs. `tokens.css` declares `initial-value: #ff00ff` on its
 * registered properties, deliberately and with the argument written above
 * them — magenta is the "this token is undeclared" signal, not a colour
 * anybody sees. Both are named rather than pattern-matched, so a third
 * exemption has to be argued here rather than acquired.
 *
 * Proved red before being trusted green: with the fourteen literals restored
 * this fails naming nine files; with `font-weight: 700` restored in
 * `components.css` it fails on the weight case; with `border-radius: 3px`
 * restored it fails on the radius case.
 */

const STYLES = fileURLToPath(new URL('../src/styles', import.meta.url))

const read = (name: string) => readFileSync(`${STYLES}/${name}`, 'utf8')

/** Comments stripped first, exactly as `stacking.test.ts` and `theme.test.ts`
 *  do, and for the reason they give: these stylesheets explain at length what
 *  a removed literal *was*, and a check that fires on the prose recording
 *  `Was \`#45272a\`, which is \`--tint-fail-line\` written out` makes the
 *  removal undocumentable. `conversation.css` and `shell.css` both carry such
 *  a paragraph. */
const withoutComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')

/** `theme.css` holds the palette; `tokens.css` holds the undeclared-token
 *  sentinel. Everything else names a token or it is a defect. */
const EXEMPT = new Set(['theme.css', 'tokens.css'])

const SOURCES = readdirSync(STYLES).filter((name) => name.endsWith('.css'))
const CHECKED = SOURCES.filter((name) => !EXEMPT.has(name))

describe('the palette is declared in theme.css and nowhere else', () => {
  it('sweeps every stylesheet, so a new file cannot slip past the list', () => {
    // The guard on the guard, as `stacking.test.ts` argues: a rule is only
    // worth something if it reads everything, and a hand-maintained list would
    // silently stop covering the next file somebody adds. This asserts the
    // directory listing is real and still contains the files the defect lived
    // in.
    expect(CHECKED).toContain('shell.css')
    expect(CHECKED).toContain('components.css')
    expect(CHECKED).toContain('base.css')
    expect(CHECKED).not.toContain('theme.css')
    expect(CHECKED.length).toBeGreaterThan(10)
  })

  it.each(CHECKED)('%s writes no colour literal', (name) => {
    const hex = Array.from(
      withoutComments(read(name)).matchAll(/#[0-9a-fA-F]{3,8}\b/g),
      (m) => m[0],
    )

    // A literal here is a second palette that only one scheme is right in.
    // `#eeb168` on `.btn-accent:hover` is what that costs: correct in dark,
    // and in light a pale fill under `--accent-fg`'s near-white ink.
    expect(hex).toEqual([])
  })

  it.each(CHECKED)('%s writes no rgb()/hsl() literal either', (name) => {
    // The same defect in the other notation. `theme.css` uses `rgba()` inside
    // `--color-link` and `rgb(0 0 0 / …)` inside `--shadow-1`, which is why
    // this is a sweep of the non-exempt files rather than of all of them.
    const fn = Array.from(
      withoutComments(read(name)).matchAll(/\b(?:rgba?|hsla?|oklch|lab)\s*\(/g),
      (m) => m[0],
    )

    expect(fn).toEqual([])
  })
})

describe('the type and shape scales hold', () => {
  it.each(CHECKED)('%s uses no weight above 600', (name) => {
    // `STYLE_GUIDE.md` §3.3: three weights, and no bold. The mono stacks have
    // no 700 face, so a browser synthesises one by smearing the 600 — heavier
    // and blurrier at 10.5px, which is most of this console. Hierarchy comes
    // from size, ink tier and space instead.
    const heavy = Array.from(
      withoutComments(read(name)).matchAll(/font-weight:\s*([^;}]+)/g),
      (m) => m[1]!.trim(),
    ).filter((value) => /^(?:700|800|900|bold(?:er)?)$/.test(value))

    expect(heavy).toEqual([])
  })

  it.each(CHECKED)('%s rounds a rectangle only by var(--radius)', (name) => {
    // One radius, `--radius-md` at 5px. `999px` and `50%` are exempt because
    // they are *shapes* rather than steps on a scale — a pill and a circle
    // are the same object at any radius token, and clamping either to 5px
    // would square a status dot. `0` is an explicit square, which is the
    // whole point of the rails and full-bleed regions being square.
    const offending = Array.from(
      withoutComments(read(name)).matchAll(/border-radius[\w-]*:\s*([^;}]+)/g),
      (m) => m[1]!.trim(),
    ).filter(
      (value) =>
        !value.split(/\s+/).every((part) => /^(?:var\(--radius\)|999px|50%|0)$/.test(part)),
    )

    expect(offending).toEqual([])
  })
})

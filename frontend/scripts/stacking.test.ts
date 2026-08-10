// `node:fs`'s sync API rather than `node:fs/promises`, matching
// `theme.test.ts` and `build-config.test.ts`, and for the reason stated there:
// eslint type-checks this directory against an inferred program that resolves
// `node:fs` but not the `node:fs/promises` subpath.
import { readFileSync, readdirSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { describe, expect, it } from 'vitest'

/** That stacking order stays a decision made in one file.
 *
 * **The defect this closes, and why the migration alone did not close it.**
 * The console shipped with the agent dock's popover at `z-index: 40` painting
 * over an `aria-modal` drawer backdrop at 20 — a live, clickable panel on top
 * of a dialog claiming to be modal, while the popover's own comment asserted
 * the drawer was in front. `OverlayHost` makes that unrepresentable *among
 * layers that register with it*: they share one `--z-overlay`, so order is
 * mount order and there is no per-layer number to get wrong. The previous
 * change moved every such overlay onto it.
 *
 * That is a guarantee about the overlays which exist, not about the next one.
 * Nothing stopped somebody writing `position: fixed; z-index: 60` in a
 * stylesheet and reproducing the inversion exactly — which is precisely how
 * the original arrived, one reasonable-looking number at a time. `OverlayHost`
 * named this as the missing half and said the fix was "a rule forbidding
 * `z-index` outside `tokens.css`". This is that rule.
 *
 * **What it actually forbids, which is narrower than that sentence and has to
 * be.** A blanket ban on the property is not implementable: `tokens.css`
 * declares custom properties and contains no `z-index` declaration at all, so
 * "only in tokens.css" would forbid every use everywhere. The enforceable
 * version of the same intent is that **a `z-index` may only be a `var(--z-*)`
 * whose token is declared in `tokens.css`**. A literal is what encodes an
 * ordering, so a literal is what is banned; naming a token is how a stylesheet
 * says which of the three declared roles a thing plays, and adding a fourth
 * role becomes an edit to the scale in `tokens.css` with its argument beside
 * it, rather than a number in a file nobody reads next to it.
 *
 * **Why a test rather than stylelint.** Considered and rejected on three
 * counts. stylelint is a new dependency plus a plugin — `declaration-property-
 * value-allowed-list` takes patterns, not "must resolve to a declared token",
 * so the token-exists half would still be custom. It would change
 * `package-lock.json`, which in this repository has to be regenerated with the
 * exact npm CI resolves or `npm ci` fails and skips every frontend step. And
 * it would be a sixth tool in a chain that already has five. This is thirty
 * lines, no dependency, and runs inside a gate that already exists — the same
 * trade `theme.test.ts` and `check-size.mjs` made for the same kind of
 * invariant.
 *
 * **What it does not catch, stated because it matters.** Inline styles and
 * `style={{ zIndex }}` in TSX are out of scope: nothing in `src/` does that
 * today, and widening the sweep to every component file would collide with the
 * stories, which set `position: fixed` inline on purpose. A component that
 * needed a stacking order badly enough to inline it would be doing something
 * the host should be doing instead. If one appears, extend `SOURCES` rather
 * than granting it an exception.
 *
 * Proved red three ways before being trusted green: a literal `z-index: 9`
 * added to `agents.css` (caught as a literal), `z-index: var(--z-modal)`
 * naming a token that does not exist (caught as undeclared), and by deleting
 * `--z-overlay` from `tokens.css` so a *legitimate* use became undeclared.
 */

const STYLES = fileURLToPath(new URL('../src/styles', import.meta.url))

const read = (name: string) => readFileSync(`${STYLES}/${name}`, 'utf8')

/** Comments stripped first, exactly as `theme.test.ts` and
 *  `check-deleted.mjs` do, and for the reason they give: these stylesheets
 *  explain at length *why* a number was removed, and a check that fires on
 *  prose describing a deleted `z-index: 20` makes the deletion
 *  undocumentable. `course.css` and `agents.css` both carry such a paragraph
 *  in this very commit. */
const withoutComments = (css: string) => css.replace(/\/\*[\s\S]*?\*\//g, '')

/** Every token `tokens.css` declares, so a `var(--z-…)` can be checked against
 *  something rather than merely pattern-matched. A name that looks like a
 *  token but is not declared resolves to nothing at runtime, which means the
 *  browser drops the declaration and the element silently takes its parent's
 *  stacking order — a failure that looks exactly like the rule being obeyed. */
const declaredTokens = (): ReadonlySet<string> =>
  new Set(Array.from(withoutComments(read('tokens.css')).matchAll(/(--[\w-]+)\s*:/g), (m) => m[1]!))

const SOURCES = readdirSync(STYLES).filter((name) => name.endsWith('.css'))

describe('stacking order is declared in tokens.css and nowhere else', () => {
  it('sweeps every stylesheet, so a new file cannot slip past the list', () => {
    // The guard on the guard. This rule is only worth anything if it reads
    // everything, and a hand-maintained list of stylesheets would silently
    // stop covering the next one somebody adds. `SOURCES` is a directory
    // listing for that reason; this asserts the listing is not empty and does
    // include the files where the defect actually lived.
    expect(SOURCES).toContain('agents.css')
    expect(SOURCES).toContain('course.css')
    expect(SOURCES).toContain('tokens.css')
    expect(SOURCES.length).toBeGreaterThan(10)
  })

  it.each(SOURCES)('%s uses no literal z-index', (name) => {
    const offending = Array.from(
      withoutComments(read(name)).matchAll(/z-index\s*:\s*([^;}]+)/g),
      (match) => match[1]!.trim(),
    ).filter((value) => !/^var\(\s*--z-[\w-]+\s*\)$/.test(value))

    // A literal here is a second, private stacking scale. `.agents-panel` at
    // 40 against `.drawer-backdrop` at 20 is what that costs, and both numbers
    // read as reasonable in the file that held them.
    expect(offending).toEqual([])
  })

  it.each(SOURCES)('%s names only tokens that tokens.css declares', (name) => {
    const tokens = declaredTokens()
    const used = Array.from(
      withoutComments(read(name)).matchAll(/z-index\s*:\s*var\(\s*(--z-[\w-]+)\s*\)/g),
      (match) => match[1]!,
    )

    expect(used.filter((token) => !tokens.has(token))).toEqual([])
  })

  it('keeps the scale itself small enough to hold in your head', () => {
    const scale = Array.from(declaredTokens()).filter((token) => token.startsWith('--z-'))

    // Three roles: `--z-sticky` for things that float within a region and must
    // not escape it, `--z-overlay` for the one host every dismissable layer
    // portals into, and `--z-toast` above both. `tokens.css` argues each and
    // explains why there is no fourth.
    //
    // This is the assertion that stops the rule from being satisfied by
    // ceremony. Without it, a new overlay obeys the letter of the rule by
    // adding `--z-popover: 40` to `tokens.css` and pointing at it — the same
    // defect, one file over, now blessed. A fourth role should cost a
    // conversation, and failing here is that conversation.
    expect(scale.sort()).toEqual(['--z-overlay', '--z-sticky', '--z-toast'])
  })
})

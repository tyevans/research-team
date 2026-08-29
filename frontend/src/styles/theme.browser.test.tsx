/// <reference types="vite/client" />
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { commands } from 'vitest/browser'

/** That the console actually has two palettes and that the right one is in
 *  force.
 *
 * **Every assertion in this file is a browser measurement, and none of them
 * could be a jsdom one.** jsdom applies no stylesheet, so
 * `getComputedStyle(el).color` there returns what an inline style said and
 * nothing a rule contributed: a console with a working light mode, a console
 * whose light column was never written, and a console with no stylesheet at
 * all are the same three characters of output. That is CLAUDE.md's rule and it
 * is the whole reason this file exists rather than a `theme.test.tsx`.
 *
 * The shape follows `color-scheme.browser.test.tsx`, which is the existing
 * measurement in this directory: set a state on `document.documentElement`,
 * render something the rule reaches, and read the engine's answer.
 */

declare module 'vitest/browser' {
  interface BrowserCommands {
    /** `null` clears the emulation. See `vite.config.ts` for why this has to be
     *  a custom command rather than something the test can do itself. */
    setColorScheme: (scheme: 'light' | 'dark' | null) => Promise<void>
  }
}

/** The document's own `data-theme`, restored after each test. Tests here move
 *  a global, and a leaked `data-theme='light'` would silently retheme every
 *  file that runs after this one in the same page. */
const declared = document.documentElement.getAttribute('data-theme')

afterEach(async () => {
  if (declared === null) document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', declared)
  await commands.setColorScheme(null)
})

const theme = (value: string | null) => {
  if (value === null) document.documentElement.removeAttribute('data-theme')
  else document.documentElement.setAttribute('data-theme', value)
}

/** A element painted by the stylesheet's tokens rather than by an inline
 *  colour, so what comes back is the cascade's answer and not the test's. */
const paint = (declarations: string) => {
  const el = document.createElement('div')
  el.setAttribute('style', declarations)
  document.body.append(el)
  return getComputedStyle(el)
}

/** A custom property as the engine resolved it, read off the root the way
 *  `GraphCanvas` reads the kind palette. */
const token = (name: string) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim()

/** Every colour token, found rather than listed.
 *
 * The population is the `@property` block in `tokens.css`: a registration with
 * `syntax: "<color>"` is, by construction, exactly one of the console's colour
 * aliases. Reading it back out of the live stylesheet means a token added
 * tomorrow is swept tomorrow, which a hand-written array would not be -- the
 * failure mode `a11y.browser.test.tsx` avoids the same way with its story glob.
 *
 * It also ties the two mechanisms together in the direction that matters: a
 * colour that is registered but has no light column, and a colour with a light
 * column that nobody registered, are both defects, and the first is what the
 * sweep below catches.
 */
const colourTokens = (): string[] => {
  const names: string[] = []
  for (const sheet of document.styleSheets) {
    let rules: CSSRuleList
    try {
      rules = sheet.cssRules
    } catch {
      continue // A cross-origin sheet, of which this page has none today.
    }
    for (const rule of rules) {
      // `rule.syntax` is matched rather than compared: Chromium serialises it
      // as `<color>` where the spec's IDL suggests the quoted form, and a `===`
      // against the wrong one of those returns an empty sweep -- which passes a
      // "nothing differed" assertion. The `dark.size` floor below exists
      // because that is exactly how this first ran.
      if (rule instanceof CSSPropertyRule && /^"?<color>"?$/.test(rule.syntax))
        names.push(rule.name)
    }
  }
  return names
}

describe('the two palettes', () => {
  it('gives every colour token a different value under each theme', () => {
    // **The assertion that says the light palette is complete**, rather than
    // that some of it exists.
    //
    // The first draft of this test read one token pair (`--fg` on `--bg`) and
    // checked the two schemes differed and were the right way round. It passed
    // with `--color-fg` rewritten as a bare `#d7dee7` -- because `--bg` still
    // moved, so the pair still differed, and a light-grey ink on a
    // near-white page is still darker than the page. A single sample cannot
    // distinguish "the palette has a light column" from "one token does",
    // which is CLAUDE.md's rule about a test whose inputs and whose subject
    // were chosen in the same hour.
    //
    // What this fails on: any one of the ~36 colour tokens left as a single
    // value. Proved red by rewriting `--color-fg` as `#d7dee7`, the case the
    // first draft missed, and again by deleting the light branch of
    // `--color-k-turn`.
    theme('dark')
    const dark = new Map(colourTokens().map((name) => [name, token(name)]))
    theme('light')
    const light = new Map(colourTokens().map((name) => [name, token(name)]))

    expect(dark.size).toBeGreaterThan(30) // The sweep saw a stylesheet at all.
    expect([...dark].filter(([name, value]) => light.get(name) === value).map(([n]) => n)).toEqual(
      [],
    )
  })

  it('puts the ink and the page the right way round in each scheme', () => {
    // The direction, which the sweep above deliberately does not check: a
    // palette whose two columns were swapped passes it. Stated as the *sign*
    // of the difference rather than as values, so the palette can be retuned
    // without touching this test.
    //
    // What it fails on: the `color-scheme` rules in `tokens.css` not matching
    // `[data-theme]`, which makes `light-dark()` pick one branch forever and
    // gives a dark ink on a dark page.
    theme('dark')
    const dark = paint('color: var(--fg); background: var(--bg)')
    const darkPair = [dark.color, dark.backgroundColor]

    theme('light')
    const light = paint('color: var(--fg); background: var(--bg)')
    const lightPair = [light.color, light.backgroundColor]

    expect(darkPair).not.toEqual(lightPair)

    // Not merely "different": the right way round. `--fg` is near-white on a
    // near-black page in dark and near-black on a near-white page in light, so
    // the *sign* of the difference is the claim, not the values -- which lets
    // the palette be retuned without touching this test.
    //
    // The pairs are read off the *captured strings* rather than off the live
    // `CSSStyleDeclaration` the helper returns, and that is not tidiness: a
    // computed-style object stays live, so reading `dark.color` after the
    // second `theme()` call yields the light value. The first draft of this
    // test did exactly that and reported the two schemes as swapped -- which
    // looked like a palette written the wrong way round and was a test reading
    // the wrong moment.
    const luminance = (rgb: string) => {
      const [r, g, b] = rgb.match(/\d+/g)!.slice(0, 3).map(Number)
      return 0.2126 * r! + 0.7152 * g! + 0.0722 * b!
    }
    expect(luminance(darkPair[0]!)).toBeGreaterThan(luminance(darkPair[1]!))
    expect(luminance(lightPair[0]!)).toBeLessThan(luminance(lightPair[1]!))
  })

  it('lets an explicit choice beat the system preference', async () => {
    // **The assertion the feature is actually for.** A reader on a dark
    // desktop who asks for light must get light.
    //
    // What it fails on: `tokens.css` declaring `color-scheme` only inside a
    // `prefers-color-scheme` media query, or a `data-theme` selector that the
    // system rule outranks. Proved red by reordering the three
    // `:root[data-theme=…]` rules above the bare `:root` one -- which loses,
    // because `:root, :root[data-theme='system']` and `:root[data-theme='light']`
    // are the same specificity and the later rule wins.
    await commands.setColorScheme('dark')

    theme(null)
    const systemDefault = paint('background: var(--bg)').backgroundColor

    theme('light')
    const chosen = paint('background: var(--bg)').backgroundColor

    expect(chosen).not.toBe(systemDefault)
    // And the choice is genuinely light rather than merely "not the system's".
    const [r, g, b] = chosen.match(/\d+/g)!.slice(0, 3).map(Number)
    expect(Math.min(r!, g!, b!)).toBeGreaterThan(200)
  })

  it('follows the system preference when nothing was chosen', async () => {
    // The default path, and the one almost every reader is on. It fails if the
    // bare `:root` rule loses its `color-scheme: light dark` -- at which point
    // `light-dark()` resolves to its light branch unconditionally and a dark
    // desktop gets a white console.
    //
    // Both directions are asserted rather than only the dark one, because a
    // stuck value passes a one-directional version of this test.
    await commands.setColorScheme('dark')
    theme(null)
    const onADarkDesktop = paint('background: var(--bg)').backgroundColor

    await commands.setColorScheme('light')
    const onALightDesktop = paint('background: var(--bg)').backgroundColor

    expect(onADarkDesktop).not.toBe(onALightDesktop)
  })
})

describe('the tokens the canvases read at runtime', () => {
  it('resolves a registered custom property to a colour, not to a function call', () => {
    // **The measurement that changed the design.** `GraphCanvas.tsx`,
    // `GraphLegend.tsx` and `TimelineCanvas.tsx` read the kind palette off the
    // root with `getComputedStyle` and hand the string to `fillStyle`, which
    // ignores an unparseable value in silence. An *unregistered* custom
    // property computes to its own token stream, so without the `@property`
    // block in `tokens.css` these reads return the two-branch scheme
    // expression rather than a colour and three canvases keep painting in the
    // previous entity's colour, with nothing thrown and nothing logged.
    //
    // What it fails on: deleting any `@property --k-*` registration. Proved
    // red that way -- the read came back as
    // `var(--lightningcss-light,#6d4bd0) var(--lightningcss-dark,#a78bfa)`,
    // which is what Lightning CSS compiles `light-dark()` down to for this
    // build's browser targets.
    //
    // `--color-k-session` -- the `@theme` name, unregistered on purpose -- is
    // asserted *against*, so this test also says which of the two spellings a
    // runtime reader must use.
    theme('dark')
    expect(token('--k-session')).toMatch(/^rgba?\(/)
    expect(token('--color-k-session')).not.toMatch(/^rgba?\(/)
  })

  it('gives the canvases a different colour under each theme', () => {
    // The point of registering them, rather than merely that they parse.
    // Fails if a kind colour is written as one value instead of a pair.
    theme('dark')
    const dark = token('--k-session')
    theme('light')
    expect(token('--k-session')).not.toBe(dark)
  })

  it('ignores an off-syntax value instead of taking it', () => {
    // The other half of what registration buys, and it is not the half this
    // test was first written to claim.
    //
    // The first draft asserted that an invalid value falls back to the
    // `initial-value: #ff00ff` sentinel, and it failed: a declaration that does
    // not match a registered property's `syntax` is rejected **at parse time**,
    // so the element keeps the value it inherited rather than reaching the
    // initial value at all. That is better behaviour than the one being
    // claimed, and the claim was wrong rather than the code. Recorded here
    // because the sentinel is still worth having -- it is what a *root* whose
    // declaration failed would show -- and because "invalid means magenta" is
    // the plausible-sounding thing a reader would otherwise assume.
    //
    // What this fails on: dropping the `@property --k-session` registration.
    // Unregistered, `--k-session: not-a-colour` is a perfectly good custom
    // property value, `color` becomes invalid at computed-value time, and the
    // element renders `rgb(0, 0, 0)` -- an unreadable black on a dark page,
    // from a typo three files away.
    theme('dark')
    const el = document.createElement('div')
    el.setAttribute('style', '--k-session: not-a-colour; color: var(--k-session)')
    document.body.append(el)
    expect(getComputedStyle(el).color).toBe(token('--k-session'))
  })
})

describe("Tailwind's opacity modifier over a themed token", () => {
  it('composites the active scheme rather than one fixed branch', () => {
    // `docs/design/frontend-library-adoption.md` §1 asks for exactly this
    // measurement before converting forty tokens, and it was right to: v4
    // implements `bg-accent/50` as
    // `color-mix(in oklab, var(--color-accent) 50%, transparent)`, and whether
    // a scheme-dependent value survives that nesting is a question about an
    // engine rather than about a spec.
    //
    // It does. What this fails on: a build whose CSS target stops resolving
    // the scheme expression inside `color-mix` -- which would show up as one
    // scheme's accent bleeding into the other, and as nothing else.
    const el = document.createElement('div')
    el.className = 'bg-accent/50'
    document.body.append(el)

    theme('dark')
    const dark = getComputedStyle(el).backgroundColor
    theme('light')
    const light = getComputedStyle(el).backgroundColor

    // Both are real composited colours rather than `transparent` or the
    // literal string, and they differ. `oklab(…)` rather than `rgb(…)` is what
    // comes back, because `color-mix(in oklab, …)` computes in that space and
    // Chromium serialises it there -- measured, not assumed; the first draft
    // of this assertion matched `/^rgba?\(/` and failed on a working build.
    expect(dark).toMatch(/^(rgba?|oklab|color)\(/)
    expect(light).toMatch(/^(rgba?|oklab|color)\(/)
    expect(dark).not.toBe(light)
  })
})

describe('the font weights', () => {
  beforeEach(() => {
    theme('dark')
  })

  it('makes font-semibold draw something', () => {
    // `check-tailwind.mjs` recorded that `font-semibold` (16 sites),
    // `font-medium` (12) and `font-normal` (1) generated no CSS at all,
    // because font weights live in Tailwind's default theme and `theme.css`
    // omits it. The console had no bold text where it thought it had sixteen
    // instances of it.
    //
    // In the browser suite rather than the build one on purpose. The build
    // check greps the stylesheet for a selector, which proves a rule was
    // emitted; this proves the rule *applies* -- a `.font-semibold{}` that
    // some later unlayered rule outranks passes the grep and fails here.
    for (const [name, weight] of [
      ['font-normal', '400'],
      ['font-medium', '500'],
      ['font-semibold', '600'],
    ] as const) {
      const el = document.createElement('div')
      el.className = name
      document.body.append(el)
      expect(getComputedStyle(el).fontWeight, name).toBe(weight)
    }
  })

  it('still refuses a weight the console did not choose', () => {
    // The half that makes the fix a decision rather than a capitulation.
    // `theme.css` declares three weights and no more, so `font-bold` is still
    // a class that generates nothing -- which is the property the whole
    // no-default-theme arrangement exists to keep. Fails if someone declares
    // `--font-weight-bold` to make a stray class valid.
    const el = document.createElement('div')
    el.className = 'font-bold'
    document.body.append(el)
    expect(getComputedStyle(el).fontWeight).toBe('400')
  })
})

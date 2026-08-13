/// <reference types="vite/client" />
import { composeStories } from '@storybook/react-vite'
import { render } from '@testing-library/react'
import axe from 'axe-core'
import { userEvent } from 'vitest/browser'
import { expect, it } from 'vitest'

import * as paneStories from './presentation/layout/Pane.stories.tsx'

/** Every story in the console, swept by axe against real layout and the real
 *  stylesheet.
 *
 * **Why this is a browser test and could not be a jsdom one.** The rule this
 * file exists for is `color-contrast`, and it is the clearest case in the
 * repository of a check that needs an engine. axe reads the *computed*
 * foreground and background of each text node, walks up the ancestor chain to
 * find whatever actually paints behind it, and composites `opacity` on the way.
 * jsdom returns what an inline style said and nothing a rule contributed, so
 * there axe reports every node as `incomplete` and the sweep would be a green
 * page reporting on a stylesheet it never read. `330ffa3` left a contrast
 * question open in exactly those words -- "a number this sweep did not
 * measure" -- because the tooling to measure it did not exist yet. This is it.
 *
 * **Why `axe-core` directly rather than a wrapper.** `@axe-core/playwright`
 * drives a Playwright `Page` from Node; these tests run *inside* the browser,
 * where there is no `Page` object to hand it, so it does not apply however
 * convenient its API looks. `vitest-axe` would work -- it is a matcher around
 * the same engine -- but it buys one `expect` extension and costs a dependency,
 * and the assertions below are not "no violations": they are set comparisons
 * against a recorded inventory, which its matcher cannot express. So the engine
 * is used directly. `axe-core` was already in the tree as a transitive of
 * `eslint-plugin-jsx-a11y`; it is now a declared dependency, because a version
 * this file's expectations are pinned to should not be a lint plugin's choice.
 *
 * **The rule set is named rather than defaulted.** `runOnly` restricts the run
 * to the four WCAG A/AA tags, which excludes axe's `best-practice` rules --
 * those encode opinions (heading order, region landmarks) that a *mounted
 * fragment* cannot be fairly judged against, since no story is a page. One
 * WCAG rule is then disabled, and it is the only one:
 *
 * `scrollable-region-focusable`, which fired on seven nodes across the `Pane`
 * and `Shell` stories. It is a **false positive in Chromium**, and that was
 * measured rather than assumed -- see `a scroll container is reachable without
 * a tabindex` below, which drives real Tab presses and lands on
 * `.lay-pane-body`. axe's check is static: it looks for a `tabindex` or for
 * focusable content, and predates Chromium making scroll containers
 * keyboard-focusable on their own. `330ffa3` had already found the same thing
 * from the other side, when a sweep for clipped focus rings discovered two
 * scrollers taking focus that its author had predicted would not.
 *
 * The honest caveat, recorded because disabling a rule on one engine's
 * behaviour is exactly where this goes wrong later: Firefox and Safari do not
 * do this, so in those engines the rule is a *true* positive and these panes
 * would be unreachable by keyboard. This console is a developer tool with a
 * Chromium suite by explicit choice (`vite.config.ts` argues that), so the
 * disable is scoped to what is actually shipped. The premise test is what makes
 * that a decision rather than a hope: the day Chromium drops the behaviour it
 * fails, and this rule should be turned back on rather than the test relaxed.
 */

/** Every story module in the console, found rather than listed. A hand-written
 *  list is a sweep that silently stops covering the component somebody added
 *  last week, which is the failure mode a sweep exists to prevent; the floor
 *  assertions below are what stop the glob failing the same way. */
const STORY_MODULES: Record<string, unknown> = import.meta.glob('./presentation/**/*.stories.tsx', {
  eager: true,
})

const AXE_OPTIONS: axe.RunOptions = {
  runOnly: { type: 'tag', values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'] },
  rules: { 'scrollable-region-focusable': { enabled: false } },
}

/** The contrast pairs this console ships today that do not reach WCAG AA's
 *  4.5:1 for normal text. A *ratchet*, in the sense `vite.config.ts` uses for
 *  the coverage floors: it does not say these are acceptable, it says they are
 *  known, so that the thirteenth pair fails this file instead of joining them
 *  unnoticed.
 *
 * Recorded as colour pairs rather than as elements or counts, because the pair
 * is the defect and the element is not: `#5c6673 on #111418` fails at 55 sites
 * and one token fixes all 55. Keying on elements would churn on every markup
 * edit and would let a *new* component adopt a failing token in silence.
 *
 * Eleven of the twelve are one token. `--fg-faint` (`#5c6673`) reaches 3.33:1
 * on `--bg`, 3.16:1 on `--bg-panel`, 3.02:1 on `--bg-panel-2`, 2.80:1 on
 * `--bg-raise` and 2.68:1 on `--bg-hover` -- so it fails against every surface
 * in the palette, not against an unlucky one. The remaining five entries with a
 * foreground that is *not* in `tokens.css` are that same token composited
 * through an `opacity` on an ancestor: `.ent-topic-row.is-closed` at 0.6 and
 * `.artifact-missing` at 0.62, both deliberate "de-emphasised" states, which
 * take an already-failing 3.33:1 down to 1.90:1. That axe reports the blended
 * colour rather than the declared one is the single most useful thing it does
 * here, and it is a number no stylesheet grep could have produced.
 *
 * **Deliberately not fixed in this commit**, and this is a judgement rather
 * than an oversight. Raising `--fg-faint` to 4.5:1 on `--bg-panel` puts it
 * within a hair of `--fg-dim` (`#8a95a3`, which passes at 6.3:1), collapsing a
 * three-tier text hierarchy into two across 60 declarations -- a redesign of
 * the console's visual language, with a diff in every stylesheet, arriving
 * inside a commit whose subject is a test harness. The `opacity` states need a
 * separate answer again, since the fix there is to stop dimming text that is
 * already the dimmest thing on the page. Both belong in their own change, with
 * someone looking at the result.
 */
const KNOWN_CONTRAST_DEBT: readonly string[] = [
  // `--fg-faint` on each surface it is drawn over.
  '#5c6673 on #0b0d10', // --bg
  '#5c6673 on #111418', // --bg-panel
  '#5c6673 on #15191e', // --bg-panel-2
  '#5c6673 on #1b2027', // --bg-raise
  '#5c6673 on #1e242c', // --bg-hover
  '#5c6673 on #241417', // --tint-fail
  // The same token seen through `opacity: 0.6` on `.ent-topic-row.is-closed`.
  '#3c424b on #0b0d10',
  '#3d444d on #0b0d10',
  '#3e454f on #111418',
  // Through `opacity: 0.62` on `.artifact-missing`.
  '#575f68 on #0b0d10',
  '#5a616b on #0b0d10',
  '#5a616b on #111418',
]

/** What the sweep saw, so a claim can be made about whether it saw anything.
 *
 * The counting is the point. A sweep that reports no violations because it
 * rendered nothing, or because the stylesheet failed to load and axe fell back
 * to `incomplete` on every node, looks exactly like a clean one -- and this
 * suite has already been bitten once by a stylesheet arriving through a route
 * nobody checked (`vitest.setup.browser.ts` records it). So the floors below
 * are asserted alongside the violations. */
interface Sweep {
  stories: number
  contrastPairs: Set<string>
  contrastNodesPassed: number
  otherViolations: string[]
}

const sweep = async (): Promise<Sweep> => {
  const result: Sweep = {
    stories: 0,
    contrastPairs: new Set(),
    contrastNodesPassed: 0,
    otherViolations: [],
  }

  for (const [path, module] of Object.entries(STORY_MODULES)) {
    // No `try` around this on purpose: a story module that cannot be composed
    // is a failure of the sweep, not a story to skip quietly. Skipping is how a
    // sweep shrinks to nothing while staying green.
    const composed = composeStories(module as never) as unknown as Record<
      string,
      React.ComponentType
    >

    for (const [name, Story] of Object.entries(composed)) {
      const host = document.createElement('div')
      document.body.append(host)
      try {
        render(<Story />, { container: host })
        // Radix positions a portalled layer on a frame after mount, and a
        // virtual list measures before it fills. Measured rather than reasoned:
        // at 0ms the `TopicQueue` stories report no rows at all.
        await new Promise((resolve) => setTimeout(resolve, 60))

        const results = await axe.run(host, AXE_OPTIONS)

        for (const pass of results.passes) {
          if (pass.id === 'color-contrast') result.contrastNodesPassed += pass.nodes.length
        }
        for (const violation of results.violations) {
          if (violation.id !== 'color-contrast') {
            result.otherViolations.push(
              `${path}#${name} [${violation.id}] ${violation.nodes.map((n) => n.target.join(' ')).join(', ')}`,
            )
            continue
          }
          for (const node of violation.nodes) {
            const measured = /foreground color: (#[0-9a-f]+), background color: (#[0-9a-f]+)/.exec(
              node.failureSummary ?? '',
            )
            // axe always words the summary this way for this rule; if it stops,
            // the pair set empties and the comparison below fails loudly rather
            // than the sweep going quiet.
            if (measured) result.contrastPairs.add(`${measured[1]!} on ${measured[2]!}`)
          }
        }
        result.stories += 1
      } finally {
        host.remove()
      }
    }
  }

  return result
}

/** One `it`, not one per story, because the interesting assertions are about
 *  the *set* of findings across the whole console rather than about any single
 *  component -- "no new failing colour pair anywhere" is not a claim a
 *  per-story test can make. The cost is a coarser failure message, paid back by
 *  the pair being named in it. Measured at ~12s of the browser suite's runtime,
 *  which roughly triples it; that is affordable precisely because this suite is
 *  not in CI. */
it('sweeps every story for WCAG A/AA violations', { timeout: 300_000 }, async () => {
  const result = await sweep()

  // Floors rather than equalities: a story added tomorrow should not fail this.
  // The numbers are what was measured today (21 modules, 91 stories) less a
  // little slack, and they exist to catch the sweep collapsing -- a glob that
  // stops matching, a `composeStories` that returns nothing.
  expect(Object.keys(STORY_MODULES).length).toBeGreaterThanOrEqual(21)
  expect(result.stories).toBeGreaterThanOrEqual(85)

  // The anti-rubber-stamp assertion, and the one worth understanding. axe
  // reports `color-contrast` as *incomplete* -- neither pass nor violation --
  // when it cannot resolve a background, which is what happens for every node
  // on an unstyled page. So a run with no stylesheet produces zero violations
  // and zero passes, and only this line can tell it from a clean console.
  // Measured at 812 passing nodes today; commenting out `index.css` in
  // `vitest.setup.browser.ts` and `.storybook/preview.tsx` together is what
  // fails it.
  expect(result.contrastNodesPassed).toBeGreaterThan(600)

  // Every WCAG A/AA rule other than contrast passes across all 91 stories, and
  // that is a real result rather than an empty one: axe's default rule set is
  // strongest at exactly the things this console has a lot of -- ARIA
  // attributes on Radix primitives, `aria-labelledby` targets that must exist,
  // button and link names, roles that must contain particular children.
  expect(result.otherViolations).toEqual([])

  // Exact, in both directions. A new failing pair fails here; so does *fixing*
  // one without deleting its entry, which is how the inventory stays a record
  // of what is true rather than a list of what was once true.
  expect([...result.contrastPairs].sort()).toEqual([...KNOWN_CONTRAST_DEBT].sort())
})

/** The premise of the one disabled rule, asserted rather than trusted.
 *
 * `scrollable-region-focusable` is switched off above on the grounds that
 * Chromium puts a scroll container in the tab order with no `tabindex` of its
 * own. This drives real Tab presses to check that, so the disable is tied to a
 * measurement that can expire. If Chromium ever stops doing it, this fails and
 * the answer is to re-enable the rule -- not to relax this.
 *
 * Would this pass with the change reverted? There is nothing to revert: it
 * asserts a browser behaviour, not this repository's code. What it fails on is
 * a Chromium release, or a `Pane` that stops being a scroll container.
 */
it('a scroll container is reachable without a tabindex', async () => {
  const Open = (composeStories(paneStories) as unknown as Record<string, React.ComponentType>).Open!

  const host = document.createElement('div')
  document.body.append(host)
  try {
    render(<Open />, { container: host })

    const body = host.querySelector<HTMLElement>('.lay-pane-body')!
    // The premise behind the premise: axe only raises the rule on a region that
    // actually scrolls, and this assertion is what keeps the test honest if the
    // story's content ever shrinks to fit.
    expect(body.scrollHeight).toBeGreaterThan(body.clientHeight)
    expect(body.hasAttribute('tabindex')).toBe(false)

    await userEvent.tab()
    expect(document.activeElement).toBe(body)
  } finally {
    host.remove()
  }
})

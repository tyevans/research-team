import { render } from '@testing-library/react'
import { expect, it } from 'vitest'

import composerCss from '../../styles/composer.css?raw'
import courseCss from '../../styles/course.css?raw'
import treeCss from '../../styles/tree.css?raw'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import { ContainerProvider } from '@app/container-context.tsx'
import { SessionId } from '@domain/shared/identifier.ts'

import { buildContainer } from '../../test/container.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { AutonomyPanel } from '../shell/AutonomyPanel.tsx'
import { Chip } from './primitives.tsx'
import { Drawer } from './Drawer.tsx'

/** That four shell-reached surfaces keep their dressing when the stylesheets
 *  they used to get it from are gone.
 *
 * **The hazard, stated once.** `docs/reports/stylesheet-orphan-sweep.md`
 * inverted the usual question — not "what does this stylesheet dress" but "what
 * dresses the components that outlive every view" — and found `.drawer*` and
 * the five gate-severity chip tones in `course.css`, `.chip`'s base in
 * `tree.css`, and `.btn-quiet` in `composer.css`. All four are written by
 * components the shell renders on every route, and all three stylesheets are on
 * the die-with-its-screen list. Deleting one would have unstyled something
 * still on screen with **nothing failing**: jsdom applies no stylesheet, so no
 * test could see it, and a class that resolves to nothing raises no error.
 *
 * **Why this suite and not jsdom.** Every assertion below is a computed style.
 * In jsdom `getComputedStyle` returns what an inline style said and nothing a
 * rule contributed, so each one would read `''` whether the dressing exists,
 * does not exist, or exists and loses — the three states this file separates.
 *
 * **How the hazard itself is expressed**, since a test that merely measures
 * today's pixels would go on passing after `course.css` was deleted and prove
 * nothing: the last case removes every rule those three files contribute from
 * the live document and re-measures. That is the route merge, simulated. It is
 * the case that would have caught this, and the one to keep if any are dropped.
 *
 * `.btn-quiet` is the one finding with no case here, and deliberately: it could
 * not become utilities and moved to `shell.css` instead — `shell.css` argues
 * why — so what holds it is `check-deleted.mjs` forbidding the name anywhere
 * else under `src/styles/`, not a measurement. Said rather than left as a gap.
 *
 * Every case here was proved red before being trusted green; the commit message
 * and `docs/reports/rescue-shell-reached-styles.md` record what each
 * neutralisation produced.
 */

/** Every top-level selector the three doomed stylesheets declare.
 *
 * Read from the files with `?raw` rather than written out here: the simulation
 * has to stay faithful when somebody edits one of them, and a copied list of
 * selectors is exactly the thing that goes stale in silence.
 *
 * Depth-zero rules only, at-rules skipped whole. None of these three files
 * contains a media query today — `responsive.css` owns every one in this
 * console — so nothing is quietly missed; a `@media` appearing in one of them
 * would make this simulation optimistic rather than wrong, which is the safer
 * direction for a check whose failure mode is crying wolf.
 */
const selectorsDeclaredIn = (css: string): string[] => {
  const source = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const selectors: string[] = []
  let depth = 0
  let start = 0
  for (let i = 0; i < source.length; i += 1) {
    const char = source[i]
    if (char === '{') {
      if (depth === 0) {
        const prelude = source.slice(start, i).trim()
        if (prelude && !prelude.startsWith('@')) selectors.push(prelude)
      }
      depth += 1
    } else if (char === '}') {
      depth -= 1
      if (depth === 0) start = i + 1
    }
  }
  return selectors
}

/** `.a,.b` and `.a, .b` are one rule; the CSSOM spells it the second way and a
 *  stylesheet may spell it either. */
const normalise = (selector: string) =>
  selector
    .split(',')
    .map((part) => part.replace(/\s+/g, ' ').trim())
    .sort()
    .join(',')

/** Run `body` as though `course.css`, `tree.css` and `composer.css` had been
 *  deleted with the screens they dress — which is what the route merge does.
 *
 * **Why not `sheet.disabled`.** Vite compiles the whole `index.css` chain into
 * one stylesheet — measured at 777 rules, Tailwind's `@layer utilities` block
 * and `theme.css`'s tokens included — so switching a sheet off takes the
 * utilities and the palette with it and proves nothing at all. Removing the
 * rules these three files contribute is the only separation that exists in the
 * document.
 *
 * Rules go back at their original indices afterwards: the browser suite shares
 * one document across the cases in a file, and a case that left the page
 * unstyled would silently change every case after it.
 */
const asIfDeleted = (body: () => void) => {
  const doomed = new Set(
    [courseCss, treeCss, composerCss].flatMap(selectorsDeclaredIn).map(normalise),
  )

  const sheet = [...document.styleSheets].find((candidate) => {
    // Reading `cssRules` on a cross-origin sheet throws; ours is inline, so a
    // throw means "not the one".
    try {
      return [...candidate.cssRules].some((rule) => /--rail-w/.test(rule.cssText))
    } catch {
      return false
    }
  })
  expect(sheet, 'the project stylesheet is not in the document').toBeDefined()

  const removed: { index: number; cssText: string }[] = []
  for (let i = sheet!.cssRules.length - 1; i >= 0; i -= 1) {
    const rule = sheet!.cssRules[i]!
    if (!(rule instanceof CSSStyleRule)) continue
    if (!doomed.has(normalise(rule.selectorText))) continue
    removed.push({ index: i, cssText: rule.cssText })
    sheet!.deleteRule(i)
  }
  // If this fires, the parse stopped matching the files and the simulation had
  // become a no-op that passes — the exact way a test like this rots into
  // reassurance. The three files carry several hundred rules between them; 50
  // is a floor low enough never to fire on ordinary editing.
  expect(removed.length, 'no view-stylesheet rule was removed').toBeGreaterThan(50)

  try {
    body()
  } finally {
    for (const { index, cssText } of [...removed].reverse()) sheet!.insertRule(cssText, index)
  }
}

const drawer = () => document.querySelector('.drawer')!
const drawerBody = () => document.querySelector('[data-drawer="body"]')!

it('draws the drawer as a fixed, right-anchored panel with a surface of its own', () => {
  render(
    <OverlayHost>
      <Drawer heading="Worker" label="Worker detail" onClose={() => {}}>
        body
      </Drawer>
    </OverlayHost>,
  )

  const style = getComputedStyle(drawer())
  expect(style.position).toBe('fixed')
  // 42vw of the 1440px viewport `vite.config.ts` sets, under the 640px cap —
  // 604.8px. Asserted as a number because `w-[42vw]` computes to pixels, and
  // asserted at all because it is the one value that shows the panel is still
  // viewport-relative rather than pinned at its cap.
  expect(Number.parseFloat(style.width)).toBeCloseTo(604.8, 1)
  expect(style.borderLeftWidth).toBe('1px')
  expect(style.borderLeftStyle).toBe('solid')
  expect(style.display).toBe('flex')
  expect(style.flexDirection).toBe('column')
  expect(style.overflow).toBe('hidden')
  // Not `transparent`: a drawer with no surface shows the page through it,
  // which is the most visible half of what deleting `course.css` would cost.
  expect(style.backgroundColor).toBe('rgb(17, 20, 24)')

  const box = drawer().getBoundingClientRect()
  expect(box.right).toBeCloseTo(window.innerWidth, 0)
  expect(box.top).toBe(0)
  expect(box.height).toBeCloseTo(window.innerHeight, 0)
})

it('insets the drawer body, and stops when the caller brings its own', () => {
  // Task #42's fix, which this had to preserve rather than re-derive: the
  // horizontal inset is the head's 12px so the heading and the first line under
  // it read as one column.
  const { rerender } = render(
    <OverlayHost>
      <Drawer heading="Worker" label="Worker detail" onClose={() => {}}>
        body
      </Drawer>
    </OverlayHost>,
  )
  expect(getComputedStyle(drawerBody()).padding).toBe('10px 12px 16px')

  rerender(
    <OverlayHost>
      <Drawer heading="Worker" label="Worker detail" onClose={() => {}} flush>
        body
      </Drawer>
    </OverlayHost>,
  )
  expect(getComputedStyle(drawerBody()).padding).toBe('0px')
})

it('gives a chip its shape from the primitive rather than from the landing view', () => {
  const { container } = render(<Chip>held</Chip>)
  const style = getComputedStyle(container.firstElementChild!)

  expect(style.fontSize).toBe('10.5px')
  expect(style.borderRadius).toBe('3px')
  expect(style.borderTopWidth).toBe('1px')
  expect(style.whiteSpace).toBe('nowrap')
  // 1px block, `--space-2` inline. The asymmetry is the chip's proportion and
  // is what rounding either value to a scale step would quietly lose.
  expect(style.padding).toBe('1px 6px')
  expect(style.color).toBe('rgb(167, 177, 189)')
})

it('lets a view tone still in a stylesheet override the primitive base', () => {
  // The single assumption the whole change rests on, checked rather than
  // reasoned. `theme.css` imports Tailwind into `layer(utilities)`; this
  // repository's stylesheets are unlayered; unlayered beats layered regardless
  // of specificity or order. So `.chip-fork` in `tree.css` goes on winning over
  // a utility-based base exactly as it won over the base rule that used to sit
  // beside it. If this were wrong, every chip in the console changed colour.
  const { container } = render(<Chip tone="fork">forked</Chip>)
  const style = getComputedStyle(container.firstElementChild!)

  expect(style.color).toBe('rgb(167, 139, 250)') // --k-session, not --fg-dim
  expect(style.backgroundColor).toBe('rgb(26, 22, 48)') // --tint-session
  // …while everything the tone does not mention still comes from the base.
  expect(style.borderRadius).toBe('3px')
  expect(style.fontSize).toBe('10.5px')
})

it('survives the route merge: the dressing holds with the view stylesheets deleted', () => {
  // The regression that ships otherwise, expressed directly. Every rule
  // `course.css`, `tree.css` and `composer.css` contribute is removed from the
  // live document, and the rescued surfaces are re-measured. Before this commit
  // the drawer would have been static and transparent, the chip unbordered body
  // text at inherited size, and the severities one undifferentiated grey.
  const { container } = render(
    <OverlayHost>
      <Drawer heading="Worker" label="Worker detail" onClose={() => {}}>
        <Chip>plain</Chip>
        <Chip dress="text-k-failure border-tint-fail-line bg-tint-fail">invariant</Chip>
        <Chip dress="text-accent border-accent-dim bg-tint-held">blocking</Chip>
      </Drawer>
    </OverlayHost>,
  )
  // `container` holds the host, not the layer — `Overlay` portals its content —
  // so the chips are found through the document like the drawer is.
  expect(container).toBeTruthy()

  asIfDeleted(() => {
    const panel = getComputedStyle(drawer())
    expect(panel.position).toBe('fixed')
    expect(panel.backgroundColor).toBe('rgb(17, 20, 24)')
    expect(Number.parseFloat(panel.width)).toBeCloseTo(604.8, 1)
    expect(getComputedStyle(drawerBody()).padding).toBe('10px 12px 16px')

    const chip = (label: string) =>
      [...document.querySelectorAll('.drawer span')].find((node) => node.textContent === label)!

    // The shape holds for all three…
    for (const label of ['plain', 'invariant', 'blocking']) {
      const style = getComputedStyle(chip(label))
      expect(style.borderRadius, label).toBe('3px')
      expect(style.padding, label).toBe('1px 6px')
      expect(style.fontSize, label).toBe('10.5px')
    }
    // …and the severities are still three distinguishable things rather than
    // the one grey a deleted `course.css` would have left.
    expect(getComputedStyle(chip('invariant')).color).toBe('rgb(244, 115, 107)') // --k-failure
    expect(getComputedStyle(chip('blocking')).color).toBe('rgb(226, 164, 87)') // --accent
    expect(getComputedStyle(chip('plain')).color).toBe('rgb(167, 177, 189)') // --fg-dim
  })
})

/** The fifth surface, added when `AutonomyPanel` moved out of the project
 *  page's queue header and behind the chrome's lock.
 *
 * It is the same finding as the four above, found the same way and one screen
 * later: the panel took fifteen `.autonomy-*` rules from `course.css` with it
 * into a dialog reachable on every route. Its rules are utilities now, and this
 * is the measurement that says so — the two that carry meaning rather than
 * merely looking tidy.
 *
 * **The scope warning's 2px accent edge** is the one thing in the panel that
 * must not be quiet: a reader skimming past it and flipping a switch that
 * changes every session on the instance is the failure the whole panel is
 * shaped around. **The row's single top rule** is the `border-solid` hazard
 * `CLAUDE.md` records: `border-0` beside `border-t` is both halves of one fix,
 * and dropping the zero draws a box on every row.
 */
const renderPanel = () => {
  const policy = { levels: new Map([['fetch', 'ask']]), gated: ['fetch'] }
  const container = buildContainer({
    autonomy: {
      read: () => Promise.resolve(policy),
      setLevel: () => Promise.resolve(policy),
      allowAll: () => Promise.resolve({ changed: new Map(), policy }),
    },
  })

  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })}
    >
      <ContainerProvider container={container}>
        <AutonomyPanel sessionId={SessionId('22222222-2222-2222-2222-222222222222')} />
      </ContainerProvider>
    </QueryClientProvider>,
  )
}

it('keeps the autonomy panel dressed without the stylesheet it came from', async () => {
  const { findByText } = renderPanel()
  const row = (await findByText('fetch')).closest('li')!
  const warn = [...document.querySelectorAll('p')].find((node) =>
    node.textContent?.startsWith('This applies to every session'),
  )!

  const measure = () => {
    const edge = getComputedStyle(warn)
    // The loudest line in the panel: 2px, accent, and only on the left.
    expect(edge.borderLeftWidth).toBe('2px')
    expect(edge.borderLeftStyle).toBe('solid')
    expect(edge.borderLeftColor).toBe('rgb(226, 164, 87)') // --accent
    expect(edge.borderTopWidth).toBe('0px')
    expect(edge.borderRightWidth).toBe('0px')

    const rule = getComputedStyle(row)
    // One rule, on top. The three sides `border-0` zeroes are what the
    // browser's `medium` default would otherwise draw at ~3px each.
    expect(rule.borderTopWidth).toBe('1px')
    expect(rule.borderTopStyle).toBe('solid')
    expect(rule.borderBottomWidth).toBe('0px')
    expect(rule.borderLeftWidth).toBe('0px')
    expect(rule.borderRightWidth).toBe('0px')
    // The fieldset's own chrome is off: the row is the frame.
    expect(getComputedStyle(row.querySelector('fieldset')!).borderTopWidth).toBe('0px')
  }

  measure()
  // And again with `course.css` gone, which is the state this move created.
  asIfDeleted(measure)
})

/** The layout constants, for the half of the layout that is JavaScript.
 *
 * `tokens.css` holds the same numbers as CSS custom properties and is the
 * source a stylesheet reads. Neither language can read the other's, so the two
 * declarations are unavoidable; what is avoidable is them drifting, and
 * `scripts/theme.test.ts` fails if any value here disagrees with its
 * `--bp-*` / `--rail-w` counterpart.
 *
 * Rejected: reading the values at runtime with `getComputedStyle`, which
 * `entity-colors.ts` already does for the event-kind colours, so there is
 * precedent. It gives one true source and costs the tests everything --
 * `vitest.setup.ts` stubs layout precisely because jsdom computes none, so a
 * `Split` reading its breakpoint that way would see an empty string in every
 * test and could not be tested at all. A checked duplicate is worth more than
 * an unverifiable single source.
 */

/** Widths at which the layout changes shape, in pixels.
 *
 * These are the *min-width* side of each boundary, which is why they are odd
 * numbers: `responsive.css` asks `max-width: 1180px` and `use-panes.ts` asks
 * `min-width: 1181px` about the same line. `matchMedia` needs the min-width
 * form, and a stylesheet can express either, so the min-width value is the one
 * kept and the stylesheet side is written as `not all and (min-width: …)`. */
export const BREAKPOINTS = {
  /** Three columns above this. Below it the panes reflow to two. */
  wide: 1181,
  /** Above this the surface owns the viewport and its regions scroll
   *  individually. Below it the surface becomes a single scrolling column --
   *  a declared mode rather than `responsive.css`'s override of `body`. */
  narrow: 821,
  /** Where chrome starts dropping fields rather than wrapping. */
  tight: 561,
} as const

export type Breakpoint = keyof typeof BREAKPOINTS

/** The media query a `matchMedia` call should ask for a breakpoint.
 *
 * One function rather than a query written at each call site: the console
 * currently spells the same boundary two ways in two languages, and the
 * spelling is where the off-by-one lives. */
export const atLeast = (breakpoint: Breakpoint) =>
  `(min-width: ${String(BREAKPOINTS[breakpoint])}px)`

/** The collapsed pane's width, in CSS rather than pixels: it is only ever used
 *  as a grid track, and a track written as `var(--rail-w)` keeps the number in
 *  the stylesheet where a reader inspecting the layout will look for it.
 *
 *  A fixed track rather than a min-width, which is the reasoning
 *  `use-panes.ts` records and the reason collapsing is worth anything: the
 *  space a collapsed pane gives up has to go to the open ones. */
export const RAIL_TRACK = 'var(--rail-w)'

/** The same width as a number, for the one place that needs to compare it. */
export const RAIL_WIDTH_PX = 34

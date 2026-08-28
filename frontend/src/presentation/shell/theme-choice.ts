/** The reader's theme choice: what it can be, where it is kept, and how it
 *  reaches the document.
 *
 * Deliberately not a dependency. `docs/design/frontend-library-adoption.md` §1
 * argues the case against `next-themes` and it holds: that library exists to
 * prevent an SSR flash, this is a Vite SPA served from a local FastAPI process,
 * and what would be left of it here is one persisted value plus a pre-paint
 * script. Both are below.
 *
 * **This module is deliberately free of both React and the DOM**, and the
 * second half is load-bearing rather than tidy. `scripts/theme.test.ts` imports
 * these names to pin them against the inline script in `index.html`, and that
 * test runs under the `build` vitest project in a real Node with
 * `tsconfig.node.json` -- which has no `dom` lib, so a single reference to
 * `document` here fails `npm run typecheck` with an error that names the wrong
 * thing entirely ("Cannot find name 'document'"). The storage and document
 * writes live in `theme-storage.ts` next door for that reason.
 */

/** Three states, not two, and the third is the default.
 *
 * `system` is a real choice rather than the absence of one: it means "keep
 * following the desktop", including when the desktop changes at sunset. A
 * two-state control cannot express it -- it can only sample the preference
 * once and then stop tracking it -- which is why the control cycles through
 * three rather than toggling.
 *
 * The CSS half of this is in `tokens.css`: `system` and a missing attribute
 * both resolve to `color-scheme: light dark`, so the browser follows the
 * desktop and `light-dark()` follows the browser. No JavaScript reads
 * `prefers-color-scheme` at all, which is the point -- a resolved-in-JS theme
 * stops tracking the moment the listener is forgotten. */
export const THEME_CHOICES = ['system', 'light', 'dark'] as const
export type ThemeChoice = (typeof THEME_CHOICES)[number]

/** What the control says it is, for the accessible name and the tooltip.
 *
 * Full sentences rather than one-word labels, for `AutonomyLock`'s reason: the
 * control is an icon, and an icon whose only label is a tooltip is the S-D2
 * defect this console records. A screen reader gets the whole state without
 * the tooltip ever opening.
 */
export const THEME_LABELS: Readonly<Record<ThemeChoice, string>> = {
  system: 'Colour theme: following your device',
  light: 'Colour theme: light',
  dark: 'Colour theme: dark',
}

/** The next state in the cycle. Separate from the component so the order is
 *  stated once and is testable without a DOM. */
export const nextThemeChoice = (choice: ThemeChoice): ThemeChoice =>
  THEME_CHOICES[(THEME_CHOICES.indexOf(choice) + 1) % THEME_CHOICES.length]!

/** The key `localStorage` is keyed by, and the one string `index.html` also
 *  spells out. It lives on this side of the split precisely so the test that
 *  pins the two together does not have to import the DOM half. */
export const THEME_STORAGE_KEY = 'rt.theme'

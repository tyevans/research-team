import { THEME_CHOICES, THEME_STORAGE_KEY, type ThemeChoice } from './theme-choice.ts'

/** The two side effects a theme choice has: it is remembered, and it is written
 *  onto the document.
 *
 * Split from `theme-choice.ts` rather than living beside the names it uses, and
 * the reason is stated there: the build-time test that pins `index.html`'s
 * inline script against `THEME_STORAGE_KEY` runs in a Node with no `dom` lib,
 * so the names have to be reachable without dragging `document` in.
 */

const isChoice = (value: unknown): value is ThemeChoice =>
  typeof value === 'string' && (THEME_CHOICES as readonly string[]).includes(value)

/** The stored choice, or `system`.
 *
 * `localStorage` is wrapped because it throws rather than returning null in a
 * browser with site data disabled, and a console that will not boot because
 * somebody hardened their browser is a worse outcome than a console that
 * forgets which theme they picked.
 */
export const readThemeChoice = (): ThemeChoice => {
  try {
    const stored: unknown = localStorage.getItem(THEME_STORAGE_KEY)
    return isChoice(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

export const writeThemeChoice = (choice: ThemeChoice): void => {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, choice)
  } catch {
    // See above. The theme still applies for this page load.
  }
}

/** The attribute the stylesheet reads. Written even for `system`, rather than
 *  removed: `tokens.css` matches `:root` and `:root[data-theme='system']` with
 *  the same rule so both work, but `theme.css`'s `dark:` variant can only match
 *  an attribute that is present. Leaving it off would make every `dark:`
 *  utility inert for the default setting -- which nothing uses today, and which
 *  is exactly the sort of thing that is discovered a year later. */
export const applyThemeChoice = (choice: ThemeChoice): void => {
  document.documentElement.setAttribute('data-theme', choice)
}

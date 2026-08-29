import { setProjectAnnotations } from '@storybook/react-vite'

import '@testing-library/jest-dom/vitest'

import preview from './.storybook/preview.tsx'

import './src/styles/index.css'

/** The browser suite's setup, and it is a *subset* of `vitest.setup.ts` rather
 *  than an import of it.
 *
 * The two things it keeps are the two that are about the application:
 * `setProjectAnnotations` so a composed story renders the same tree here as in
 * the workbench, and `jest-dom`'s matchers.
 *
 * Everything else in the jsdom setup is a stub *for* jsdom, and taking those
 * along would defeat the suite. The last two lines there are the clearest case:
 *
 * ```
 * Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { value: 600 })
 * Object.defineProperty(HTMLElement.prototype, 'offsetWidth',  { value: 800 })
 * ```
 *
 * Unconditional, so in a real engine they would replace measured layout with
 * two constants -- every element 800x600, in the one suite whose whole purpose
 * is to measure. The `matchMedia` and `getBoundingClientRect` stubs are guarded
 * by `if (!...)` and so would be inert here, but relying on that guard would
 * make this file's correctness depend on a detail of the other one. A separate
 * file states the intent: the browser suite stubs nothing.
 *
 * `index.css` is imported here **and** by `.storybook/preview.tsx`, which
 * `setProjectAnnotations` above pulls in — so today this line changes nothing,
 * and commenting it out leaves the suite green. It was written believing it was
 * load-bearing and kept once it turned out not to be, for one reason: a suite
 * that asserts on colour must not get its stylesheet as a side effect of a
 * decorator list it does not control. The preview exists to configure the
 * workbench, and the day somebody moves that import into a Storybook-only entry
 * point, every assertion here would start measuring an unstyled page and still
 * pass — `getComputedStyle` returns the user agent's answer perfectly
 * confidently. Duplicate imports of one CSS module cost nothing; this one buys
 * independence from a file with a different job.
 */
setProjectAnnotations(preview)

/** The suite runs dark unless a test says otherwise, and this line is the only
 *  thing that makes that true.
 *
 * Before light mode there was nothing to declare: `tokens.css` hard-coded
 * `color-scheme: dark` and every colour token had one value. Now the scheme
 * follows `data-theme`, a document with none of its own falls through to
 * `color-scheme: light dark`, and **the headless browser's own preference is
 * light** -- measured 2026-08-28. So without this, six existing files that pin
 * a colour as an `rgb()` literal (`Tabs`, `shell-reached-dressing`,
 * `TruncatedText`, `flashcards`, `lesson-focus`, `resolved-frame-dressing`)
 * would start measuring the light palette against dark expectations, and would
 * fail for a reason that has nothing to do with what they assert.
 *
 * Dark rather than light because dark is what those assertions were written
 * against and what the console has always been. A test that wants the other
 * scheme sets `data-theme` itself and puts it back -- `theme.browser.test.tsx`
 * and `a11y.browser.test.tsx` both do, and both restore it, because this is a
 * global and a leaked value would retheme every file that runs after them.
 */
document.documentElement.setAttribute('data-theme', 'dark')

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

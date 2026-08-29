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

/** Wait for the stylesheet to have actually arrived, before any test measures
 *  anything against it.
 *
 * **This is the fix for the class of failure B184 describes, and it is what
 * lets a suite about computed styles be trusted at all.** Each test file gets
 * its own iframe and re-imports `index.css`, which is a chain of `@import`s
 * served by one dev server. Sometimes the first assertion in a file runs
 * against a sheet that is only partly applied -- and a partly-applied sheet is
 * indistinguishable, to `getComputedStyle`, from a rule that is wrong.
 *
 * Measured on 2026-08-29: `aspect-ratio: auto` where a `course.css` rule
 * declares `3 / 2`; `opacity: 1` where `opacity-0` is in the class attribute;
 * `border-box` where `box-content` is; and `--fg` where `text-accent` is -- the
 * last with the *token* resolving, so that time it was `@layer utilities` alone
 * that was missing. Every one of those rules is present in `npm run build`.
 *
 * Two probes rather than one, because the failures come in both flavours: a
 * rule from this repository's own stylesheets (`markdown.css`'s `.md`) and a
 * rule from `@layer utilities` (Tailwind's `opacity-0`). Either can be the one
 * that has not landed, and waiting on one would not see the other.
 *
 * It throws rather than continuing past the deadline, deliberately: a timeout
 * means the sheet genuinely is not being served, and every assertion in the
 * file that follows would be a confident measurement of an unstyled page. A
 * named failure at setup is the readable form of that.
 *
 * What it does not do is make the seam correct. The sheet still arrives when it
 * arrives, and a test running long after setup could in principle still meet a
 * later `@import` mid-flight. B184 carries the two proper fixes -- serve the
 * built stylesheet, or block on the sheet rather than on a probe of it. This is
 * the cheap one, and it turns a wrong measurement into a wait.
 */
const probe = document.createElement('div')
probe.className = 'md opacity-0'
probe.setAttribute('aria-hidden', 'true')
probe.style.position = 'fixed'
document.body.appendChild(probe)

/** `.md` sets `padding: 10px 14px 40px` and `opacity-0` sets `opacity: 0`.
 *  Neither is a value a bare `<div>` takes from anything else in this tree. */
const dressed = () => {
  const style = getComputedStyle(probe)
  return style.paddingTop === '10px' && style.opacity === '0'
}

const DEADLINE_MS = 10_000
const startedAt = performance.now()
while (!dressed()) {
  if (performance.now() - startedAt > DEADLINE_MS) {
    const style = getComputedStyle(probe)
    throw new Error(
      `vitest.setup.browser: index.css did not apply within ${DEADLINE_MS}ms ` +
        `(padding-top ${style.paddingTop}, opacity ${style.opacity}). Every ` +
        `assertion in this file would have measured an unstyled page. See B184.`,
    )
  }
  await new Promise((resolve) => requestAnimationFrame(resolve))
}

probe.remove()

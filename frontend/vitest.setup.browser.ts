import { setProjectAnnotations } from '@storybook/react-vite'

import '@testing-library/jest-dom/vitest'

import preview from './.storybook/preview.tsx'

import indexCss from './src/styles/index.css?inline'

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
 * `index.css` is imported here `?inline` and injected below, which is B184's
 * fix rather than a stylistic choice; the block over that injection carries the
 * measurement. It is also imported for its side effect by
 * `.storybook/preview.tsx`, which `setProjectAnnotations` above pulls in -- and
 * that copy is now the redundant one, kept because the preview exists to
 * configure the workbench and this file must not depend on what a decorator
 * list it does not control happens to import. Two copies of one stylesheet cost
 * nothing: the rules are identical, so whichever the cascade reads last resolves
 * to the same value.
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

/** Inject the whole stylesheet as one string, before any test measures
 *  anything against it.
 *
 * **This is the fix for B184, and it replaces a probe that waited on the
 * defect rather than removing it.**
 *
 * What was wrong: `index.css` is a chain of 21 `@import`s, each served
 * separately by one dev server, and each test file gets its own iframe that
 * re-requests the chain. A test could run against a sheet that had arrived
 * only in part -- and a partly-applied sheet is indistinguishable, to
 * `getComputedStyle`, from a rule that is wrong. B184 has the measurements:
 * `aspect-ratio: auto` where `course.css` declares `3 / 2`, `opacity: 1` where
 * `opacity-0` is in the class attribute, `--fg` where `text-accent` is.
 *
 * `?inline` returns the *transformed* stylesheet as a string, so Vite has
 * already resolved every `@import` and Tailwind has already generated
 * `@layer utilities` by the time this module has a value. Measured on
 * 2026-09-03: 109,479 characters, **zero** occurrences of `@import`, and
 * `.crs-card-art`, `#root`, `opacity-0` and `@layer` all present. One module,
 * fetched atomically -- there is no longer a partial state for a test to
 * observe, which is the property the old probe could only wait for and never
 * guarantee.
 *
 * Why the previous mitigation was not enough, and this is the evidence that
 * sent it back: it waited on `structure.css`'s `#root { display: contents }`
 * on the reasoning that it is the last of the 21 imports, "so anything earlier
 * in the chain has necessarily arrived". That does not hold. In three
 * consecutive CI runs -- `main` on 2026-09-01 and this branch twice on
 * 2026-09-03 -- **the probe passed and `course-card-sizing`'s aspect case
 * still read `auto`**: `course.css` is import 25 of 51 lines and
 * `structure.css` is 51, so the later one applied while the earlier one had
 * not. The chain does not arrive in source order.
 *
 * The cost: this file now decides the stylesheet, where the sheet used to be a
 * side effect of an import. That is the point -- see the block at the top of
 * this file -- but it means a rule that reaches the browser only through some
 * path other than `index.css` is invisible here, where before it would at
 * least have raced in.
 *
 * What a test would fail on: delete these three lines and the check below
 * throws, naming this entry. Every `*.browser.test.tsx` assertion is a
 * computed style or a measurement, so an unstyled page is not a suite that
 * fails a little -- it is a suite whose every reading is the user agent's
 * default, reported perfectly confidently. */
const sheet = document.createElement('style')
sheet.textContent = indexCss
document.head.appendChild(sheet)

/** And then check it, synchronously, rather than wait for it.
 *
 * A wait would be dishonest now: the sheet is a string this module already
 * holds, appended to `document.head` above, and `getComputedStyle` forces the
 * style recalculation itself. If these two values are not right on the first
 * read they are not going to become right on the second, so a deadline would
 * only delay the same failure by ten seconds.
 *
 * Two probes rather than one, kept from the version this replaces, because the
 * two misses B184 records come from different halves of the pipeline: a rule
 * from this repository's own stylesheets (`structure.css`'s
 * `#root { display: contents }`) and one from `@layer utilities`, which
 * Tailwind generates separately from a scan of the source tree and which can
 * be absent while every hand-written rule is present. B160's `--fg` reading is
 * that second case -- the *token* resolved, so `tokens.css` had applied and
 * only the utilities layer had not. Checking one would not see the other.
 *
 * It throws rather than continuing, deliberately, and that is unchanged: a
 * named failure at setup is the readable form of "every assertion in this file
 * would have measured an unstyled page". */
const probe = document.createElement('div')
// `#root` rather than a class, because the rule being checked is written
// against that id. The application's own root is mounted by a test's `render`,
// not by this file, so there is no clash.
probe.id = 'root'
probe.className = 'opacity-0'
probe.setAttribute('aria-hidden', 'true')
document.body.appendChild(probe)

const style = getComputedStyle(probe)
const display = style.display
const opacity = style.opacity
probe.remove()

if (display !== 'contents' || opacity !== '0') {
  throw new Error(
    `vitest.setup.browser: the injected index.css did not apply ` +
      `(display ${display}, opacity ${opacity}). Every assertion in this file ` +
      `would have measured an unstyled page. See B184.`,
  )
}

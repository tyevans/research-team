import { setProjectAnnotations } from '@storybook/react-vite'

import '@testing-library/jest-dom/vitest'

import preview from './.storybook/preview.tsx'

/** The workbench's own configuration, applied to every test that composes a
 *  story.
 *
 * `composeStories` does not read `.storybook/preview` by itself. Without this
 * line the preview's decorators and parameters exist in the browser and
 * nowhere else, so a story and the test that imports it render *different
 * trees* — and the difference is invisible, because both render something.
 *
 * That is not hypothetical here. The preview mounts an `OverlayHost`, and a
 * `Tooltip` with no host renders no content at all: without this, every
 * explanation would appear in the workbench and vanish in the tests that
 * assert on it, which is the shape of the defect #128 repaired. It is
 * deliberately in the setup file rather than in each test — the alternative is
 * a rule every future test file has to know, and the one that forgets is the
 * one that fails silently.
 *
 * The cost is that the preview is now load-bearing for the suite: a decorator
 * added there wraps several hundred existing tests. That is the point, and it
 * is also the reason the preview's decorator list should stay short and be
 * argued for where it is written.
 */
setProjectAnnotations(preview)

/** jsdom implements neither of these, and both are load-bearing in the console:
 *  the pane layout asks whether the three-column breakpoint is active, and the
 *  timeline scrolls the selected row into view on every render. Stubbing them
 *  here keeps every component test from having to know that. */
if (!window.matchMedia) {
  window.matchMedia = (query: string) =>
    ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as MediaQueryList
}

if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {}
}

/** jsdom lays out nothing, so every element reports a zero-height rect --
 *  and `useVirtualizer` (the document list) sizes its visible window off
 *  that rect. Left alone, every virtualized test would see a scroll
 *  container with no height and render nothing to assert on. A fixed
 *  height here is the same trade `matchMedia` above makes: real layout is
 *  Playwright's job, not jsdom's. */
if (!window.ResizeObserver) {
  window.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
}
if (!Element.prototype.getBoundingClientRect) {
  Element.prototype.getBoundingClientRect = (): DOMRect => ({
    width: 800,
    height: 600,
    top: 0,
    left: 0,
    bottom: 600,
    right: 800,
    x: 0,
    y: 0,
    toJSON: () => ({}),
  })
}
// `react-virtual` sizes the scroll container off `offsetWidth`/`offsetHeight`
// rather than the rect above, and jsdom never lays either out. `HTMLElement`,
// not `Element`, is what actually defines these in jsdom, and it sits closer
// than `Element` in the prototype chain -- overriding `Element` alone is
// silently shadowed.
Object.defineProperty(HTMLElement.prototype, 'offsetHeight', { configurable: true, value: 600 })
Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, value: 800 })

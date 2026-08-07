import '@testing-library/jest-dom/vitest'

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

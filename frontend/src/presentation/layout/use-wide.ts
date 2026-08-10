import { useCallback, useSyncExternalStore } from 'react'

import { atLeast, type Breakpoint } from './layout-tokens.ts'

/** Whether the viewport is at or above a named breakpoint.
 *
 * A subscription, which the props-only rule forbids inside an entity
 * component — and this is not one. The rule exists so that a component's
 * output is a function of its props and can therefore be enumerated by a
 * story; the viewport is not application state, it is the medium, and a layout
 * primitive that could not observe it would push the observation into every
 * view instead.
 *
 * `useSyncExternalStore` rather than `useState` + `useEffect`, which is how
 * `use-panes.ts` does it today. Two reasons, and the second is why the lint
 * rule that rejected the first draft of this file is right: the effect version
 * has to `setState` on subscribe to catch a breakpoint crossed between render
 * and effect, which is a synchronous state update inside an effect and a
 * cascading render; and it renders once with a guessed value before
 * correcting itself, which is a flash of the wrong layout on first paint.
 * `useSyncExternalStore` reads the store during render and cannot tear.
 *
 * `matchMedia` rather than a resize listener: it fires on the transition
 * rather than on every pixel, so nothing recomputes while a window is dragged
 * through a range where the answer does not change.
 *
 * jsdom does not implement it. `vitest.setup.ts` stubs it to answer `false` to
 * everything, so under test this hook always reports "not wide" unless a test
 * replaces the stub — which is exactly why `splitTemplate` is a separate pure
 * function and why the assertions that matter live there rather than here.
 */
export const useWide = (breakpoint: Breakpoint): boolean => {
  const query = atLeast(breakpoint)

  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = window.matchMedia?.(query)
      if (!list) return () => {}
      list.addEventListener('change', onChange)
      return () => list.removeEventListener('change', onChange)
    },
    [query],
  )

  const read = useCallback(() => window.matchMedia?.(query).matches ?? true, [query])

  // Server snapshot is the same function: this console has no server rendering
  // and never will — it is a single-page application served as static files —
  // so a divergent server value would describe a situation that cannot arise.
  return useSyncExternalStore(subscribe, read, read)
}

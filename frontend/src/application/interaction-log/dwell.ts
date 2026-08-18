/** How long a view was current, and how much of that the tab was hidden for.
 *
 * `performance.now()` rather than `Date.now()`: monotonic, so a system clock
 * moved mid-session cannot produce a negative or absurd duration. The
 * emitter's `occurred_at` still comes from the wall clock, because that one
 * is for a human reading rows.
 */

import type { Emitter } from './emitter.ts'

export interface DwellTracker {
  enter(view: string, params?: Readonly<Record<string, unknown>>): void
  exit(): void
  /** Subscribe to the page lifecycle. Returns the unsubscribe. */
  attach(): () => void
}

export const createDwellTracker = ({
  emitter,
  clock = () => performance.now(),
}: {
  emitter: Emitter
  clock?: () => number
}): DwellTracker => {
  let view: string | null = null
  let enteredAt = 0
  let hiddenMs = 0
  let hiddenSince: number | null = null

  const exit = () => {
    if (view === null) return
    if (hiddenSince !== null) {
      hiddenMs += clock() - hiddenSince
      hiddenSince = null
    }
    emitter.record('ViewExited', {
      dwell_ms: Math.round(clock() - enteredAt),
      hidden_ms: Math.round(hiddenMs),
    })
    view = null
  }

  const onVisibility = () => {
    if (document.visibilityState === 'hidden') {
      hiddenSince = clock()
      emitter.record('AttentionLost')
      return
    }
    // Only when something was actually lost. A `visibilitychange` to visible
    // with no preceding hide is common -- some browsers fire one on initial
    // load, and a tracker attached while the tab is already visible sees it --
    // and an unguarded emit puts an unpaired `AttentionRegained` in the log.
    // The arithmetic above is unaffected either way, which is exactly why this
    // survived review of the numbers: `hidden_ms` stays correct while the raw
    // event stream, the thing this feature exists to produce, does not.
    if (hiddenSince === null) return
    hiddenMs += clock() - hiddenSince
    hiddenSince = null
    emitter.record('AttentionRegained')
  }

  const onPageHide = () => {
    // The last view of every session ends here, and it is the view most
    // likely to be the one somebody got stuck on. Beacon rather than post:
    // an in-flight fetch is cancelled on unload.
    exit()
    emitter.flushOnUnload()
  }

  return {
    enter(next, params = {}) {
      exit()
      view = next
      enteredAt = clock()
      hiddenMs = 0
      hiddenSince = document.visibilityState === 'hidden' ? clock() : null
      emitter.setContext({ view: next })
      emitter.record('ViewEntered', { params })
    },

    exit,

    attach() {
      document.addEventListener('visibilitychange', onVisibility)
      window.addEventListener('pagehide', onPageHide)
      return () => {
        document.removeEventListener('visibilitychange', onVisibility)
        window.removeEventListener('pagehide', onPageHide)
      }
    },
  }
}

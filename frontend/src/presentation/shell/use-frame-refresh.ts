import { useEffect, useRef } from 'react'

import type { FeedFrame } from '@application/ports/event-stream.ts'

import { useStream } from './StreamProvider.tsx'

/** How long to wait for the burst to end before re-reading.
 *
 * Frames arrive in clusters -- a turn commits a dozen events at once, a
 * seeding run opens eight topics in a row -- and refetching per frame would be
 * a dozen identical requests for one repaint. 400ms is long enough to collapse
 * a burst and short enough that nobody reaches for the reload button.
 */
export const FRAME_DEBOUNCE_MS = 400

/** "The log moved, re-read" -- the debounce, in one place.
 *
 * Extracted from `useTreeRefresh`, which was the only caller until the
 * research page needed the same thing for topics. The two differ only in which
 * frames they care about and what they invalidate, which is exactly what the
 * two callbacks are; keeping one implementation of the timer means a fix to
 * the burst behaviour cannot land on one screen and miss the other.
 *
 * `active` because a subscription is not free to leave running: a view that is
 * off screen refetching on every frame competes with the one that is on it.
 *
 * The callbacks are read through a ref rather than depended on, so callers can
 * pass inline lambdas. Depending on them instead would resubscribe on every
 * render, and -- worse -- the cleanup would clear the pending timer each time,
 * so a component that renders steadily under a burst would never refresh at
 * all. That is the failure a test asserting "one refetch after a burst" is
 * pinning.
 */
export const useFrameRefresh = (
  active: boolean,
  accepts: (frame: FeedFrame) => boolean,
  refresh: () => void,
): void => {
  const stream = useStream()
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const latest = useRef({ accepts, refresh })

  useEffect(() => {
    latest.current = { accepts, refresh }
  })

  useEffect(() => {
    if (!active) return
    const off = stream.onFrame((frame) => {
      if (!latest.current.accepts(frame)) return
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => latest.current.refresh(), FRAME_DEBOUNCE_MS)
    })
    return () => {
      off()
      if (timer.current) clearTimeout(timer.current)
    }
  }, [active, stream])
}

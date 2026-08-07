import { useEffect } from 'react'

import type { SessionStore } from '@application/session/session-store.ts'

import { useStream } from '../shell/StreamProvider.tsx'

/** Wire the live feed into a session's store.
 *
 * The store owns every decision about what a frame means; this only delivers
 * them. Keeping the subscription here rather than inside the store is what lets
 * the store be tested by calling `handleFrame` directly, with no connection and
 * no timers involved. */
export const useSessionStream = (store: SessionStore): void => {
  const stream = useStream()

  useEffect(() => {
    const offFrame = stream.onFrame((frame) => store.getState().handleFrame(frame))
    const offReconnect = stream.onReconnect((resumable) => {
      void store.getState().handleReconnect(resumable)
    })
    return () => {
      offFrame()
      offReconnect()
    }
  }, [store, stream])
}

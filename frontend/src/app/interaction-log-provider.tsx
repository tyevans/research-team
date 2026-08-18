/** Where the interaction log is switched on.
 *
 * One emitter per page load, since `browser_session_id` is per load and the
 * seq counter has to be shared by everything that records. Mounted above the
 * views so a route change is observed once rather than by each view.
 */

import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react'

import type { InteractionSink } from '@application/ports/interaction-log.ts'
import { createDwellTracker, type DwellTracker } from '@application/interaction-log/dwell.ts'
import { createEmitter, type Emitter } from '@application/interaction-log/emitter.ts'
import { installId, newBrowserSessionId } from '@infrastructure/storage/install-identity.ts'

/** Records nothing, fails at nothing.
 *
 * The context default, because every component test renders without the
 * provider and a throwing hook would turn one composition decision into
 * hundreds of failures. `InMemoryPreferenceStore` exists for the same
 * reason.
 */
const SILENT: Emitter = {
  record: () => {},
  setContext: () => {},
  start: () => {},
  flush: async () => {},
  flushOnUnload: () => {},
  stop: () => {},
  pending: () => 0,
}

const InteractionLogContext = createContext<Emitter>(SILENT)

// Module scope, not inline in the provider: `Date.now` reached from inside
// render trips eslint-plugin-react-hooks' purity rule even though this
// closure only *calls* it later, from `emitter.record`, never during render
// itself. Hoisting the reference out of the render body is what the rule
// wants to see; `container.ts`'s own `now: () => Date.now()` gets away with
// it only because it runs outside a component entirely.
const now = (): number => Date.now()

export const useInteractionLog = (): Emitter => useContext(InteractionLogContext)

export const InteractionLogProvider = ({
  sink,
  view,
  projectId = null,
  sessionId = null,
  children,
}: {
  sink: InteractionSink
  view: string
  projectId?: string | null
  sessionId?: string | null
  children: ReactNode
}) => {
  // A lazy `useState` initialiser, not `useMemo`. React documents a memo as a
  // hint it may discard, and this one has identity semantics: a discarded
  // emitter mints a second `browser_session_id` and restarts `seq` at 1
  // mid-page-load, which is exactly the `(browser_session_id, seq)` pair the
  // server dedupes on. State is never discarded for a mounted component, so
  // "one emitter per page load" becomes actual rather than probable -- and the
  // `[sink]` key goes with it, which was its own small hazard: a sink swapped
  // mid-load would have started a second browser session.
  //
  // A lazy ref would say the same thing and lint refuses it -- `react-hooks`'
  // `refs` rule forbids reading `.current` during render, and the read is the
  // whole point of the pattern. StrictMode calls this initialiser twice and
  // discards one result, so `installId()`/`newBrowserSessionId()` do run twice
  // per dev mount; the retained pair is still one per page load.
  const [emitter] = useState<Emitter>(() =>
    createEmitter({
      sink,
      now,
      installId: installId(),
      browserSessionId: newBrowserSessionId(),
    }),
  )

  const [dwell] = useState<DwellTracker>(() => createDwellTracker({ emitter }))

  // Cleared by a remount, which is how the teardown below tells StrictMode's
  // synthetic unmount from a real one: the remount is synchronous, so it has
  // already run by the time the queued microtask looks.
  const unmounting = useRef(false)

  useEffect(() => {
    unmounting.current = false
    // Recreates the interval a previous cleanup cleared. Without it StrictMode
    // leaves every `npm run dev` session with no timed flush at all.
    emitter.start()
    const detach = dwell.attach()
    return () => {
      detach()
      emitter.stop()
      unmounting.current = true
      // Deferred by one microtask rather than run here, and this is the ref
      // guard the brief asked for: StrictMode unmounts and remounts within the
      // same commit, so a synchronous exit-and-flush put a duplicate
      // `ViewEntered` and a spurious zero-dwell `ViewExited` into the same
      // `interactions.db` a developer reads by hand. A real unmount has no
      // remount to clear the flag, so the exit still happens -- and page close
      // does not depend on this path at all, which `dwell.ts`'s own `pagehide`
      // listener covers. Beacon rather than post: a post would race the
      // remount, and `flushOnUnload` catches internally (emitter.ts).
      queueMicrotask(() => {
        if (!unmounting.current) return
        dwell.exit()
        emitter.flushOnUnload()
      })
    }
  }, [dwell, emitter])

  // One effect, in this order, rather than a `setContext` effect and an
  // `enter` effect. `enter()` calls `exit()` internally, and `exit()` records
  // `ViewExited` against whatever context is current -- so a separate
  // `setContext` effect running first stamped every page's dwell with the ids
  // of the page the user went to *next*, and running it second stamped
  // `ViewEntered` with the ids of the page they came from. Only exit, rewrite,
  // enter gets both right.
  //
  // Guarded on the values rather than left to the dependency array, because
  // StrictMode re-invokes an effect whose dependencies did not change, and
  // that re-invoke is a second `ViewEntered` for one page load.
  const entered = useRef<string | null>(null)
  useEffect(() => {
    const key = JSON.stringify([view, projectId, sessionId])
    if (entered.current === key) return
    entered.current = key
    dwell.exit()
    emitter.setContext({ projectId, sessionId })
    dwell.enter(view)
  }, [dwell, emitter, view, projectId, sessionId])

  return <InteractionLogContext.Provider value={emitter}>{children}</InteractionLogContext.Provider>
}

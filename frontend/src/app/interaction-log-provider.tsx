/** Where the interaction log is switched on.
 *
 * One emitter per page load, since `browser_session_id` is per load and the
 * seq counter has to be shared by everything that records. Mounted above the
 * views so a route change is observed once rather than by each view.
 */

import { createContext, useContext, useEffect, useMemo, type ReactNode } from 'react'

import type { InteractionSink } from '@application/ports/interaction-log.ts'
import { createDwellTracker } from '@application/interaction-log/dwell.ts'
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
  const emitter = useMemo(
    () =>
      createEmitter({
        sink,
        now,
        installId: installId(),
        browserSessionId: newBrowserSessionId(),
      }),
    [sink],
  )

  const dwell = useMemo(() => createDwellTracker({ emitter }), [emitter])

  useEffect(() => {
    const detach = dwell.attach()
    return () => {
      detach()
      // A last flush by beacon rather than by post: this also runs on a
      // StrictMode double-invoke in development, where a post would race the
      // remount. `emitter.flushOnUnload()` catches internally (emitter.ts) --
      // that guard, not one here, is what covers `dwell.ts`'s own call to it
      // from `onPageHide`, which this provider does not go through.
      dwell.exit()
      emitter.flushOnUnload()
      emitter.stop()
    }
  }, [dwell, emitter])

  useEffect(() => {
    emitter.setContext({ projectId, sessionId })
  }, [emitter, projectId, sessionId])

  useEffect(() => {
    dwell.enter(view)
  }, [dwell, view])

  return <InteractionLogContext.Provider value={emitter}>{children}</InteractionLogContext.Provider>
}

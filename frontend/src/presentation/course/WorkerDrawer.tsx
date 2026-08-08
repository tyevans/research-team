import { useEffect, useMemo } from 'react'

import { notify } from '@application/notifications/toast-store.ts'
import {
  createSessionStore,
  currentView,
  type SessionStore,
} from '@application/session/session-store.ts'
import { useContainer } from '@app/container-context.tsx'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { shortId, type SessionId } from '@domain/shared/identifier.ts'

import { Chip } from '../common/primitives.tsx'
import { sessionHref } from '../routing/routes.ts'
import { ActivityFeed } from '../session/ActivityFeed.tsx'
import { Conversation } from '../session/Conversation.tsx'
import { useSessionStream } from '../session/use-session-stream.ts'

/** A worker's real transcript, over the course page.
 *
 * Builds **its own** session store rather than borrowing the shell's, which
 * belongs to the session route: `createSessionStore` is a factory, so two
 * stores over the same log cost one extra subscription and cannot interfere.
 * The store is closed on unmount, or every open-and-close of the drawer
 * would leak a live SSE subscriber onto a store nobody can reach any more.
 *
 * **Read-only, deliberately.** No composer, and a pending approval is a chip
 * linking out to the session view rather than being answerable in place.
 * Typing into a session you opened in order to *observe* is a different
 * intention and should cost a navigation. (An unattended run does not
 * produce approvals at all — the driver floors `fetch` at `ask` and works
 * read-only precisely so it cannot deadlock on one — so a pending approval
 * here always belongs to a human's joined session, and answering it belongs
 * to whoever is driving that session, not to a reader who merely opened the
 * drawer to watch.)
 *
 * The drawer always opens at HEAD rather than deriving a scrub position:
 * "watching" means following the log as it grows, and a drawer opened at a
 * historical point would silently stop updating with nothing on screen to
 * say why. `historicalAt` is therefore always `null` for `Conversation`,
 * never derived from `state.scrub` the way the session route does.
 */
export const WorkerDrawer = ({
  sessionId,
  onClose,
  makeStore = createSessionStore,
}: {
  sessionId: SessionId
  onClose: () => void
  /** Injected so a test can drive the drawer without a real store. */
  makeStore?: typeof createSessionStore
}) => {
  const container = useContainer()

  const store: SessionStore = useMemo(
    () =>
      makeStore({
        sessions: container.sessions,
        turns: container.turns,
        approvals: container.approvals,
        now: container.now,
        notify,
      }),
    [container, makeStore],
  )

  useEffect(() => {
    void store.getState().open(sessionId, ScrubPoint.head())
    return () => store.getState().close()
  }, [sessionId, store])

  useSessionStream(store)

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const state = store()
  const view = currentView(state)
  const pending = state.approvals.size > 0

  return (
    <div className="drawer-backdrop" onClick={onClose}>
      <aside
        className="drawer"
        role="dialog"
        aria-label={`Watching session ${shortId(sessionId)}`}
        onClick={(event) => event.stopPropagation()}
      >
        <header className="drawer-head">
          <h3 className="drawer-title">Watching {shortId(sessionId)}</h3>
          {pending ? (
            <Chip tone="run-short" title="Answering it belongs to whoever is driving that session">
              waiting on an approval
            </Chip>
          ) : null}
          <span className="drawer-spacer" />
          <a className="btn btn-sm" href={sessionHref(sessionId)}>
            Open the session
          </a>
          <button type="button" className="btn btn-sm" onClick={onClose}>
            Close
          </button>
        </header>

        <div className="drawer-body">
          {/* historicalAt is always null: the drawer only ever shows HEAD, so
              there is no scrub position to report — see the doc comment above. */}
          <Conversation view={view} error={state.snapshotError} historicalAt={null} />
          <ActivityFeed store={store} />
        </div>
      </aside>
    </div>
  )
}

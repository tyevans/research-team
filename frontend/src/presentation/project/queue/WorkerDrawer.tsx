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

import { Drawer } from '../../common/Drawer.tsx'
import { sessionHref } from '../../routing/routes.ts'
import { ActivityFeed } from '../../session/ActivityFeed.tsx'
import { Conversation } from '../../session/Conversation.tsx'
import { useSessionStream } from '../../session/use-session-stream.ts'

/** A worker's real transcript, over the course page.
 *
 * Builds **its own** session store rather than borrowing the shell's, which
 * belongs to the session route: `createSessionStore` is a factory, so two
 * stores over the same log cost one extra subscription and cannot interfere.
 * The store is closed on unmount, or every open-and-close of the drawer
 * would leak a live SSE subscriber onto a store nobody can reach any more.
 *
 * **Read-only, and no longer the place decisions are taken.** Composing a
 * message changes where a session goes, and typing into a session you opened
 * in order to *observe* is a different intention — that still costs a
 * navigation, so there is no `Composer` here. This drawer used to carry
 * `Approvals` and `AutonomyAllowAll` as well, on the argument that the person
 * watching is exactly the person positioned to decide. That argument was
 * right and the placement was too narrow: it only held while this drawer was
 * open. Both now live in the shell's `DecisionBar`, which reaches the reader
 * on every route, so a watcher can still decide without navigating — from
 * here or from anywhere else.
 *
 * The drawer always opens at HEAD rather than deriving a scrub position:
 * "watching" means following the log as it grows, and a drawer opened at a
 * historical point would silently stop updating with nothing on screen to
 * say why. `historicalAt` is therefore always `null` for `Conversation`,
 * never derived from `state.scrub` the way the session route does.
 */
export const WorkerDrawer = ({
  sessionId,
  heading,
  onClose,
  makeStore = createSessionStore,
}: {
  sessionId: SessionId
  /** What to call the agent, when the id is not what the reader knows it by.
   *
   * The course page opens this from a roster it is already looking at, so
   * `Watching 3f2a…` is enough there. The agent widget opens it from any page
   * in the console, where the reader knows this agent as "the extraction in
   * atlas" and may not recognise a single id on the screen. The id stays in
   * the heading either way -- it is what a bug report needs -- but it stops
   * being the only thing in it. */
  heading?: string
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

  const state = store()
  const view = currentView(state)

  return (
    <Drawer
      heading={heading ? `${heading} · ${shortId(sessionId)}` : `Watching ${shortId(sessionId)}`}
      label={heading ? `Watching ${heading}` : `Watching session ${shortId(sessionId)}`}
      onClose={onClose}
      // `Conversation` is the session view's own scroller and pads itself
      // (`.conv`, `.activity`); it is the same component on a whole route, so
      // its inset belongs to it rather than to whatever is showing it.
      flush
      actions={
        <a className="btn btn-sm" href={sessionHref(sessionId)}>
          Open the session
        </a>
      }
    >
      {/* `Approvals` and `AutonomyAllowAll` used to sit here, above the
          conversation. Both are now the shell's `DecisionBar`, which is
          strictly more of what putting them here was reaching for: a watcher
          could answer a gated call without navigating, but only for the
          session whose drawer happened to be open. The bar reaches them on
          every route, including with no drawer open at all. */}
      {/* historicalAt is always null: the drawer only ever shows HEAD, so
          there is no scrub position to report — see the doc comment above.
          emptyDetail overrides Conversation's default, which invites the
          reader to send a turn below; the drawer has no composer, so that
          instruction would point at a control that isn't there. */}
      <Conversation
        view={view}
        error={state.snapshotError}
        historicalAt={null}
        emptyDetail="Nothing has been said in this session yet."
      />
      <ActivityFeed store={store} />
    </Drawer>
  )
}

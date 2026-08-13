import { useCallback, useEffect, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'

import { notify } from '@application/notifications/toast-store.ts'
import { errorMessage } from '@application/ports/errors.ts'
import { queryKeys } from '@application/queries/keys.ts'
import {
  currentView,
  type SessionActions,
  type SessionState,
  type SessionStore,
} from '@application/session/session-store.ts'
import { useContainer } from '@app/container-context.tsx'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { compactedThrough, type SessionProjection } from '@domain/session/session.ts'
import type { EventIndex } from '@domain/session/event-index.ts'
import { shortId, type SessionId } from '@domain/shared/identifier.ts'
import type { FilePath } from '@domain/shared/file-path.ts'
import type { WorkspaceFile } from '@domain/workspace/workspace-file.ts'
import type { Message } from '@domain/conversation/message.ts'

import { homeHref, sessionHref } from '../routing/routes.ts'
import { navigate } from '../routing/use-route.ts'
import { useSessionStream } from './use-session-stream.ts'

/** Everything one session's screen does, with no opinion about how it is
 *  arranged.
 *
 * **Why this is a hook and not a component.** One session is now read in two
 * shapes: the standalone `#/s/<id>` route, which is three panes in a `Split`,
 * and the project page's HOLDER region, which is one stacked column beside two
 * other regions. Those two differ only in markup — the effects, the store
 * lifecycle, the Escape listener and the four callbacks are identical, and were
 * identical when they lived in `SessionView` and `SessionView` was mounted
 * inside a `Pane`. Duplicating them into two components is how the two
 * arrangements start behaving differently by accident.
 *
 * **`sessionId` is nullable, and that is the load-bearing part of the
 * signature.** The project page calls this at the top of a component that may
 * have no holding session at all, and a hook called inside the `if` that
 * discovers so is a conditional hook. So every effect below tolerates `null` by
 * doing nothing, and the caller decides what to draw instead. The cost is that
 * `state` on a null screen is whatever the shared store last held; no caller
 * reads it, because both check the id first.
 *
 * **`href` is a parameter rather than `sessionHref` inlined, which is a
 * deliberate change from the code this moved out of.** `SessionView` wrote
 * `sessionHref` for every scrub and every file open, which is right on `#/s/`
 * and was wrong the moment the project page mounted it: clicking an event in
 * HOLDER rewrote the address to the standalone session route, i.e. navigated
 * out of the project page, discarding QUEUE and MATERIAL, to look at the event
 * you just clicked. That shipped in slice 0 and was invisible because HOLDER
 * was a whole session view and leaving for another one looked like nothing. It
 * stops being invisible the moment HOLDER is one region of three, so the
 * address each arrangement writes is now the arrangement's own business.
 */
export type SessionScreen = {
  /** The store's state, read once so callers do not each subscribe. */
  state: SessionState & SessionActions
  /** The projection at the current scrub point, or `null` while loading. */
  view: SessionProjection | null
  files: readonly WorkspaceFile[]
  messages: readonly Message[]
  /** How many messages the visible transcript folds away. */
  compacted: number
  /** The scrub point as a number, or `null` at head. */
  historicalAt: number | null
  selectEvent: (point: ScrubPoint) => void
  openFile: (path: FilePath) => void
  forkAt: (index: EventIndex) => void
  /** Whether the end-session confirmation is up, and its setter. Owned here
   *  rather than by each arrangement because the confirmation is a property of
   *  the session being read, not of the layout reading it. */
  endPending: boolean
  setEndPending: (pending: boolean) => void
  endSession: () => void
}

export const useSessionScreen = ({
  store,
  sessionId,
  at,
  path: openPath,
  href,
}: {
  /** Owned by the shell, which needs the same session's head for the
   *  breadcrumb. `open()` resets it wholesale, so switching sessions through it
   *  leaves nothing of the previous one behind. */
  store: SessionStore
  /** `null` when the caller has no session to show — see the note above. */
  sessionId: SessionId | null
  at: ScrubPoint
  /** The open file, read from the route. Not mirrored into state: the address
   *  bar owns it, so a scrub cannot silently drop it and a link always
   *  reproduces the screen. */
  path: FilePath | null
  /** Where a scrub or a file-open writes itself. See the type's docstring. */
  href: (at: ScrubPoint, path: FilePath | null) => string
}): SessionScreen => {
  const container = useContainer()
  const queryClient = useQueryClient()
  const state = store()

  useEffect(() => {
    if (sessionId === null) return
    void store.getState().open(sessionId, at)
    return () => store.getState().close()
    // `at` is deliberately not a dependency: opening is per session, and a
    // scrub within one is handled below without refetching the log.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, store])

  // A hand-edited hash or the browser's back button changes the position
  // without remounting, and the fold has to follow.
  useEffect(() => {
    if (sessionId === null) return
    if (!ScrubPoint.equals(store.getState().scrub, at)) void store.getState().scrubTo(at)
  }, [at, sessionId, store])

  useSessionStream(store)

  // Expired highlights are swept on a timer so a flash does not linger until
  // some unrelated render happens to clear it.
  useEffect(() => {
    if (state.fresh.size === 0) return
    const timer = setTimeout(() => store.getState().sweepFresh(), 1_600)
    return () => clearTimeout(timer)
  }, [state.fresh, store])

  // Both of these rewrite the address bar rather than component state, and both
  // replace rather than push: dragging through forty events, or clicking down a
  // file list, should not bury the page you arrived from under forty entries.
  const selectEvent = useCallback(
    (point: ScrubPoint) => {
      navigate(href(point, openPath), { replace: true })
    },
    [href, openPath],
  )

  const openFile = useCallback(
    (path: FilePath) => {
      navigate(href(state.scrub, path), { replace: true })
    },
    [href, state.scrub],
  )

  /** Global "back to live". The timeline handles Escape itself and stops the
   *  event, so a keypress with it focused never folds twice.
   *
   *  `selectEvent` is a real dependency, and used to be suppressed as one. It
   *  closes over the open file, so the listener registered on the first render
   *  kept navigating with whatever file was open then — pressing Escape after
   *  opening a file dropped it, which is exactly the case the path is in the
   *  URL to survive. Re-subscribing costs one listener swap. */
  useEffect(() => {
    if (sessionId === null) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      if (!ScrubPoint.isHistorical(store.getState().scrub)) return
      if (document.activeElement instanceof HTMLTextAreaElement) return
      selectEvent(ScrubPoint.head())
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [selectEvent, sessionId, store])

  /** Whether the end-session confirmation is up. Boolean rather than
   *  `ProjectList`'s discriminated union because there is one question here,
   *  not two. */
  const [endPending, setEndPending] = useState(false)

  const forkAt = (index: EventIndex) => {
    void store
      .getState()
      .fork(index)
      .then((forked) => {
        if (forked) {
          void queryClient.invalidateQueries({ queryKey: queryKeys.tree() })
          // The standalone route unconditionally, and not `href`: a fork is a
          // *different* session, which the project page's HOLDER has no way to
          // address — it shows the one holding the project.
          navigate(sessionHref(forked))
        }
      })
  }

  const endSession = () => {
    if (sessionId === null) return
    void container.sessions
      .release(sessionId)
      .then((released) => {
        if (!released) {
          notify('This session is not in a project.', 'bad')
          return
        }
        notify(`Session ended. ${shortId(state.head?.projectId)} is free.`, 'good')
        void queryClient.invalidateQueries({ queryKey: queryKeys.projects() })
        navigate(homeHref())
      })
      .catch((error: unknown) => notify(`Could not end session: ${errorMessage(error)}`, 'bad'))
  }

  const view = currentView(state)
  const messages = view?.messages ?? []

  return {
    state,
    view,
    files: view?.files ?? [],
    messages,
    compacted: compactedThrough(view?.compactedThrough, messages.length),
    historicalAt: ScrubPoint.toNullable(state.scrub),
    selectEvent,
    openFile,
    forkAt,
    endPending,
    setEndPending,
    endSession,
  }
}

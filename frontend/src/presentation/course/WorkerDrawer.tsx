import { useEffect, useMemo, useRef } from 'react'

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
/** Descendants a keyboard user can land on, queried fresh on every keypress
 *  rather than cached at mount: the drawer's body is a live transcript that
 *  grows as frames arrive, so a list captured once would go stale and the
 *  trap would eventually cycle to elements that no longer exist, or miss
 *  ones that just arrived. */
const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input, textarea, select, [tabindex]:not([tabindex="-1"])'

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
  const asideRef = useRef<HTMLElement>(null)
  const closeButtonRef = useRef<HTMLButtonElement>(null)

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

  // Move focus in on open, and give it back on close. The close button, not
  // the heading, is the target: a heading isn't natively focusable (it would
  // need a `tabIndex={-1}` just to receive focus programmatically, dropping
  // it into the tab order like a fake control), while the close button is
  // already a real, always-present affordance a keyboard user expects to be
  // able to reach immediately. Without this, focus stays on whatever roster
  // row button opened the drawer, so a screen-reader user hears the drawer's
  // content announced without their focus ever having moved into it.
  //
  // The element that had focus before opening is captured here rather than
  // assumed to be the roster row, and re-checked for DOM membership before
  // restoring: the row could have been removed (e.g. the worker finished and
  // dropped off the roster) while the drawer was open, and focusing a
  // detached node throws in some environments and silently no-ops in others
  // — neither of which puts focus anywhere useful.
  useEffect(() => {
    const previouslyFocused = document.activeElement
    closeButtonRef.current?.focus()
    return () => {
      if (previouslyFocused instanceof HTMLElement && document.contains(previouslyFocused)) {
        previouslyFocused.focus()
      }
    }
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        onClose()
        return
      }

      // Trap Tab/Shift+Tab inside the drawer so a keyboard user can't tab
      // straight through into the course page behind it, which is still
      // rendered and still focusable. Focusable elements are queried here,
      // at keypress time, rather than once at mount — see FOCUSABLE_SELECTOR.
      if (event.key !== 'Tab' || !asideRef.current) return

      const focusable = Array.from(
        asideRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      )
      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (!first || !last) return

      const active = document.activeElement
      if (event.shiftKey) {
        if (active === first || !asideRef.current.contains(active)) {
          event.preventDefault()
          last.focus()
        }
      } else if (active === last || !asideRef.current.contains(active)) {
        event.preventDefault()
        first.focus()
      }
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
        aria-modal="true"
        aria-label={`Watching session ${shortId(sessionId)}`}
        ref={asideRef}
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
          <button type="button" className="btn btn-sm" ref={closeButtonRef} onClick={onClose}>
            Close
          </button>
        </header>

        <div className="drawer-body">
          {/* historicalAt is always null: the drawer only ever shows HEAD, so
              there is no scrub position to report — see the doc comment above.
              emptyDetail overrides Conversation's default, which invites the
              reader to send a turn below; the drawer has no composer, so
              that instruction would point at a control that isn't there. */}
          <Conversation
            view={view}
            error={state.snapshotError}
            historicalAt={null}
            emptyDetail="Nothing has been said in this session yet."
          />
          <ActivityFeed store={store} />
        </div>
      </aside>
    </div>
  )
}

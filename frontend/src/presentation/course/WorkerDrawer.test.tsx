import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { cloneElement } from 'react'
import { expect, it, vi } from 'vitest'

import type { SessionStore } from '@application/session/session-store.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { AutonomyRepository } from '@application/ports/repositories.ts'
import { emptyActivity } from '@domain/activity/activity.ts'
import { SessionId } from '@domain/shared/identifier.ts'
import { TurnState } from '@domain/session/turn.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { StreamProvider } from '../shell/StreamProvider.tsx'
import { WorkerDrawer } from './WorkerDrawer.tsx'

const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

/** A policy with something still asking, so the drawer's `AutonomyAllowAll`
 *  renders enabled controls. A policy where everything was already auto would
 *  disable them, and the Tab-trap tests below would then pass for the wrong
 *  reason — by excluding the buttons rather than including them. */
const fakeAutonomy = (): AutonomyRepository => {
  const policy = {
    levels: new Map([
      ['fetch', 'ask'],
      ['advance_stage', 'ask'],
    ]),
    gated: ['fetch', 'advance_stage'],
    stageGates: ['advance_stage'],
  }
  return {
    read: vi.fn<AutonomyRepository['read']>().mockResolvedValue(policy),
    setLevel: vi.fn<AutonomyRepository['setLevel']>().mockResolvedValue(policy),
    allowAll: vi
      .fn<AutonomyRepository['allowAll']>()
      .mockResolvedValue({ changed: new Map(), policy }),
  }
}

/** A stream that never delivers anything, which is all this suite needs:
 *  `useSessionStream` only has to subscribe and unsubscribe without throwing. */
const fakeStream = (): EventStream => ({
  connect(_listener: EventStreamListener) {},
  disconnect() {},
})

/** A zustand-shaped fake: callable as the hook itself (with or without a
 *  selector, the way `Conversation`'s and `ActivityFeed`'s real props are
 *  read), plus `getState()` for the imperative calls `open`/`close` go
 *  through. Nothing here needs to be reactive — no test in this file asserts
 *  a re-render off a state change the fake itself produces. */
const fakeStore = (overrides: {
  open?: SessionStore['getState'] extends never ? never : (...args: never[]) => Promise<void>
  close?: () => void
}): SessionStore => {
  const state = {
    sessionId: SESSION,
    head: null,
    log: [],
    scrub: { kind: 'head' as const },
    snapshot: null,
    loadingSnapshot: false,
    snapshotError: null,
    error: null,
    turn: TurnState.idle(),
    note: null,
    activity: emptyActivity(),
    discarded: new Map(),
    fresh: new Map(),
    open: overrides.open ?? vi.fn().mockResolvedValue(undefined),
    close: overrides.close ?? vi.fn(),
    reload: vi.fn().mockResolvedValue(undefined),
    scrubTo: vi.fn().mockResolvedValue(undefined),
    send: vi.fn().mockResolvedValue(undefined),
    cancel: vi.fn().mockResolvedValue(undefined),
    fork: vi.fn().mockResolvedValue(null),
    dismissNote: vi.fn(),
    handleFrame: vi.fn(),
    handleReconnect: vi.fn().mockResolvedValue(undefined),
    refreshRunning: vi.fn().mockResolvedValue(undefined),
    sweepFresh: vi.fn(),
  }

  const store = ((selector?: (s: typeof state) => unknown) =>
    selector ? selector(state) : state) as unknown as SessionStore
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(store as any).getState = () => state
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(store as any).setState = () => {}
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  ;(store as any).subscribe = () => () => {}
  return store
}

/** Renders a `WorkerDrawer` behind the same providers the shell wraps every
 *  view in, with its store swapped for a fake via the `makeStore` prop —
 *  `cloneElement` rather than a component prop on `ui` itself, since the JSX
 *  is already built by the caller and `makeStore` is a detail this helper
 *  owns, not the test. */
const renderDrawer = (
  ui: ReactElement<{ sessionId: SessionId; onClose: () => void; makeStore?: unknown }>,
  parts: {
    open?: (...args: never[]) => Promise<void>
    close?: () => void
  } = {},
) => {
  const store = fakeStore(parts)
  const container = { stream: fakeStream(), autonomy: fakeAutonomy() } as unknown as AppContainer
  // A `QueryClient` because the drawer now contains `AutonomyAllowAll`, which
  // reads the instance-wide policy through the same query key the course
  // page's panel uses.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
  // An `OverlayHost`, because `WorkerDrawer` is a `Drawer` and a `Drawer` is
  // an `Overlay`, which renders nothing without one. In the application this
  // comes from `Shell`; here it is the innermost wrapper, matching the real
  // tree where the host sits inside the providers and outside the page.
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <StreamProvider>
          <OverlayHost>{children}</OverlayHost>
        </StreamProvider>
      </ContainerProvider>
    </QueryClientProvider>
  )
  return render(cloneElement(ui, { makeStore: () => store }), { wrapper })
}

it('opens the session it was given', async () => {
  const open = vi.fn().mockResolvedValue(undefined)

  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />, { open })

  expect(open).toHaveBeenCalledWith(SESSION, expect.anything())
})

it('closes on escape', async () => {
  const onClose = vi.fn()

  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={onClose} />)
  await userEvent.keyboard('{Escape}')

  expect(onClose).toHaveBeenCalled()
})

it('offers no composer, because it is for watching', () => {
  // Typing into a session you opened in order to observe is a different
  // intention, and it should cost a navigation.
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  expect(screen.queryByRole('textbox')).toBeNull()
})

it('does not tell an empty session to send a turn it has no composer for', () => {
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  expect(screen.getByText('Nothing has been said in this session yet.')).toBeInTheDocument()
  expect(screen.queryByText(/send the first turn below/i)).toBeNull()
})

it('still offers a link to open the full session', () => {
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  const link = screen.getByRole('link', { name: /open the session/i })
  expect(link).toHaveAttribute('href', expect.stringContaining(SESSION))
})

/** **Four approval tests and the allow-all test were deleted here**, and the
 *  deletion is the change rather than a casualty.
 *
 *  They asserted that the drawer rendered approve/reject controls, that each
 *  answered through the drawer's own store rather than by navigating, and that
 *  `AutonomyAllowAll` sat beside them. All five were true and all five were
 *  about a placement that is gone: approvals are the shell's `DecisionBar`
 *  now, subscribed to the whole feed rather than to this drawer's session.
 *  Keeping them here would have meant keeping the call site they describe.
 *
 *  What they were really testing is asserted in `DecisionBar.test.tsx`,
 *  including the case none of them could reach — an approval for a session
 *  whose drawer is *not* open still reaching a person.
 *
 *  Deliberately kept below: that the drawer offers no composer, which is still
 *  this component's own claim about itself.
 */
it('no longer offers a decision, because the shell does on every page', () => {
  // The complement of the deletion above, and it fails if `Approvals` is put
  // back here: two decision surfaces over one gate is exactly the arrangement
  // the bar replaced, and the drawer's would again be the one that only works
  // while it happens to be open.
  //
  // No approval is seeded into the fake store any more, because the store has
  // no approvals to seed: the parallel copy it kept was deleted once nothing
  // rendered it. Putting `Approvals` back here would therefore also mean
  // rebuilding that state, which is a louder change than the one-line import
  // this test was originally guarding against — but it is still the change
  // this test refuses.
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  expect(screen.queryByRole('button', { name: /^approve$/i })).toBeNull()
  expect(screen.queryByRole('button', { name: /^reject$/i })).toBeNull()
})

it('closes the store it opened when it unmounts', () => {
  const close = vi.fn()

  const { unmount } = renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />, {
    close,
  })
  unmount()

  expect(close).toHaveBeenCalled()
})

it('is announced as a modal', () => {
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  expect(screen.getByRole('dialog')).toHaveAttribute('aria-modal', 'true')
})

it('moves focus into the drawer on open', () => {
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  expect(screen.getByRole('button', { name: /close/i })).toHaveFocus()
})

/** **`returns focus to whatever opened it, on unmount` was deleted here**, and
 *  what it was really testing is worth writing down.
 *
 *  It appended a button to `document.body`, focused it, rendered the drawer,
 *  and then unmounted the *entire tree* — asserting that focus came back. That
 *  worked because `Drawer` restored focus from its own unmount cleanup. It
 *  does not any more, and it should not: the restore is the host's, because
 *  only the host knows when the page stops being `inert`, and a cleanup that
 *  fired while the page was still inert was silently doing nothing in a real
 *  browser. `OverlayHost` carries that reasoning and the measurement.
 *
 *  Under the host, unmounting everything means unmounting the host too, so
 *  there is nothing left to give focus back — which is the right behaviour for
 *  a tree that has gone away, and a scenario no reader ever performs. The
 *  scenario a reader *does* perform is closing the drawer while the app keeps
 *  running, and that is asserted where the behaviour now lives: `Drawer.test`
 *  for the single case and `OverlayHost.test` for a stack unwinding one level
 *  at a time. Kept here: that focus moves *in*, which is still this
 *  component's own doing. */

/** **Three Tab-trap tests were deleted here**, and the deletion is the point
 *  rather than a casualty.
 *
 *  They dispatched a synthetic `Tab` KeyboardEvent and asserted that
 *  `Drawer`'s own keydown handler called `focus()` on the element it had
 *  decided was next — wrapping forwards, wrapping backwards, and including an
 *  approval button that arrived after mount. Their own preamble conceded what
 *  they were: "jsdom does not implement real tab-order traversal", so they
 *  asserted on the handler's behaviour and not on the reader's. They tested a
 *  hand-rolled ring, exactly, and could not have told you whether a keyboard
 *  user could leave the dialog — which is the only thing the ring was for.
 *
 *  `Drawer` has no ring now. Confinement is `inert` on `.lay-app-root`, which
 *  is the platform's, covers pointer and assistive technology as well as Tab,
 *  and is asserted over the whole document in `OverlayHost.test.tsx` rather
 *  than over one element here. jsdom implements the attribute and not its
 *  behaviour, so the browser half is checked in Storybook.
 *
 *  The one claim in those tests that was about *this* component rather than
 *  the trap — an approval that arrives after mount is inside the dialog and
 *  reachable — is kept, below, without the ring. */
/** `sweeps in an approval that arrives after it opened` was deleted with the
 *  four above: it asserted that a late-arriving approval button was a
 *  descendant of the dialog, and there is no approval button in the dialog any
 *  more. What it was standing in for -- that `inert` confines by containment
 *  rather than by a hand-rolled ring -- is asserted over the whole document at
 *  the bottom of this file, which is where it belongs.
 *
 *  `offers the way to stop being asked, beside the approvals` was deleted for
 *  the same reason as the decision tests: `AutonomyAllowAll` is beside the
 *  approvals still, and the approvals are in the bar. `DecisionBar.test.tsx`
 *  asserts it there. */

it('makes the page behind it unreachable rather than merely covered', () => {
  // The claim the three deleted trap tests were reaching for, asserted the way
  // that could actually catch the defect that shipped: not "Tab cycles inside
  // the drawer" but "nothing outside the drawer is reachable at all".
  //
  // `.lay-app-root` is the single element a modal marks, which is why the
  // assertion has somewhere to point. Before it existed, `Drawer` set
  // `aria-modal="true"` and left the entire shell tabbable.
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  expect(document.querySelector('.lay-app-root')).toHaveAttribute('inert')
  expect(document.querySelector('.lay-app-root')).toHaveAttribute('aria-hidden', 'true')
})

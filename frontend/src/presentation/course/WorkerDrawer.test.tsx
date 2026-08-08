import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { cloneElement } from 'react'
import { expect, it, vi } from 'vitest'

import type { SessionStore } from '@application/session/session-store.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import { emptyActivity } from '@domain/activity/activity.ts'
import { SessionId } from '@domain/shared/identifier.ts'
import { TurnState } from '@domain/session/turn.ts'

import { StreamProvider } from '../shell/StreamProvider.tsx'
import { WorkerDrawer } from './WorkerDrawer.tsx'

const SESSION = SessionId('22222222-2222-2222-2222-222222222222')

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
  approvals?: readonly { approvalId: string; tool: string }[]
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
    approvals: new Map(
      (overrides.approvals ?? []).map((approval) => [approval.approvalId, approval]),
    ),
    deciding: null,
    fresh: new Map(),
    open: overrides.open ?? vi.fn().mockResolvedValue(undefined),
    close: overrides.close ?? vi.fn(),
    reload: vi.fn().mockResolvedValue(undefined),
    scrubTo: vi.fn().mockResolvedValue(undefined),
    send: vi.fn().mockResolvedValue(undefined),
    cancel: vi.fn().mockResolvedValue(undefined),
    fork: vi.fn().mockResolvedValue(null),
    decide: vi.fn().mockResolvedValue(undefined),
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
    approvals?: readonly { approvalId: string; tool: string }[]
  } = {},
) => {
  const store = fakeStore(parts)
  const container = { stream: fakeStream() } as unknown as AppContainer
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <ContainerProvider container={container}>
      <StreamProvider>{children}</StreamProvider>
    </ContainerProvider>
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

it('links out to the session rather than answering an approval in place', () => {
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />, {
    approvals: [{ approvalId: 'a-1', tool: 'fetch' }],
  })

  const link = screen.getByRole('link', { name: /open the session/i })
  expect(link).toHaveAttribute('href', expect.stringContaining(SESSION))
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

it('returns focus to whatever opened it, on unmount', () => {
  const opener = document.createElement('button')
  opener.textContent = 'open drawer'
  document.body.append(opener)
  opener.focus()
  expect(opener).toHaveFocus()

  const { unmount } = renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)
  expect(opener).not.toHaveFocus()

  unmount()

  expect(opener).toHaveFocus()
  opener.remove()
})

// jsdom does not implement real tab-order traversal — `userEvent.tab()` is
// emulated and does not exercise the drawer's own keydown handler the way a
// browser's native Tab would. So these dispatch a real `Tab`/`Shift+Tab`
// KeyboardEvent by hand and assert on the handler's own `focus()` calls,
// rather than leaning on `userEvent.tab()` to look like it proved more than
// it does.
it('wraps Tab from the last focusable element back to the first', () => {
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  const focusable = screen
    .getByRole('dialog')
    .querySelectorAll<HTMLElement>('a[href], button:not([disabled])')
  const last = focusable[focusable.length - 1]
  const first = focusable[0]
  last?.focus()
  expect(last).toHaveFocus()

  document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Tab', bubbles: true }))

  expect(first).toHaveFocus()
})

it('wraps Shift+Tab from the first focusable element to the last', () => {
  renderDrawer(<WorkerDrawer sessionId={SESSION} onClose={() => {}} />)

  const focusable = screen
    .getByRole('dialog')
    .querySelectorAll<HTMLElement>('a[href], button:not([disabled])')
  const last = focusable[focusable.length - 1]
  const first = focusable[0]
  first?.focus()
  expect(first).toHaveFocus()

  document.dispatchEvent(
    new KeyboardEvent('keydown', { key: 'Tab', shiftKey: true, bubbles: true }),
  )

  expect(last).toHaveFocus()
})

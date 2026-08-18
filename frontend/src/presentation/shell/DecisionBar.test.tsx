import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import { useToasts } from '@application/notifications/toast-store.ts'
import { ApiError } from '@application/ports/errors.ts'
import type { EventStream, EventStreamListener } from '@application/ports/event-stream.ts'
import type { ApprovalRepository, AutonomyRepository } from '@application/ports/repositories.ts'
import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import { InteractionLogContext } from '@app/interaction-log-provider.tsx'
import type { Approval, ApprovalDecision } from '@domain/approval/approval.ts'
import { ApprovalId, SessionId } from '@domain/shared/identifier.ts'

import { DecisionBar } from './DecisionBar.tsx'
import { StreamProvider } from './StreamProvider.tsx'

/** The session the reader is notionally looking at, and one they are not.
 *
 * Two ids rather than one because the defect this component replaces is
 * invisible with a single session: three per-session call sites all render
 * correctly when the only approval belongs to the session on screen.
 */
const ON_SCREEN = SessionId('11111111-1111-1111-1111-111111111111')
const ELSEWHERE = SessionId('22222222-2222-2222-2222-222222222222')

const anApproval = (
  id: string,
  overrides: { sessionId?: SessionId; allowedDecisions?: readonly ApprovalDecision[] } = {},
): Approval => ({
  id: ApprovalId(id),
  sessionId: overrides.sessionId ?? ELSEWHERE,
  toolName: 'fetch',
  description: null,
  args: { url: 'https://example.com' },
  // The tool gate's real list: `ALLOWED_DECISIONS` in
  // `research_team/infrastructure/agent/approval.py` excludes `respond`.
  allowedDecisions: overrides.allowedDecisions ?? ['approve', 'edit', 'reject'],
  context: null,
})

/** A policy with something still asking, so `AutonomyAllowAll` renders an
 *  enabled control rather than a disabled one. */
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

/** The one `EventSource` the shell owns, with a handle on what it delivers.
 *
 * `StreamProvider` is the real one: the claim under test is that the bar is
 * fed by *that* subscription and not by a fetch of its own, and a test that
 * called the hook's setter directly would pass with no subscription at all.
 */
const controllableStream = () => {
  let listener: EventStreamListener | null = null
  const stream: EventStream = {
    connect(l) {
      listener = l
    },
    disconnect() {
      listener = null
    },
  }
  return {
    stream,
    deliver(...frames: Parameters<EventStreamListener['onFrame']>[0][]) {
      act(() => {
        for (const frame of frames) listener?.onFrame(frame)
      })
    },
  }
}

const renderBar = ({
  decide: decideResult,
  record,
}: { decide?: () => Promise<void>; record?: (kind: string, payload: unknown) => void } = {}) => {
  const feed = controllableStream()
  const decide = decideResult
    ? vi.fn<ApprovalRepository['decide']>().mockImplementation(decideResult)
    : vi.fn<ApprovalRepository['decide']>().mockResolvedValue(undefined)
  const approvals: ApprovalRepository = {
    pending: vi.fn<ApprovalRepository['pending']>().mockResolvedValue([]),
    decide,
  }
  const container = {
    stream: feed.stream,
    approvals,
    autonomy: fakeAutonomy(),
  } as unknown as AppContainer
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })

  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <InteractionLogContext.Provider value={{ record: record ?? (() => {}) } as never}>
          <StreamProvider>{children}</StreamProvider>
        </InteractionLogContext.Provider>
      </ContainerProvider>
    </QueryClientProvider>
  )

  const view = render(<DecisionBar />, { wrapper })
  return { ...view, ...feed, decide, approvals }
}

it('renders nothing at all until something is pending', () => {
  // The bar is on every page, so "nothing pending" has to be indistinguishable
  // from the bar not existing -- otherwise every route grows a permanent empty
  // band. Fails if the section is rendered unconditionally.
  renderBar()

  expect(screen.queryByRole('region', { name: /decisions waiting/i })).toBeNull()
})

/** The whole reason this component exists.
 *
 * The three call sites it replaced each filtered by the session they were
 * showing, so an approval raised on any other session was invisible until the
 * reader happened to open it. Here the bar is handed no session at all and the
 * approval belongs to one nothing on screen is about.
 *
 * This test fails if `useApprovalFeed` grows a `sessionId` filter, which is
 * the specific regression worth naming: it is a one-line change that looks
 * like tidying.
 */
it('shows an approval for a session the reader is not looking at', () => {
  const bar = renderBar()

  bar.deliver({ kind: 'approvalRequested', approval: anApproval('a-1', { sessionId: ELSEWHERE }) })

  expect(screen.getByRole('region', { name: /decisions waiting/i })).toBeInTheDocument()
  expect(screen.getByText('fetch')).toBeInTheDocument()
})

it('gathers approvals from more than one session into the one bar', () => {
  const bar = renderBar()

  bar.deliver(
    { kind: 'approvalRequested', approval: anApproval('a-1', { sessionId: ON_SCREEN }) },
    { kind: 'approvalRequested', approval: anApproval('a-2', { sessionId: ELSEWHERE }) },
  )

  expect(screen.getByText('2 calls are waiting')).toBeInTheDocument()
  expect(screen.getByText(/from 2 session\(s\)/)).toBeInTheDocument()
})

/** R-F6.9 in a new place: a decision the server will not take is *named*.
 *
 * `respond` is excluded on an ordinary tool gate. Hidden, the console would
 * offer three controls here and four on a stage gate with nothing on screen
 * saying why -- capabilities varying invisibly with server state. Asserting
 * both halves (present, and unusable) in one test is deliberate: a component
 * that hides it passes the second half, and one that offers it live passes the
 * first.
 */
it('names a decision this gate refuses, disabled, with the reason', () => {
  const bar = renderBar()

  bar.deliver({
    kind: 'approvalRequested',
    approval: anApproval('a-1', { allowedDecisions: ['approve', 'edit', 'reject'] }),
  })

  const respond = screen.getByRole('button', { name: /respond instead/i })
  expect(respond).toBeInTheDocument()
  expect(respond).toBeDisabled()
  // The server's own words, from `ALLOWED_DECISIONS`' docstring. Visible text
  // rather than a `title`, and pointed at by `aria-describedby` so it is the
  // button's description rather than prose that happens to be nearby.
  const reason = screen.getByText(/invents a result/i)
  expect(reason).toBeInTheDocument()
  expect(respond).toHaveAttribute('aria-describedby', reason.id)
})

it('offers a decision this gate does allow', () => {
  const bar = renderBar()

  bar.deliver({
    kind: 'approvalRequested',
    approval: anApproval('a-1', { allowedDecisions: ['approve', 'edit', 'reject', 'respond'] }),
  })

  expect(screen.getByRole('button', { name: /respond instead/i })).toBeEnabled()
  expect(screen.queryByText(/invents a result/i)).toBeNull()
})

it('posts an approval straight through, with no payload', async () => {
  const user = userEvent.setup()
  const bar = renderBar()
  const approval = anApproval('a-1')

  bar.deliver({ kind: 'approvalRequested', approval })
  await user.click(screen.getByRole('button', { name: /^approve$/i }))

  expect(bar.decide).toHaveBeenCalledWith(approval.sessionId, approval.id, {
    decision: 'approve',
  })
})

/** `edit` carries the arguments, or it is a re-run of the call being objected
 *  to.
 *
 *  The two-step -- press `Edit the call`, then submit -- is the assertion as
 *  much as the payload is: a bare button that posted `{decision: 'edit'}` on
 *  the first press would satisfy a test that only checked the decision.
 */
it('posts edited arguments under editedArgs', async () => {
  const user = userEvent.setup()
  const bar = renderBar()
  const approval = anApproval('a-1')

  bar.deliver({ kind: 'approvalRequested', approval })
  await user.click(screen.getByRole('button', { name: /edit the call/i }))
  expect(bar.decide).not.toHaveBeenCalled()

  const field = screen.getByLabelText(/arguments to run instead/i)
  await user.clear(field)
  await user.type(field, '{{"url":"https://example.org"}')
  await user.click(screen.getByRole('button', { name: /run the edited call/i }))

  expect(bar.decide).toHaveBeenCalledWith(approval.sessionId, approval.id, {
    decision: 'edit',
    editedArgs: { url: 'https://example.org' },
  })
})

it('refuses to send an edit that is not valid JSON, rather than letting the server refuse it', async () => {
  const user = userEvent.setup()
  const bar = renderBar()

  bar.deliver({ kind: 'approvalRequested', approval: anApproval('a-1') })
  await user.click(screen.getByRole('button', { name: /edit the call/i }))
  const field = screen.getByLabelText(/arguments to run instead/i)
  await user.clear(field)
  await user.type(field, 'not json')
  await user.click(screen.getByRole('button', { name: /run the edited call/i }))

  expect(bar.decide).not.toHaveBeenCalled()
  expect(screen.getByRole('alert')).toHaveTextContent(/not valid JSON/i)
})

/** `respond` carries the message, or it invents an empty tool result. */
it('posts a written response under message', async () => {
  const user = userEvent.setup()
  const bar = renderBar()
  const approval = anApproval('a-1', {
    allowedDecisions: ['approve', 'edit', 'reject', 'respond'],
  })

  bar.deliver({ kind: 'approvalRequested', approval })
  await user.click(screen.getByRole('button', { name: /respond instead/i }))
  expect(bar.decide).not.toHaveBeenCalled()

  await user.type(screen.getByLabelText(/what to tell the agent/i), 'The page 404s; skip it.')
  await user.click(screen.getByRole('button', { name: /send this instead/i }))

  expect(bar.decide).toHaveBeenCalledWith(approval.sessionId, approval.id, {
    decision: 'respond',
    message: 'The page 404s; skip it.',
  })
})

/** The card comes down on the frame, not on the click.
 *
 * That is what makes the REPL and a second tab work: whichever path answered
 * it, `ApprovalSettled` is the one thing every listener sees.
 */
it('clears a card when the approval settles, whoever answered it', () => {
  const bar = renderBar()
  const approval = anApproval('a-1')

  bar.deliver({ kind: 'approvalRequested', approval })
  expect(screen.getByRole('region', { name: /decisions waiting/i })).toBeInTheDocument()

  bar.deliver({
    kind: 'approvalSettled',
    sessionId: approval.sessionId,
    approvalId: approval.id,
  })

  expect(screen.queryByRole('region', { name: /decisions waiting/i })).toBeNull()
})

/** Moved here from `session-store.test.ts`, which owned this claim while the
 *  store had its own `decide`. The store's copy is gone; the behaviour is not.
 *
 *  A 404 means the REPL, another tab, or a timeout settled the gate first.
 *  `ApprovalSettled` takes the card down either way, so a toast would be an
 *  error message about nothing having gone wrong — and it would fire on the
 *  ordinary race, not on a rare one. The second half is the load-bearing half:
 *  a `catch {}` that swallowed everything would pass the first assertion alone
 *  while hiding a real failure to record a decision.
 */
it('stays quiet when a decision races somebody else’s, but not when it fails', async () => {
  const user = userEvent.setup()
  useToasts.setState({ toasts: [] })

  const raced = renderBar({
    decide: () => Promise.reject(new ApiError('gone', 404)),
  })
  raced.deliver({ kind: 'approvalRequested', approval: anApproval('a-1') })
  await user.click(screen.getByRole('button', { name: /^approve$/i }))
  expect(useToasts.getState().toasts).toHaveLength(0)

  raced.unmount()
  const broken = renderBar({
    decide: () => Promise.reject(new ApiError('the server fell over', 500)),
  })
  broken.deliver({ kind: 'approvalRequested', approval: anApproval('a-2') })
  await user.click(screen.getByRole('button', { name: /^approve$/i }))
  expect(useToasts.getState().toasts).toHaveLength(1)
  expect(useToasts.getState().toasts[0]?.message).toMatch(/the server fell over/i)
})

it('offers the way to stop being asked, beside the approvals', async () => {
  // Moved here from the worker drawer with the approvals it belongs to: the
  // person answering the same gate for the fifth time should not have to find
  // a settings surface to make it stop.
  const bar = renderBar()

  bar.deliver({ kind: 'approvalRequested', approval: anApproval('a-1') })

  expect(
    await screen.findByRole('button', { name: /allow everything except the review gate/i }),
  ).toBeInTheDocument()
  // And it says what it changes, on the control rather than in a tooltip --
  // the policy is instance-wide although it is reached through one session.
  expect(screen.getByText(/every session on this instance/i)).toBeInTheDocument()
})

/** `ApprovalDecided.latency_ms` and `.expanded_details` are the entire reason
 *  this kind exists -- the click-through-versus-deliberation distinction from
 *  `direction.md` §3 -- so this is not a smoke test of "an event fired", it
 *  pins the two numbers.
 */
it('records ApprovalDecided with the elapsed time and false for a click-through approval', async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime })
  const record = vi.fn()
  const bar = renderBar({ record })
  const approval = anApproval('a-1')

  bar.deliver({ kind: 'approvalRequested', approval })
  await vi.advanceTimersByTimeAsync(400)
  await user.click(screen.getByRole('button', { name: /^approve$/i }))

  expect(record).toHaveBeenCalledWith('ApprovalDecided', {
    decision: 'approve',
    latency_ms: expect.any(Number),
    expanded_details: false,
    review_id: approval.id,
  })
  const [, payload] = record.mock.calls.find(([kind]) => kind === 'ApprovalDecided')!
  expect((payload as { latency_ms: number }).latency_ms).toBeGreaterThanOrEqual(400)
  vi.useRealTimers()
})

it('records expanded_details: true once Edit or Respond has been opened, even after deciding a plain approve', async () => {
  const user = userEvent.setup()
  const record = vi.fn()
  const bar = renderBar({ record })
  const approval = anApproval('a-1', {
    allowedDecisions: ['approve', 'edit', 'reject', 'respond'],
  })

  bar.deliver({ kind: 'approvalRequested', approval })
  // Opened and then closed again -- deliberation happened even though the
  // final decision came through the plain Approve button, and closing the
  // form must not erase that it was opened.
  await user.click(screen.getByRole('button', { name: /respond instead/i }))
  await user.click(screen.getByRole('button', { name: /respond instead/i }))
  await user.click(screen.getByRole('button', { name: /^approve$/i }))

  expect(record).toHaveBeenCalledWith(
    'ApprovalDecided',
    expect.objectContaining({ expanded_details: true }),
  )
})

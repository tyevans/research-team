import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'

import { InteractionLogProvider } from './interaction-log-provider.tsx'
import { ErrorBoundary, LoggedErrorBoundary } from './ErrorBoundary.tsx'

/** React logs every caught error itself, and a boundary test is nothing but
 *  caught errors -- so the run prints several screens of stack for tests that
 *  are passing. Silenced here rather than globally, so a stack printed by
 *  anything else in the suite is still visible. */
let consoleError: { mockRestore: () => void }

beforeEach(() => {
  consoleError = vi.spyOn(console, 'error').mockImplementation(() => {})
})

afterEach(() => {
  consoleError.mockRestore()
})

const Boom = ({ throws = true }: { throws?: boolean }) => {
  if (throws) throw new TypeError('cannot read properties of null')
  return <p>the page</p>
}

it('draws a recovery surface instead of nothing when a child throws during render', async () => {
  render(
    <ErrorBoundary where="root">
      <Boom />
    </ErrorBoundary>,
  )

  // The three affordances, by their accessible names. Proved red by
  // rendering `<Boom />` with no boundary: the render throws out of
  // `render()` and the test fails before it reaches an assertion, which is
  // exactly what the application did to `#root`.
  expect(screen.getByRole('alert')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Go home' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
})

it('shows the error rather than an apology', () => {
  render(
    <ErrorBoundary where="root">
      <Boom />
    </ErrorBoundary>,
  )

  expect(screen.getByText(/cannot read properties of null/)).toBeInTheDocument()
  expect(screen.getByText('TypeError')).toBeInTheDocument()
})

it('shows a thrown non-Error too, rather than crashing inside the fallback', () => {
  const Throws = () => {
    // Legal JavaScript, and a `.message` read on it is `undefined` -- which
    // is why `getDerivedStateFromError` normalises before the fallback runs.
    // The rule this suppresses is right about production code and is exactly
    // what this case exists to survive.
    // eslint-disable-next-line @typescript-eslint/only-throw-error
    throw 'a bare string'
  }

  render(
    <ErrorBoundary where="root">
      <Throws />
    </ErrorBoundary>,
  )

  expect(screen.getByText(/a bare string/)).toBeInTheDocument()
})

it('draws the children again when the throw was transient', async () => {
  const Sometimes = () => {
    if (!recovered) throw new Error('first time only')
    return <p>the page</p>
  }
  let recovered = false

  render(
    <ErrorBoundary where="root">
      <Sometimes />
    </ErrorBoundary>,
  )
  recovered = true
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  expect(screen.getByText('the page')).toBeInTheDocument()
})

it('says how many times a permanent error has been retried', async () => {
  render(
    <ErrorBoundary where="root">
      <Boom />
    </ErrorBoundary>,
  )

  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))

  // Not on the first press: one retry is the ordinary case and a count on it
  // would be noise.
  expect(screen.getByText(/Tried 2 times/)).toBeInTheDocument()
})

it('changes the hash before clearing the error, so home is not the page that threw', async () => {
  window.location.hash = '#/p/1111'

  render(
    <ErrorBoundary where="root">
      <Boom />
    </ErrorBoundary>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Go home' }))

  expect(window.location.hash).toBe('#/')
})

const spySink = () => ({ send: vi.fn(async () => {}), sendOnUnload: vi.fn() })

const streamOf = (sink: ReturnType<typeof spySink>) =>
  [...sink.send.mock.calls, ...sink.sendOnUnload.mock.calls].flatMap(
    (call) => call[0] as unknown as { kind: string; payload: Record<string, unknown> }[],
  )

it('reports a caught error to the interaction log, all the way to the sink', async () => {
  /** The assertion is that a row *reached the sink*, never that nothing
   *  threw. CLAUDE.md's interaction-log section: the context default records
   *  nothing and fails at nothing, so "the boundary was never given a log"
   *  and "the boundary reports correctly" are the same observation to any
   *  test that only checks for absence. Rendering `LoggedErrorBoundary`
   *  outside `InteractionLogProvider` makes this test fail. */
  const sink = spySink()

  const { unmount } = render(
    <InteractionLogProvider sink={sink} view="project/entity">
      <LoggedErrorBoundary where="console">
        <Boom />
      </LoggedErrorBoundary>
    </InteractionLogProvider>,
  )
  unmount()
  await Promise.resolve()

  const raised = streamOf(sink).find((event) => event.kind === 'RenderErrorRaised')
  expect(raised?.payload).toEqual({
    where: 'console',
    error_name: 'TypeError',
    // A length, not the text: the message is the field most likely to carry a
    // path or a fragment of somebody's query, and the vocabulary records free
    // text as shape unless it is on `TEXT_BEARING_FIELDS`.
    message_length: 'cannot read properties of null'.length,
  })
})

it('reports a retry as ActionRetried rather than as a second error kind', async () => {
  const sink = spySink()

  const { unmount } = render(
    <InteractionLogProvider sink={sink} view="project/entity">
      <LoggedErrorBoundary where="console">
        <Boom />
      </LoggedErrorBoundary>
    </InteractionLogProvider>,
  )
  await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
  unmount()
  await Promise.resolve()

  const retried = streamOf(sink).filter((event) => event.kind === 'ActionRetried')
  expect(retried.map((event) => event.payload)).toEqual([
    { action_kind: 'render', attempt_number: 1 },
    // The retry re-renders the subtree, which throws again -- so the second
    // `RenderErrorRaised` is expected and is not what this asserts on.
  ])
})

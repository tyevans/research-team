import { render } from '@testing-library/react'
import { StrictMode } from 'react'
import { afterEach, expect, it, vi } from 'vitest'

import { FLUSH_INTERVAL_MS } from '@application/interaction-log/emitter.ts'

import { InteractionLogProvider, useInteractionLog } from './interaction-log-provider.tsx'

const Probe = () => {
  const log = useInteractionLog()
  log.record('EntityOpened', { entity_id: 'a', source: 'graph' })
  return null
}

/** Records nothing, so a test counting the stream counts only the provider's
 *  own events. `Probe` records during render, and StrictMode renders twice. */
const Quiet = () => null

interface Recorded {
  kind: string
  view: string
  project_id: string | null
  session_id: string | null
  browser_session_id: string
}

/** The provider's teardown defers its final exit-and-flush by one microtask,
 *  so that a StrictMode remount can cancel it. Nothing has reached the sink
 *  until that microtask has run. */
const settled = () => Promise.resolve()

const spySink = () => ({ send: vi.fn(async () => {}), sendOnUnload: vi.fn() })

/** Everything that reached the sink, by either route, in order. */
const streamOf = (sink: ReturnType<typeof spySink>): Recorded[] =>
  [...sink.send.mock.calls, ...sink.sendOnUnload.mock.calls].flatMap(
    (call) => call[0] as unknown as Recorded[],
  )

afterEach(() => {
  vi.useRealTimers()
})

it('records nothing and throws nothing without a provider', () => {
  /** Every component test in this suite renders without the provider. A hook
   *  that threw would turn one wiring decision into hundreds of failures. */
  expect(() => render(<Probe />)).not.toThrow()
})

it('hands the emitter to anything below it', async () => {
  /** Asserts the child's own `record` reached the batch, which is the only
   *  thing that distinguishes the real provider from a fragment. The version
   *  this replaces asserted `sink.send` had *not* been called, which is true
   *  with the provider deleted, with `SILENT` in its place, and with the whole
   *  commit reverted -- it constrained nothing. */
  const sink = spySink()

  const { unmount } = render(
    <InteractionLogProvider sink={sink} view="project/entity">
      <Probe />
    </InteractionLogProvider>,
  )
  unmount()
  await settled()

  expect(streamOf(sink).map((event) => event.kind)).toContain('EntityOpened')
})

it('reports the view it was given', async () => {
  const sink = spySink()

  const { unmount } = render(
    <InteractionLogProvider sink={sink} view="project/timeline">
      <Probe />
    </InteractionLogProvider>,
  )
  unmount()
  await settled()

  // Through sendOnUnload, not send: teardown runs dwell.exit() and
  // emitter.flushOnUnload(), which is wired to sink.sendOnUnload by design
  // (dwell.ts's own pagehide handler and emitter.ts's flushOnUnload both go
  // there, never through send/flush). The brief's step-1 sketch asserted
  // sink.send here, which this suite's own unmount path never calls --
  // proved by running that version first and watching it fail with an
  // empty sink.send.mock.calls rather than a missing view.
  expect(streamOf(sink).some((event) => event.view === 'project/timeline')).toBe(true)
})

it('stamps a view exit with the project that view belonged to', async () => {
  /** The dwell of a page is the log's headline measurement, and it was filed
   *  under the *next* page's ids: the `setContext` effect was declared above
   *  the `enter` effect, so a route change rewrote the context before
   *  `enter()`'s internal `exit()` recorded `ViewExited`. Fails on the
   *  `project_id` of the ViewExited row (was 'B'), not on the events existing.
   *  Swapping the two effects moves the defect onto ViewEntered rather than
   *  removing it, which is why the fix is one ordered effect. */
  const sink = spySink()

  const { rerender, unmount } = render(
    <InteractionLogProvider sink={sink} view="project/entity" projectId="A">
      <Quiet />
    </InteractionLogProvider>,
  )
  rerender(
    <InteractionLogProvider sink={sink} view="project/doc" projectId="B">
      <Quiet />
    </InteractionLogProvider>,
  )
  unmount()
  await settled()

  expect(streamOf(sink).map((event) => [event.kind, event.view, event.project_id])).toStrictEqual([
    ['ViewEntered', 'project/entity', 'A'],
    ['ViewExited', 'project/entity', 'A'],
    ['ViewEntered', 'project/doc', 'B'],
    ['ViewExited', 'project/doc', 'B'],
  ])
})

it('drops the session id only after the session view has been exited', async () => {
  /** The mirror case, and the one that loses data outright: navigating a
   *  session -> home stamped `session_id: null` on the single event carrying
   *  how long that session was read. */
  const sink = spySink()

  const { rerender, unmount } = render(
    <InteractionLogProvider sink={sink} view="session" sessionId="S">
      <Quiet />
    </InteractionLogProvider>,
  )
  rerender(
    <InteractionLogProvider sink={sink} view="home">
      <Quiet />
    </InteractionLogProvider>,
  )
  unmount()
  await settled()

  const exited = streamOf(sink).find((event) => event.kind === 'ViewExited')
  expect(exited?.session_id).toBe('S')
})

it('keeps flushing on the interval after a StrictMode remount', async () => {
  /** `main.tsx` wraps the app in StrictMode unconditionally, so this is every
   *  `npm run dev`. The cleanup's `emitter.stop()` cleared the interval and
   *  the re-invoke started nothing, because the timer is created inside
   *  `createEmitter` and the emitter survives the remount. Measured before the
   *  fix: 0 sends in a 20 s window under StrictMode, 1 without. */
  vi.useFakeTimers()
  const sink = spySink()

  render(
    <StrictMode>
      <InteractionLogProvider sink={sink} view="project/entity">
        <Quiet />
      </InteractionLogProvider>
    </StrictMode>,
  )
  await vi.advanceTimersByTimeAsync(FLUSH_INTERVAL_MS * 4)

  expect(sink.send).toHaveBeenCalledTimes(1)
})

it('enters a view once on a StrictMode dev load', async () => {
  /** Dev-only noise, but it lands in the same `interactions.db` a developer
   *  inspects by hand -- which is the only place this feature's beacon path
   *  is verified at all. Measured before the fix: ViewEntered, ViewExited,
   *  ViewEntered, ViewExited with seq 1-4 for one mount and one unmount. */
  const sink = spySink()

  const { unmount } = render(
    <StrictMode>
      <InteractionLogProvider sink={sink} view="project/entity">
        <Quiet />
      </InteractionLogProvider>
    </StrictMode>,
  )
  unmount()
  await settled()

  expect(streamOf(sink).map((event) => event.kind)).toStrictEqual(['ViewEntered', 'ViewExited'])
})

it('keeps one browser session across a change of sink identity', async () => {
  /** `useMemo` is a hint, not a cache: React may discard it, and a discarded
   *  emitter mints a second `browser_session_id` and restarts `seq` at 1
   *  mid-page-load -- breaking the `(browser_session_id, seq)` key the server
   *  dedupes on. A discard cannot be forced from a test, so this pins the
   *  observable half of the same change: the emitter is per page load, not per
   *  `sink` identity. Fails against `useMemo(..., [sink])`, which mints a
   *  second id on the re-render below. */
  const sink = spySink()

  const { rerender, unmount } = render(
    <InteractionLogProvider sink={{ ...sink }} view="home">
      <Quiet />
    </InteractionLogProvider>,
  )
  rerender(
    <InteractionLogProvider sink={sink} view="home">
      <Quiet />
    </InteractionLogProvider>,
  )
  unmount()
  await settled()

  expect(new Set(streamOf(sink).map((event) => event.browser_session_id)).size).toBe(1)
})

it('guards flushOnUnload against a throwing sink', async () => {
  /** The guard itself lives in `emitter.ts` (`flushOnUnload`'s own
   *  try/catch), not in this provider -- `dwell.ts`'s `onPageHide` calls
   *  `emitter.flushOnUnload()` directly, so a guard only here would miss
   *  that path. This is an integration test through the provider's real
   *  teardown, proving the two are actually wired together: it would fail
   *  (an uncaught throw during unmount) if either the emitter's guard or
   *  this provider's use of `flushOnUnload` on cleanup were removed.
   *
   *  The teardown is now a microtask, so an escaping throw surfaces as an
   *  unhandled error rather than out of `unmount()` -- vitest fails the file
   *  on that, which is why `await settled()` is what makes this test bite. */
  const sink = {
    send: vi.fn(async () => {}),
    sendOnUnload: vi.fn(() => {
      throw new Error('sendBeacon exploded')
    }),
  }

  const { unmount } = render(
    <InteractionLogProvider sink={sink} view="project/entity">
      <Probe />
    </InteractionLogProvider>,
  )

  expect(() => unmount()).not.toThrow()
  await settled()
})

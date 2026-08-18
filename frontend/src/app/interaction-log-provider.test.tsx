import { render } from '@testing-library/react'
import { expect, it, vi } from 'vitest'

import { InteractionLogProvider, useInteractionLog } from './interaction-log-provider.tsx'

const Probe = () => {
  const log = useInteractionLog()
  log.record('EntityOpened', { entity_id: 'a', source: 'graph' })
  return null
}

it('records nothing and throws nothing without a provider', () => {
  /** Every component test in this suite renders without the provider. A hook
   *  that threw would turn one wiring decision into hundreds of failures. */
  expect(() => render(<Probe />)).not.toThrow()
})

it('hands the emitter to anything below it', () => {
  const sink = { send: vi.fn(async () => {}), sendOnUnload: vi.fn() }

  render(
    <InteractionLogProvider sink={sink} view="project/entity">
      <Probe />
    </InteractionLogProvider>,
  )

  expect(sink.send).not.toHaveBeenCalled()
})

it('reports the view it was given', async () => {
  const sink = { send: vi.fn(async () => {}), sendOnUnload: vi.fn() }

  const { unmount } = render(
    <InteractionLogProvider sink={sink} view="project/timeline">
      <Probe />
    </InteractionLogProvider>,
  )
  unmount()

  // Through sendOnUnload, not send: teardown runs dwell.exit() and
  // emitter.flushOnUnload(), which is wired to sink.sendOnUnload by design
  // (dwell.ts's own pagehide handler and emitter.ts's flushOnUnload both go
  // there, never through send/flush). The brief's step-1 sketch asserted
  // sink.send here, which this suite's own unmount path never calls --
  // proved by running that version first and watching it fail with an
  // empty sink.send.mock.calls rather than a missing view.
  const batch = sink.sendOnUnload.mock.calls[0]?.[0] as { view: string }[] | undefined
  expect(batch?.some((event) => event.view === 'project/timeline')).toBe(true)
})

it('guards flushOnUnload against a throwing sink', () => {
  /** The guard itself lives in `emitter.ts` (`flushOnUnload`'s own
   *  try/catch), not in this provider -- `dwell.ts`'s `onPageHide` calls
   *  `emitter.flushOnUnload()` directly, so a guard only here would miss
   *  that path. This is an integration test through the provider's real
   *  teardown, proving the two are actually wired together: it would fail
   *  (an uncaught throw during unmount) if either the emitter's guard or
   *  this provider's use of `flushOnUnload` on cleanup were removed. */
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
})

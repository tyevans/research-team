import { expect, it, vi } from 'vitest'

import { createDwellTracker } from './dwell.ts'

/** Dwell is a measurement, and jsdom measures nothing: it implements no page
 *  lifecycle, so `visibilitychange` and `pagehide` never fire, and
 *  `performance.now()` does not advance the way it does in a browser. Written
 *  as a jsdom test, every assertion below would have had to be a comment --
 *  which CLAUDE.md records happening four times in a row here.
 */

const recorder = () => {
  const events: { kind: string; payload: Record<string, unknown> }[] = []
  return {
    events,
    record: vi.fn((kind: string, payload: Record<string, unknown> = {}) => {
      events.push({ kind, payload })
    }),
    setContext: vi.fn(),
    start: vi.fn(),
    flush: vi.fn(async () => {}),
    flushOnUnload: vi.fn(),
    stop: vi.fn(),
    pending: vi.fn(() => 0),
  }
}

/** Playwright cannot background a tab it is driving, so `document.hidden`
 *  never flips on its own here. This stubs `visibilityState` for the
 *  duration of one test and restores it afterward -- it pins the tracker's
 *  accounting given a visibility change, not the browser's own visibility
 *  behaviour, which is a real limit of what this test can prove. */
const stubVisibility = (state: DocumentVisibilityState) => {
  const original = Object.getOwnPropertyDescriptor(Document.prototype, 'visibilityState')
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => state,
  })
  return () => {
    if (original) Object.defineProperty(document, 'visibilityState', original)
  }
}

it('reports a dwell that grew with real elapsed time', async () => {
  const emitter = recorder()
  const tracker = createDwellTracker({ emitter })

  tracker.enter('project/timeline')
  await new Promise((resolve) => setTimeout(resolve, 60))
  tracker.exit()

  const exited = emitter.events.find((event) => event.kind === 'ViewExited')
  expect(exited).toBeDefined()
  expect(exited?.payload.dwell_ms as number).toBeGreaterThanOrEqual(50)
})

it('reports entering and exiting in order', () => {
  const emitter = recorder()
  const tracker = createDwellTracker({ emitter })

  tracker.enter('home')
  tracker.enter('project/entity')

  expect(emitter.events.map((event) => event.kind)).toEqual([
    'ViewEntered',
    'ViewExited',
    'ViewEntered',
  ])
})

it('does not report an exit for a view never entered', () => {
  const emitter = recorder()

  createDwellTracker({ emitter }).exit()

  expect(emitter.events).toHaveLength(0)
})

it('counts hidden time separately from dwell', () => {
  /** Without this, "stalled here for four minutes" and "went to lunch" are
   *  the same event, and the attention half of the log is worthless.
   *
   *  `visibilityState` is stubbed 'hidden' before the dispatch so the
   *  handler's own read of it takes the hidden branch -- with the real,
   *  always-'visible' jsdom/Chromium-under-Playwright state, the first
   *  dispatch would take AttentionRegained instead and this would pin
   *  nothing. */
  const emitter = recorder()
  let time = 0
  const tracker = createDwellTracker({ emitter, clock: () => time })
  const detach = tracker.attach()

  try {
    tracker.enter('project/timeline')
    time = 1_000
    const restore = stubVisibility('hidden')
    document.dispatchEvent(new Event('visibilitychange'))
    time = 5_000
    restore()
    tracker.exit()

    const exited = emitter.events.find((event) => event.kind === 'ViewExited')
    expect(exited?.payload.dwell_ms).toBe(5_000)
    expect(exited?.payload.hidden_ms as number).toBeGreaterThan(0)
  } finally {
    detach()
  }
})

it('stops listening when detached', () => {
  const emitter = recorder()
  const tracker = createDwellTracker({ emitter })
  const detach = tracker.attach()

  detach()
  window.dispatchEvent(new Event('pagehide'))

  expect(emitter.flushOnUnload).not.toHaveBeenCalled()
})

it('flushes by beacon on pagehide', () => {
  const emitter = recorder()
  const detach = createDwellTracker({ emitter }).attach()
  try {
    window.dispatchEvent(new Event('pagehide'))

    expect(emitter.flushOnUnload).toHaveBeenCalled()
  } finally {
    detach()
  }
})

it('does not restart the hidden clock on a repeated hide', () => {
  const emitter = recorder()
  // An explicit clock rather than `performance.now()`: the loss this pins is
  // arithmetic, and "hidden_ms is smaller than it should be" needs a known
  // number to be smaller than.
  let ticks = 0
  const tracker = createDwellTracker({ emitter, clock: () => ticks })
  const detach = tracker.attach()
  // Entered while visible, then hidden: `enter()` starts its own
  // `hiddenSince` if the tab is already hidden, which would make the first
  // event below the *second* hide rather than the first.
  tracker.enter('home')
  const restore = stubVisibility('hidden')
  try {
    document.dispatchEvent(new Event('visibilitychange'))
    ticks = 100
    // A second hidden->hidden transition. Without the guard this overwrites
    // `hiddenSince`, so the 100 ticks already hidden are discarded --
    // `hidden_ms` comes back 50 rather than 150 -- and the log gains an
    // `AttentionLost` answering nothing.
    document.dispatchEvent(new Event('visibilitychange'))
    ticks = 150
    tracker.exit()

    expect(emitter.events.filter((event) => event.kind === 'AttentionLost')).toHaveLength(1)
    const exited = emitter.events.find((event) => event.kind === 'ViewExited')
    expect(exited?.payload.hidden_ms).toBe(150)
  } finally {
    restore()
    detach()
  }
})

it('does not report attention regained when none was lost', () => {
  const emitter = recorder()
  const tracker = createDwellTracker({ emitter })
  const detach = tracker.attach()
  const restore = stubVisibility('visible')
  try {
    tracker.enter('home')
    // A visible-without-a-preceding-hide transition. Browsers do fire one --
    // on initial load, and whenever a tracker attaches to an already-visible
    // tab -- so this is the ordinary case, not a contrived one.
    document.dispatchEvent(new Event('visibilitychange'))

    // Reverting the `hiddenSince === null` guard in `onVisibility` fails this
    // on the length assertion: the log gains an `AttentionRegained` answering
    // no `AttentionLost`. `hidden_ms` is right either way, which is what makes
    // the defect invisible to any test that only checks the arithmetic.
    expect(emitter.events.filter((event) => event.kind === 'AttentionRegained')).toHaveLength(0)
  } finally {
    restore()
    detach()
  }
})

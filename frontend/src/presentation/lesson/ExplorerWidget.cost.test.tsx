/** What every reader interaction costs, which is the whole engineering content
 *  of this widget.
 *
 * Measured, not reasoned, and the measurement is upstream: `GET /timeline` is
 * two full passes over the tenant's entire entity set
 * (`timeline_reader.py:108-115`) and is deliberately uncached, and `limit`
 * never reaches the store (`graph_reader.py:294-299`) so it does not govern
 * that cost. A `timeline` block pays that once. An explorer hands the reader a
 * control that can pay it per keystroke.
 *
 * Alone in its own file rather than folded into `ExplorerWidget.test.tsx`,
 * deliberately. The design's section 7 calls this "the requirement most likely
 * to be quietly lost in a later refactor", and a file named for the
 * requirement is harder to delete by accident than three assertions among
 * twenty. It also means these run alone in a second while iterating.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'

import type { AttemptsApi } from '@application/lesson/use-attempts.ts'
import { componentBlock } from '@presentation/ask/ask-fixtures.ts'

import { ExplorerWidget } from './ExplorerWidget.tsx'
import { band, harness, PROJECT } from './timeline-widget-harness.tsx'

vi.mock('../research/TimelineCanvas.tsx', () => ({
  TimelineCanvas: ({ bands }: { bands: readonly unknown[] }) => (
    <div data-testid="timeline-canvas" data-bands={bands.length} />
  ),
}))

const EXPLORER = {
  over: 'timeline',
  prompt: 'Pull the window back.',
  vary: ['entity_type', 'window'],
  from: '0300-01-01',
  to: '0400-01-01',
}

const mount = (data: Record<string, unknown> = EXPLORER) => {
  const timeline = vi
    .fn()
    .mockResolvedValue({ bands: [band('b1')], undatedCount: 0, truncated: false })
  render(
    <ExplorerWidget
      block={componentBlock({ type: 'explorer', id: 'e1', data })}
      attempts={{} as unknown as AttemptsApi}
      projectId={PROJECT}
    />,
    { wrapper: harness(timeline) },
  )
  return timeline
}

const from = () => screen.getByLabelText(/^from$/i)

/** A real macrotask gap, for the assertions that a request did *not* happen.
 *  `waitFor` cannot prove a negative and `await Promise.resolve()` does not
 *  drain a fetch TanStack Query would have scheduled. */
const settle = () => new Promise((resolve) => setTimeout(resolve, 20))

/** Real timers back for whoever runs next. Only one case fakes the clock, and a
 *  leaked fake clock does not fail that case -- it fails an unrelated one later,
 *  which is how a deterministic bug gets filed as flakiness (`CLAUDE.md`, "A
 *  failure under load is not evidence"). */
afterEach(() => {
  vi.useRealTimers()
})

it('issues one request when the window control is released, not one per change', async () => {
  // The failure this exists against is not hypothetical: a controlled
  // `<input type="date">` wired straight to the query key issues a request per
  // edit, so a reader adjusting a bound twice pays four full passes over the
  // corpus for one intention.
  //
  // Red against a widget that puts the draft value in the query key.
  const timeline = mount()
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(1))

  fireEvent.change(from(), { target: { value: '0200-01-01' } })
  fireEvent.change(from(), { target: { value: '0250-01-01' } })
  fireEvent.change(from(), { target: { value: '0280-01-01' } })

  // Nothing yet: three edits, and the reader has not finished deciding.
  expect(timeline).toHaveBeenCalledTimes(1)

  fireEvent.blur(from())

  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(2))
  expect(timeline).toHaveBeenLastCalledWith(PROJECT, {
    from: '0280-01-01',
    to: '0400-01-01',
  })
})

it('issues nothing at all when a released window is the one already showing', async () => {
  // A blur with no edit behind it -- tabbing through the controls -- must not
  // cost a double pass. Red against a widget that commits on every blur by
  // rebuilding the window object: `setState` to an equal *object* is not equal
  // to React, so the key changes identity and the query refires.
  const timeline = mount()
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(1))

  fireEvent.blur(from())
  fireEvent.blur(from())

  await settle()
  expect(timeline).toHaveBeenCalledTimes(1)
})

it('costs nothing to return to a parameter set already seen this session', async () => {
  // The second half of the design's section 4: "a reader returning to a
  // setting they already tried must not pay for it twice." This is what
  // `resolvedWidgetQuery`'s `staleTime` and `refetchOnMount: false` buy,
  // combined with a key carrying every bound.
  //
  // Red two ways, and both look fine on screen: a widget that omits
  // `...resolvedWidgetQuery` refetches the stale entry and comes back 3; a
  // widget keyed on the project alone never varies its key, comes back 1, and
  // shows the first window's bands under the third window's controls.
  const timeline = mount()
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(1))

  fireEvent.change(from(), { target: { value: '0200-01-01' } })
  fireEvent.blur(from())
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(2))

  fireEvent.change(from(), { target: { value: '0300-01-01' } })
  fireEvent.blur(from())

  await settle()
  expect(timeline).toHaveBeenCalledTimes(2)
})

it('asks once, not twice, when the author fixed no entity type', async () => {
  // The vocabulary read and the display read are the same request here: both
  // are built from `queryKeys.timeline` and both omit `entityType`, so
  // TanStack Query dedupes them to one fetch. That is the design's section 1
  // -- "one request gives the widget both its initial view and its full picker
  // vocabulary" -- and it holds only while the two keys are built the same
  // way. Red against a vocabulary query given a key of its own.
  const timeline = mount({ over: 'timeline', prompt: 'Look.', vary: ['entity_type', 'window'] })

  await waitFor(() => expect(screen.getByTestId('timeline-canvas')).toBeInTheDocument())
  await settle()
  expect(timeline).toHaveBeenCalledTimes(1)
})

it('pays a second read on mount only when the author fixed a type it must vary past', async () => {
  // The honest cost of the picker, asserted rather than tolerated: an explorer
  // that starts filtered needs an unfiltered read to know what else is in
  // there. Two reads, once, cached for the session -- not two per
  // interaction, which is what this number stops a later refactor becoming.
  const timeline = mount({ ...EXPLORER, entity_type: 'Person' })

  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(2))
  await settle()
  expect(timeline).toHaveBeenCalledTimes(2)
  // `call` is annotated rather than inferred: `vi.fn()` with no generic types
  // its calls as `any[]`, and the lint forbids returning one from a `.map`.
  expect(timeline.mock.calls.map((call: unknown[]) => call[1])).toEqual(
    expect.arrayContaining([
      { entityType: 'Person', from: '0300-01-01', to: '0400-01-01' },
      { from: '0300-01-01', to: '0400-01-01' },
    ]),
  )
})

it('pays that second read again on each window commit, and no more than that', async () => {
  // The mount case above is only half the promise the widget's docstring makes.
  // A committed window moves *both* keys -- the display read carries the type,
  // the vocabulary read must re-ask what types exist inside the new window --
  // so a filtered explorer costs two double passes per reader intention rather
  // than one. Two, not three or four: this is the number a later refactor would
  // inflate by giving the vocabulary query a key of its own or by dropping the
  // draft, and it is asserted rather than left to be discovered.
  const timeline = mount({ ...EXPLORER, entity_type: 'Person' })
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(2))

  fireEvent.change(from(), { target: { value: '0200-01-01' } })
  fireEvent.change(from(), { target: { value: '0280-01-01' } })
  fireEvent.blur(from())

  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(4))
  await settle()
  expect(timeline).toHaveBeenCalledTimes(4)
  expect(timeline.mock.calls.slice(2).map((call: unknown[]) => call[1])).toEqual(
    expect.arrayContaining([
      { entityType: 'Person', from: '0280-01-01', to: '0400-01-01' },
      { from: '0280-01-01', to: '0400-01-01' },
    ]),
  )
})

it('is still free to revisit after the shared five-minute policy would have gone stale', async () => {
  // The one case the other five cannot see: they run in milliseconds, so a
  // widget that dropped its overrides back to `resolvedWidgetQuery`'s five
  // minutes passes all of them. The design's section 4 means the sitting, not
  // five minutes -- a reader comparing four windows over a coffee returns to
  // the first and must not pay the double pass again.
  //
  // Fake timers, and `settle()` is deliberately not used inside this case: a
  // faked clock never fires its `setTimeout`, so awaiting one deadlocks until
  // vitest's own timeout. `advanceTimersByTimeAsync` is the equivalent -- it
  // moves the clock and drains the microtasks a resolved fetch left behind.
  vi.useFakeTimers()
  const timeline = mount()
  await vi.advanceTimersByTimeAsync(0)
  expect(timeline).toHaveBeenCalledTimes(1)

  fireEvent.change(from(), { target: { value: '0200-01-01' } })
  fireEvent.blur(from())
  await vi.advanceTimersByTimeAsync(0)
  expect(timeline).toHaveBeenCalledTimes(2)

  // Six minutes of the reader looking at the second window: past the shared
  // policy's staleness window, and past the default `gcTime` with it.
  await vi.advanceTimersByTimeAsync(6 * 60_000)

  fireEvent.change(from(), { target: { value: '0300-01-01' } })
  fireEvent.blur(from())
  await vi.advanceTimersByTimeAsync(20)

  expect(timeline).toHaveBeenCalledTimes(2)
})

it('commits on Enter as well as on blur, and an Enter with nothing edited is free', async () => {
  // Blur is one release gesture; Enter is the other, and the controls sit in a
  // `<fieldset>` rather than a `<form>` deliberately (see `Controls`), so there
  // is no implicit submit to fall back on. Without a key handler a reader who
  // types a bound and presses Enter sees the widget sit there unchanged with no
  // feedback -- which is what this was proved red against before `onKeyDown`
  // existed: the first `waitFor` timed out at one call.
  //
  // The second half is the cost half, and it is why this case lives in this
  // file rather than beside the prose assertions: Enter must go through the
  // same guarded commit as blur, so pressing it having changed nothing must not
  // pay a double pass. Red against a handler that calls `onCommit` directly.
  const timeline = mount()
  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(1))

  fireEvent.change(from(), { target: { value: '0200-01-01' } })
  fireEvent.keyDown(from(), { key: 'Enter' })

  await waitFor(() => expect(timeline).toHaveBeenCalledTimes(2))
  expect(timeline).toHaveBeenLastCalledWith(PROJECT, {
    from: '0200-01-01',
    to: '0400-01-01',
  })

  fireEvent.keyDown(from(), { key: 'Enter' })
  await settle()
  expect(timeline).toHaveBeenCalledTimes(2)
})

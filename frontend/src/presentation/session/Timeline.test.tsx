import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'
import { expect, it, vi } from 'vitest'

import type { ActivityEntry } from '@domain/activity/activity.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'

import { Timeline } from './Timeline.tsx'

/** The keyboard model of the event log, which had no test at all.
 *
 * `docs/component-system-spec.md` §10 names this component first among phase
 * 4's prerequisites and calls it the expensive one, for a reason it lists:
 * roving tabindex, vi keys, `Home`/`End`/`Escape`, the HEAD marker one past
 * the end, the column cursor, and a `stopPropagation` so one Escape does not
 * fold twice. Six behaviours, no test, and phase 4 changes the keyboard model
 * on purpose. A redesign here is a redesign without a net until this file
 * exists.
 *
 * **Every case below was proved red** against a deliberately broken
 * `Timeline`. Six breaks were used, and what each one took down is worth
 * recording exactly, because two of the results are *not* one-break-one-test
 * and reading them as such would overstate the net:
 *
 * | Break | Fails |
 * |---|---|
 * | roving `tabIndex` pinned to `0` | 9 of 11 |
 * | `j`/`k` removed from the key list | `moves with j and k` |
 * | `Escape` removed from the `End` branch | `treats Escape as "back to live"` **and** `stops one Escape` |
 * | HEAD clamp lowered `total + 1` → `total` | `reaches HEAD` and `does not walk off either end` |
 * | column reset dropped from the vertical branch | `puts the cursor back` |
 * | `stopPropagation` deleted | `stops one Escape` |
 *
 * The nine are not nine independent claims: `tabStop()` is the shared helper
 * and it asserts there is exactly one tab stop, so pinning `tabIndex` fails
 * every case that calls it. That is a helper coupling rather than nine
 * separate proofs, and it is the reason the count is written here instead of
 * being left to look like breadth.
 *
 * `stops one Escape` failing under the *Escape* break is likewise expected
 * rather than a bonus: with `Escape` dropped from the branch, `next` is
 * `null` and the handler returns before it reaches `stopPropagation` at all.
 * So that case pins two things at once -- Escape being handled, and being
 * handled without escaping the grid -- and only the second is what its name
 * promises.
 *
 * **What this file deliberately does not assert:** appearance, scrolling
 * (`scrollIntoView` is not implemented in jsdom and `vitest.setup.ts` says
 * so), and the row *contents* -- `humaniseEventType`, truncation and the
 * path-deduplication rule are the domain's and are tested there.
 *
 * One case documents a defect rather than a virtue. See `the column cursor is
 * invisible` below: S-D7 is real, this file pins its current behaviour so
 * phase 4 changes it deliberately rather than by accident, and the test says
 * plainly that what it asserts is not what a reader should get.
 */

const entry = (index: number, over: Partial<LogEntry> = {}): LogEntry => ({
  index: EventIndex(index),
  type: 'FileWritten',
  occurredAt: '2026-08-10T12:00:00Z',
  summary: `event ${index}`,
  path: null,
  turnIndex: null,
  isError: false,
  cancelled: null,
  ...over,
})

const LOG: readonly LogEntry[] = [entry(1), entry(2), entry(3)]

const NO_FRESH = new Map<EventIndex, number>()
const NO_DISCARDED = new Map<EventIndex, readonly ActivityEntry[]>()

/** A caller that owns the scrub point, because `Timeline` does not: it reports
 *  a move and re-renders with whatever it is given. A test passing a fixed
 *  `scrub` could observe the first keystroke and never the second, which is
 *  where every off-by-one in this component would live. */
const Log = ({
  log = LOG,
  start = ScrubPoint.head(),
  onFork = () => {},
  onSelect,
}: {
  log?: readonly LogEntry[]
  start?: ScrubPoint
  onFork?: (at: EventIndex) => void
  onSelect?: (at: ScrubPoint) => void
}) => {
  const [scrub, setScrub] = useState(start)
  return (
    <Timeline
      log={log}
      scrub={scrub}
      fresh={NO_FRESH}
      discarded={NO_DISCARDED}
      onFork={onFork}
      onSelect={(at) => {
        setScrub(at)
        onSelect?.(at)
      }}
    />
  )
}

/** The row carrying the tab stop. There must be exactly one, which is the
 *  whole claim of a roving tabindex, so this asserts the count rather than
 *  taking the first match. */
const tabStop = () => {
  const stops = screen.getAllByRole('row').filter((row) => row.getAttribute('tabindex') === '0')
  expect(stops).toHaveLength(1)
  return stops[0]!
}

it('puts exactly one row in the tab order, and moves it with the selection', async () => {
  const user = userEvent.setup()
  render(<Log />)

  // HEAD to begin with, which is the selection a session opens on.
  expect(tabStop()).toHaveAttribute('id', 'ev-head')

  tabStop().focus()
  await user.keyboard('{ArrowUp}')

  // Fails with `tabIndex` pinned to 0: every row is a tab stop, so `tabStop()`
  // finds four and the length assertion fails before anything about movement
  // is even reached. That is the point of asserting the count -- a hundred-row
  // log with a hundred tab stops is a keyboard user tabbing a hundred times to
  // leave the timeline.
  expect(tabStop()).toHaveAttribute('id', 'ev-3')
})

it('moves with j and k as well as the arrows', async () => {
  const user = userEvent.setup()
  render(<Log start={ScrubPoint.at(EventIndex(2))} />)

  tabStop().focus()
  await user.keyboard('k')
  expect(tabStop()).toHaveAttribute('id', 'ev-1')

  await user.keyboard('j')
  expect(tabStop()).toHaveAttribute('id', 'ev-2')

  // Undocumented anywhere a user would find it, which is S-D5/S-D6's
  // complaint and not this file's to fix. Asserted so that whoever *does*
  // document or remove them is doing it on purpose.
  await user.keyboard('{ArrowDown}')
  expect(tabStop()).toHaveAttribute('id', 'ev-3')
})

it('sends Home to the first event and End to HEAD', async () => {
  const user = userEvent.setup()
  render(<Log start={ScrubPoint.at(EventIndex(2))} />)

  tabStop().focus()
  await user.keyboard('{Home}')
  expect(tabStop()).toHaveAttribute('id', 'ev-1')

  await user.keyboard('{End}')
  expect(tabStop()).toHaveAttribute('id', 'ev-head')
})

it('treats Escape as “back to live”, not as a dismissal', async () => {
  const user = userEvent.setup()
  render(<Log start={ScrubPoint.at(EventIndex(1))} />)

  tabStop().focus()
  await user.keyboard('{Escape}')

  // Escape shares the `End` branch: in a component whose whole subject is
  // *where you are in time*, the way out of a historical position is to return
  // to the present. Fails with `Escape` removed from that branch -- the
  // selection stays on event 1 and the reader is stuck in the past with the
  // key they would reach for first.
  expect(tabStop()).toHaveAttribute('id', 'ev-head')
})

it('stops one Escape from also reaching the page behind it', async () => {
  const user = userEvent.setup()
  const outer = vi.fn()

  // On `document`, which is where the real listener is: `SessionView` calls
  // `document.addEventListener('keydown', …)` for its own Escape handling.
  // A wrapping `<div onKeyDown>` would have been the same test in shape, and
  // both `jsx-a11y/no-static-element-interactions` and honesty are against it
  // -- the rule because a div with a key handler and no role is not an
  // interactive element, and honesty because the thing this component has to
  // not disturb lives on the document, not on its parent.
  document.addEventListener('keydown', outer)
  try {
    render(<Log start={ScrubPoint.at(EventIndex(1))} />)

    tabStop().focus()
    await user.keyboard('{Escape}')

    // Fails with `stopPropagation` deleted: the outer handler runs too, so one
    // keypress scrubs to HEAD *and* does whatever the page does with Escape --
    // the "one keypress folds twice" the component's own comment names.
    expect(outer).not.toHaveBeenCalled()
  } finally {
    // In a `finally` so a failed assertion does not leak a document listener
    // into every test that runs after this one in the same file.
    document.removeEventListener('keydown', outer)
  }
})

it('reaches HEAD, which sits one past the last event', async () => {
  const user = userEvent.setup()
  const onSelect = vi.fn()
  render(<Log start={ScrubPoint.at(EventIndex(3))} onSelect={onSelect} />)

  tabStop().focus()
  await user.keyboard('{ArrowDown}')

  // Three events, so HEAD is row 4 and the clamp is `total + 1`. Fails with
  // the clamp lowered to `total`: ArrowDown from the last event does nothing,
  // and a reader who scrubbed into history can no longer arrow back to live.
  expect(onSelect).toHaveBeenLastCalledWith(ScrubPoint.head())
  expect(tabStop()).toHaveAttribute('id', 'ev-head')
})

it('does not walk off either end', async () => {
  const user = userEvent.setup()
  render(<Log start={ScrubPoint.at(EventIndex(1))} />)

  tabStop().focus()
  await user.keyboard('{ArrowUp}{ArrowUp}{ArrowUp}')
  expect(tabStop()).toHaveAttribute('id', 'ev-1')

  await user.keyboard('{End}{ArrowDown}{ArrowDown}')
  expect(tabStop()).toHaveAttribute('id', 'ev-head')
})

/** **S-D7, closed.**
 *
 *  This case previously asserted the *defect*: that the row's markup was
 *  byte-identical before and after `→`, so a keyboard user had silently
 *  rearmed `Enter` from "scrub to this event" to "fork a new session" with no
 *  way to tell. Its note said that when phase 4 landed a visible cursor this
 *  test should fail and be rewritten rather than deleted. It did, and this is
 *  the rewrite.
 *
 *  What replaces it asserts the same mode change is still real -- `Enter`
 *  after `→` still forks, which is the useful behaviour -- and that it is now
 *  *announced*: the cell carries an id and an `aria-colindex`, and the focused
 *  row points `aria-activedescendant` at it. The visible ring is CSS and jsdom
 *  computes none, so the class is asserted here and the appearance is phase
 *  6's. */
it('announces which column the cursor is on, and forks from the fork column', async () => {
  const user = userEvent.setup()
  const onFork = vi.fn()
  render(<Log start={ScrubPoint.at(EventIndex(2))} onFork={onFork} />)

  const row = tabStop()
  row.focus()

  // Starts on the event column, which is what makes `Enter` mean "scrub" until
  // somebody says otherwise.
  expect(row).toHaveAttribute('aria-activedescendant', 'ev-2-c1')

  await user.keyboard('{ArrowRight}')

  // The mode is now three separate things a reader or a screen reader can
  // observe, where before it was none: the descendant pointer moved, the cell
  // says which column it is, and it carries the class the stylesheet rings.
  const cursorCell = document.getElementById('ev-2-c2')
  expect(tabStop()).toHaveAttribute('aria-activedescendant', 'ev-2-c2')
  expect(cursorCell).toHaveAttribute('aria-colindex', '2')
  expect(cursorCell).toHaveClass('ev-cursor')

  // And the behaviour it announces is unchanged -- this is a fix to the
  // *reporting* of the mode, not a removal of it. Forking from the keyboard is
  // still reachable, which is the thing the column exists for.
  await user.keyboard('{Enter}')
  expect(onFork).toHaveBeenCalledWith(EventIndex(2))
})

it('will not put the cursor on HEAD, whose action cell is empty', async () => {
  const user = userEvent.setup()
  const onFork = vi.fn()
  const onSelect = vi.fn()
  render(<Log onFork={onFork} onSelect={onSelect} />)

  const head = tabStop()
  expect(head).toHaveAttribute('id', 'ev-head')
  head.focus()

  await user.keyboard('{ArrowRight}')
  expect(tabStop()).not.toHaveAttribute('aria-activedescendant')

  await user.keyboard('{Enter}')
  expect(onFork).not.toHaveBeenCalled()
  expect(onSelect).toHaveBeenLastCalledWith(ScrubPoint.head())

  // **The assertion that makes this test falsifiable is the next one**, and
  // finding it was the point of applying the break rather than reasoning about
  // it. Everything above passes with the `selectedIndex === null` guard
  // removed, because HEAD's row renders no cursor either way and `Enter` on
  // HEAD already fell through to "scrub" via a *different* guard.
  //
  // The guard earns itself on this path: `→` on HEAD arms the column, a
  // *click* selects a row without going through the vertical branch that would
  // have reset it, and the next `Enter` forks a session the reader only meant
  // to scrub to. Clicking is how the cursor escapes the keyboard model, and it
  // is the one route that does not reset.
  await user.click(screen.getByText('event 2'))
  await user.keyboard('{Enter}')

  expect(onFork).not.toHaveBeenCalled()
})

it('puts the cursor back on the event column when the selection moves', async () => {
  const user = userEvent.setup()
  const onFork = vi.fn()
  const onSelect = vi.fn()
  render(<Log start={ScrubPoint.at(EventIndex(2))} onFork={onFork} onSelect={onSelect} />)

  tabStop().focus()
  await user.keyboard('{ArrowRight}{ArrowUp}{Enter}')

  // Fails with the `setColumn(0)` dropped from the vertical branch: the cursor
  // stays on the fork column across the move, so Enter forks a row the reader
  // arrowed onto expecting to scrub to it. That is the invisible cursor's
  // sharpest edge, and the reset is the only thing blunting it today.
  expect(onFork).not.toHaveBeenCalled()
  expect(onSelect).toHaveBeenLastCalledWith(ScrubPoint.at(EventIndex(1)))
})

it('says the log is empty rather than drawing an empty grid', () => {
  render(<Log log={[]} />)

  expect(screen.getByText('The log is empty.')).toBeInTheDocument()
  expect(screen.queryByRole('grid')).not.toBeInTheDocument()
})

it('counts the HEAD marker in the grid’s row count', () => {
  render(<Log />)

  // Three events plus HEAD. `aria-rowcount` that disagrees with what a screen
  // reader can reach is worse than none, because it is a number the reader is
  // told to trust.
  expect(screen.getByRole('grid')).toHaveAttribute('aria-rowcount', '4')
})

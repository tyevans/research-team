import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { EventIndex } from '@domain/session/event-index.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import { TurnState, type TurnNote } from '@domain/session/turn.ts'

import { Composer } from './Composer.tsx'

/** Sending a turn, and every state in which you cannot.
 *
 * Fourth of phase 4's six prerequisites (§10). The component is small and its
 * rules are all *refusals*, which is why it needs a test: every one of them is
 * a thing that does not happen, and a thing that does not happen leaves no
 * trace when it breaks. A composer that sends a blank turn, or sends a second
 * turn while the first is in flight, looks fine in a screenshot.
 *
 * **Proved red** against three breaks: the `!draft.trim()` guard removed;
 * `setDraft('')` removed after a send; and the `ctrlKey || metaKey` condition
 * widened to bare Enter. Each failed one case, the one it names.
 *
 * A fourth break was tried and **did not fail anything**, which is recorded
 * here rather than quietly dropped: removing the `busy` check from `submit`
 * leaves every case green, because a disabled textarea fires no `keydown` and
 * a disabled button fires no `click`, so nothing in this harness reaches
 * `submit` while a turn is in flight. The guard is still correct -- `busy` can
 * turn true from a stream frame between the render a reader sees and the
 * keypress they make -- but that race is not reachable from here, and
 * `will not send a second turn while one is in flight` says so at the point it
 * would otherwise be assumed.
 *
 * **What this does not assert:** the elapsed-time labels. `useTick` repaints
 * once a second off `Date.now()`, and pinning "turn in flight · 3s" would make
 * this file a clock test. `format.ts` owns `elapsed`/`elapsedSince` and is
 * tested there.
 */

const composer = (over: Partial<Parameters<typeof Composer>[0]> = {}) =>
  render(
    <Composer
      turn={TurnState.idle()}
      note={null}
      scrub={ScrubPoint.head()}
      onSend={vi.fn()}
      onCancel={vi.fn()}
      onRecheck={vi.fn()}
      onJumpTo={vi.fn()}
      onTyping={vi.fn()}
      {...over}
    />,
  )

const box = () => screen.getByRole('textbox')

it('sends on Ctrl+Enter and clears the draft', async () => {
  const user = userEvent.setup()
  const onSend = vi.fn()
  composer({ onSend })

  await user.type(box(), 'what changed in the config?')
  await user.keyboard('{Control>}{Enter}{/Control}')

  expect(onSend).toHaveBeenCalledWith('what changed in the config?')
  // Clearing matters more than it looks: the turn is in flight and the
  // textarea is about to be disabled, so a draft left behind is text the
  // reader can see, cannot edit, and will find still sitting there when the
  // turn finishes -- reading as though it had not been sent.
  expect(box()).toHaveValue('')
})

it('sends on Cmd+Enter too', async () => {
  const user = userEvent.setup()
  const onSend = vi.fn()
  composer({ onSend })

  await user.type(box(), 'hello')
  await user.keyboard('{Meta>}{Enter}{/Meta}')

  expect(onSend).toHaveBeenCalledWith('hello')
})

it('treats bare Enter as a newline, not as send', async () => {
  const user = userEvent.setup()
  const onSend = vi.fn()
  composer({ onSend })

  await user.type(box(), 'first line{Enter}second line')

  // A turn is prose and prose has paragraphs. Fails with the modifier
  // condition widened to bare Enter, at which point a half-written thought is
  // sent the moment the reader reaches for a new line.
  expect(onSend).not.toHaveBeenCalled()
  expect(box()).toHaveValue('first line\nsecond line')
})

it('refuses to send nothing, or only whitespace', async () => {
  const user = userEvent.setup()
  const onSend = vi.fn()
  composer({ onSend })

  await user.click(screen.getByRole('button', { name: 'Send turn' }))
  expect(onSend).not.toHaveBeenCalled()

  await user.type(box(), '   \n  ')
  await user.click(screen.getByRole('button', { name: 'Send turn' }))

  // Trimmed for the *check* but not for the payload: what gets sent is the
  // draft as typed. The guard is about "is there anything here at all", which
  // is a different question from what the agent should receive.
  expect(onSend).not.toHaveBeenCalled()
})

it('will not send a second turn while one is in flight', async () => {
  const user = userEvent.setup()
  const onSend = vi.fn()
  composer({ turn: TurnState.sending(Date.now()), onSend })

  expect(box()).toBeDisabled()
  expect(screen.getByRole('button', { name: 'Running…' })).toBeDisabled()

  await user.keyboard('{Control>}{Enter}{/Control}')
  expect(onSend).not.toHaveBeenCalled()

  // **What is actually proved here is the `disabled` attribute, not the
  // `busy` check inside `submit`.** Removing that check leaves this test
  // green, which was checked rather than assumed: a disabled textarea fires
  // no `keydown` and a disabled button fires no `click`, so neither route
  // reaches `submit` at all and the guard inside it is unreachable from here.
  //
  // It is still right to keep the guard -- `busy` can turn true from a stream
  // frame between the render a reader is looking at and the keypress they
  // make, and then `submit` runs against a form that was enabled a moment
  // ago. That race is not reachable from this harness, so it is named rather
  // than asserted. Claiming this case covers "two guards" would be the kind of
  // reassurance §10's rule exists to stop.
})

it('offers to cancel only while a turn is running, and only once', async () => {
  const user = userEvent.setup()
  const onCancel = vi.fn()
  const { unmount } = composer()

  expect(screen.queryByRole('button', { name: 'Cancel turn' })).not.toBeInTheDocument()
  unmount()

  const running = composer({ turn: TurnState.sending(Date.now()), onCancel })
  await user.click(screen.getByRole('button', { name: 'Cancel turn' }))
  expect(onCancel).toHaveBeenCalledTimes(1)
  running.unmount()

  // Once asked for, the control says so and stops accepting: cancelling is a
  // request the server has to unwind, and a second press does not make it
  // faster. "Cancelling…" is the honest label for a state nobody can hurry.
  composer({
    turn: { ...TurnState.sending(Date.now()), cancelRequested: true } as TurnState,
  })
  expect(screen.getByRole('button', { name: 'Cancelling…' })).toBeDisabled()
})

it('says a turn started elsewhere is not this tab’s to send into', () => {
  composer({
    turn: TurnState.watching({
      turnIndex: 3,
      startedAt: null,
      elapsedSeconds: null,
    } as never),
  })

  // The label differs from `Running…` on purpose: this tab did not start it
  // and does not own its outcome, and "Turn running" says that without
  // claiming it is ours.
  expect(screen.getByRole('button', { name: 'Turn running' })).toBeDisabled()
  expect(screen.getByText(/running.*elsewhere|elsewhere/i)).toBeInTheDocument()
})

it('warns that a turn appends to HEAD while the reader is in history', () => {
  composer({ scrub: ScrubPoint.at(EventIndex(2)) })

  // The most important sentence this component renders. A reader scrubbed back
  // to event 2 and typing has every reason to expect the turn to happen
  // *there*; it does not, and there is no way to make it, so the composer says
  // what will happen and names the thing that does branch.
  expect(
    screen.getByText('viewing history — a turn appends to HEAD; fork to branch from here'),
  ).toBeInTheDocument()
})

it('jumps to where a turn began when its range is clicked', async () => {
  const user = userEvent.setup()
  const onJumpTo = vi.fn()
  const note: TurnNote = {
    tone: 'good',
    text: 'turn finished',
    range: { turnIndex: 3, from: EventIndex(14), to: EventIndex(21) },
    recheck: false,
  }
  composer({ note, onJumpTo })

  await user.click(screen.getByRole('button', { name: 'turn 3 · events 14–21' }))

  // `from`, not `to`: the reader wants to watch what the turn did, which means
  // starting where it started.
  expect(onJumpTo).toHaveBeenCalledWith(EventIndex(14))
})

it('offers a re-check only when the note is a guess', async () => {
  const user = userEvent.setup()
  const onRecheck = vi.fn()
  const observed: TurnNote = { tone: 'good', text: 'turn finished', range: null, recheck: false }

  const { unmount } = composer({ note: observed })
  expect(screen.queryByRole('button', { name: 're-check' })).not.toBeInTheDocument()
  unmount()

  composer({ note: { ...observed, recheck: true }, onRecheck })
  await user.click(screen.getByRole('button', { name: 're-check' }))
  expect(onRecheck).toHaveBeenCalledTimes(1)
})

it('tells the session that the last turn’s outcome is stale once typing starts', async () => {
  const user = userEvent.setup()
  const onTyping = vi.fn()
  composer({ note: { tone: 'good', text: 'turn finished', range: null, recheck: false }, onTyping })

  await user.type(box(), 'n')

  // Once you start writing the next turn, the last one's outcome is history.
  // The composer does not clear the note itself -- it reports, and the session
  // decides -- which is the state/presentation split §9 asks for everywhere.
  expect(onTyping).toHaveBeenCalled()
})

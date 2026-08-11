import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { Message, MessageRole } from '@domain/conversation/message.ts'
import type { SessionProjection } from '@domain/session/session.ts'

import { Conversation } from './Conversation.tsx'

/** What the transcript pane says when there is nothing to say, and where it
 *  scrolls to when there is.
 *
 * Fifth of phase 4's six prerequisites (§10).
 *
 * Two of its rules are worth a test and one is not. The stick-to-bottom
 * behaviour -- follow the live conversation unless the reader has scrolled up
 * to read something -- is the component's headline behaviour and is asserted
 * below by giving jsdom the geometry it does not compute. The scroll
 * *position* after a repaint is not asserted, because jsdom does not lay
 * anything out and a number it invents is not evidence; the browser half is
 * phase 6's.
 *
 * The rule that turns out to matter most is the dullest one: `emptyDetail`.
 * The default tells a reader to "send the first turn below", which is true on
 * the session route and false in `WorkerDrawer`, where this component is
 * reused read-only with no composer anywhere on screen. A default that
 * instructs a reader to do something their view cannot do is the exact defect
 * the four reports kept finding, and it is one prop away at all times.
 *
 * **Proved red** against three breaks: `emptyDetail` ignored in favour of the
 * hard-coded default; the `historicalAt` branch dropped; and `error` moved
 * below the empty check so a failed read renders as an empty conversation.
 */

const projection = (over: Partial<SessionProjection> = {}): SessionProjection =>
  ({
    messages: [],
    compactedThrough: null,
    compactionSummary: '',
    ...over,
  }) as unknown as SessionProjection

const message = (role: MessageRole, content: string): Message => ({
  role,
  content,
  toolCalls: [],
  isError: false,
})

it('never claims an empty conversation when the read failed', () => {
  render(<Conversation view={null} error="the server said 500" historicalAt={null} />)

  // R-F6.9's rule, applied here: empty and unavailable are different facts,
  // and showing "No conversation yet" for a failed read tells the reader
  // something false about the session. Fails if the error check is moved below
  // the empty check, which is one line and reads as harmless.
  expect(screen.getByText('the server said 500')).toBeInTheDocument()
  expect(screen.queryByText('No conversation yet.')).not.toBeInTheDocument()
})

it('does not tell a reader to send a turn when their view has no composer', () => {
  // `WorkerDrawer` renders this read-only. The default wording assumes a
  // composer below the pane; there is none there, so the caller overrides it.
  render(
    <Conversation
      view={projection()}
      error={null}
      historicalAt={null}
      emptyDetail="This worker has not said anything yet."
    />,
  )

  expect(screen.getByText('This worker has not said anything yet.')).toBeInTheDocument()
  expect(screen.queryByText('Send the first turn below.')).not.toBeInTheDocument()
})

it('says nothing had been said *yet* when the reader is in the past', () => {
  render(<Conversation view={projection()} error={null} historicalAt={9} />)

  // Not the same claim as "no conversation yet". A session with fifty turns
  // scrubbed back to event 9 has plenty of conversation -- none of it had
  // happened at that point, and the sentence has to say which of the two the
  // reader is looking at. Overrides `emptyDetail` too, since a prompt to send
  // a turn is wrong in history whatever the caller passed.
  expect(screen.getByText('Nothing had been said by event 9.')).toBeInTheDocument()
})

it('renders the transcript when there is one', () => {
  render(
    <Conversation
      view={projection({ messages: [message('assistant', 'the config changed on line 4')] })}
      error={null}
      historicalAt={null}
    />,
  )

  expect(screen.getByText('the config changed on line 4')).toBeInTheDocument()
  expect(screen.queryByText('No conversation yet.')).not.toBeInTheDocument()
})

it('follows a growing conversation while the reader is at the bottom', () => {
  const { container, rerender } = render(
    <Conversation
      view={projection({ messages: [message('user', 'first')] })}
      error={null}
      historicalAt={null}
    />,
  )

  const scroller = container.querySelector<HTMLElement>('.conv-scroll')!

  // jsdom lays nothing out, so every one of these is 0 and the component
  // cannot tell "at the bottom" from "scrolled away". Defining them is what
  // makes the question answerable at all -- and defining them explicitly is
  // also the honest version, because it puts the geometry this test depends on
  // in the test rather than in an assumption about the environment.
  Object.defineProperty(scroller, 'scrollHeight', { value: 1000, configurable: true })
  Object.defineProperty(scroller, 'clientHeight', { value: 300, configurable: true })
  scroller.scrollTop = 700 // exactly at the bottom
  scroller.dispatchEvent(new Event('scroll'))

  rerender(
    <Conversation
      view={projection({ messages: [message('user', 'first'), message('assistant', 'second')] })}
      error={null}
      historicalAt={null}
    />,
  )

  expect(scroller.scrollTop).toBe(1000)
})

it('leaves a reader who has scrolled up where they were', () => {
  const { container, rerender } = render(
    <Conversation
      view={projection({ messages: [message('user', 'first')] })}
      error={null}
      historicalAt={null}
    />,
  )

  const scroller = container.querySelector<HTMLElement>('.conv-scroll')!
  Object.defineProperty(scroller, 'scrollHeight', { value: 1000, configurable: true })
  Object.defineProperty(scroller, 'clientHeight', { value: 300, configurable: true })
  scroller.scrollTop = 200 // 500px from the bottom, well past the 80px latch
  scroller.dispatchEvent(new Event('scroll'))

  rerender(
    <Conversation
      view={projection({ messages: [message('user', 'first'), message('assistant', 'second')] })}
      error={null}
      historicalAt={null}
    />,
  )

  // The whole point of the latch. A reader who scrolled up is *reading*, and
  // yanking them to the bottom every time a frame lands is the fastest way to
  // make a live view unusable -- worse than not following at all, because it
  // punishes them for looking.
  expect(scroller.scrollTop).toBe(200)
})

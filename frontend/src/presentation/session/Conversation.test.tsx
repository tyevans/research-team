import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { ActivityEntry } from '@domain/activity/activity.ts'
import type { Message, MessageRole } from '@domain/conversation/message.ts'
import { MessageId, SessionId } from '@domain/shared/identifier.ts'
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

const live = (id: string, over: Partial<ActivityEntry> = {}): ActivityEntry => ({
  messageId: MessageId(id),
  sessionId: SessionId('7d41e0aa-1111-4111-8111-444444444444'),
  kind: 'assistant',
  text: null,
  payload: {},
  ...over,
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

/* --- the turn in flight ---------------------------------------------------
 *
 * These four are the change of 2026-08-28: the live tail used to be a sibling
 * component with its own scroller, so none of this was this component's
 * problem and none of it was asserted anywhere.
 *
 * **Proved red** by reverting each half: with the empty-state condition back
 * to `messages.length === 0`, the first fails; with `<LiveTail>` removed, the
 * first two fail; with `ProvisionalBubble` rendering every body literally the
 * way the old markup did, the markdown one fails. */

it('does not claim an empty conversation while a turn is streaming into it', () => {
  render(
    <Conversation
      view={projection()}
      error={null}
      historicalAt={null}
      activity={[live('m1', { text: 'reading the config' })]}
    />,
  )

  // The defect this is named for, seen in a `WorkerDrawer` on a worker that
  // had not committed anything yet: "No conversation yet." across the pane,
  // with prose visibly arriving underneath it. Two surfaces disagreeing about
  // whether anything is happening.
  expect(screen.queryByText('No conversation yet.')).not.toBeInTheDocument()
  expect(screen.getByText('reading the config')).toBeInTheDocument()
})

it('puts the turn in flight inside the transcript, not beside it', () => {
  const { container } = render(
    <Conversation
      view={projection({ messages: [message('assistant', 'done reading')] })}
      error={null}
      historicalAt={null}
      activity={[live('m1', { text: 'now writing' })]}
    />,
  )

  // One list and one scroller. As siblings the two were separate scrolling
  // regions, which is why the stick-to-bottom ref on `.conv-scroll` governed
  // the half that was not moving. Fails if the tail is rendered outside
  // `.conv` again -- including "outside but still inside `.conv-scroll`",
  // which looks right and puts it beyond the column's gap and padding.
  const tail = container.querySelector('.conv > .provisional')
  expect(tail).toBeInTheDocument()
  expect(tail).toHaveTextContent('now writing')
})

it('renders streaming prose as markdown, the way the message it becomes will', () => {
  const { container } = render(
    <Conversation
      view={projection()}
      error={null}
      historicalAt={null}
      activity={[live('m1', { text: '## Findings\n\nThe **cap** is 160.' })]}
    />,
  )

  // Until this change the live tail was the only model-authored prose in the
  // console rendered as plain text: a reader watched raw `##` and `**` stream
  // in, and then the same words silently reflowed into a formatted message the
  // moment the turn committed.
  expect(container.querySelector('.provisional h2')).toHaveTextContent('Findings')
  expect(container.querySelector('.provisional strong')).toHaveTextContent('cap')
})

it('leaves a tool-call summary literal', () => {
  const { container } = render(
    <Conversation
      view={projection()}
      error={null}
      historicalAt={null}
      activity={[
        live('m1', {
          kind: 'tool',
          payload: { data: { tool_calls: [{ name: 'read_file', args: { path: 'a_b_c.md' } }] } },
        }),
      ]}
    />,
  )

  // The other half of the same rule. `→ read_file(path=a_b_c.md)` is a label
  // this code assembled, not a document: through a markdown parser the pair of
  // underscores turns the middle of a filename italic and the characters
  // vanish from a string whose whole job is being exact.
  const body = container.querySelector('.provisional-body')!
  expect(body).toHaveTextContent('read_file')
  expect(body.querySelector('em')).toBeNull()
  expect(body).toHaveClass('mono')
})

it('follows the stream, and not only the commits', () => {
  // One projection object across both renders, deliberately. `messages` is
  // memoised on `view.messages`, and a fresh `projection()` per render hands
  // it a new array identity every time -- which fires the scroll effect
  // whatever its dependency list says. With that, the test passes with
  // `activity` dropped from the deps and proves nothing; it was written that
  // way first and checked.
  const stable = projection()

  const { container, rerender } = render(
    <Conversation view={stable} error={null} historicalAt={null} activity={[]} />,
  )

  const scroller = container.querySelector<HTMLElement>('.conv-scroll')!
  Object.defineProperty(scroller, 'scrollHeight', { value: 1000, configurable: true })
  Object.defineProperty(scroller, 'clientHeight', { value: 300, configurable: true })
  scroller.scrollTop = 700
  scroller.dispatchEvent(new Event('scroll'))

  rerender(
    <Conversation
      view={stable}
      error={null}
      historicalAt={null}
      activity={[live('m1', { text: 'a long answer arriving' })]}
    />,
  )

  // A turn saves atomically, so between "sent" and "committed" the *only*
  // thing that grows is the tail. While it lived in its own scroller this
  // effect could not see it, which made stick-to-bottom useless for exactly
  // the case it was written for. Fails if `activity` is dropped from the
  // effect's dependency list.
  expect(scroller.scrollTop).toBe(1000)
})

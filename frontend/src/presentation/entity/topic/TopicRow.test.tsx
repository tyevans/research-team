import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { TopicView } from '@domain/research/topic.ts'
import { TopicId } from '@domain/shared/identifier.ts'

import { TopicRow } from './TopicRow.tsx'

/** The `Row` density's contract, and the slot discipline.
 *
 * The height guarantee — that a row's height is a function of its kind and not
 * its content — is the property that matters most here and is **not testable
 * in jsdom**, which lays nothing out. What is testable is the structural half
 * of it: that a long question produces no more elements than a short one, and
 * that the row renders no disclosure. The clamp itself is CSS and needs a
 * browser; the story is where it is checked.
 */

const aTopic = (over: Partial<TopicView> = {}): TopicView => ({
  topicId: TopicId('22222222-2222-2222-2222-222222222222'),
  question: 'Who funded the study?',
  status: 'open',
  sources: 3,
  findings: 1,
  openSubQuestions: 0,
  triggers: [],
  needsAttention: false,
  isBlocked: false,
  ...over,
})

it('spells the status without underscores, through one component', () => {
  render(<TopicRow topic={aTopic({ status: 'not_pursuing' })} />)

  // The fourth `.replace('_', ' ')` this row does not contain.
  expect(screen.getByText('not pursuing')).toBeInTheDocument()
})

it('names its counts rather than showing bare numbers', () => {
  render(<TopicRow topic={aTopic({ sources: 3, findings: 1 })} />)
  expect(screen.getByText('3 sources')).toBeInTheDocument()
  expect(screen.getByText('1 findings')).toBeInTheDocument()
})

it('hides the open-questions count when there are none', () => {
  // "0 open" is a count of nothing occupying space in a 320px rail. The row
  // shows it only when it is a fact worth acting on.
  const { rerender } = render(<TopicRow topic={aTopic({ openSubQuestions: 0 })} />)
  // `'0 open'` exactly, not `/open$/`: the first draft used the regex and it
  // matched the *status* chip, which reads `open` for a topic nobody has
  // started. The test failed for a reason that had nothing to do with the
  // count, and would equally have passed for one.
  expect(screen.queryByText('0 open')).toBeNull()

  rerender(<TopicRow topic={aTopic({ openSubQuestions: 2 })} />)
  expect(screen.getByText('2 open')).toBeInTheDocument()
})

it('navigates with a link, never a handler', () => {
  render(<TopicRow topic={aTopic()} href="/topic/22222222" />)
  expect(screen.getByRole('link', { name: 'Who funded the study?' })).toHaveAttribute(
    'href',
    '/topic/22222222',
  )
})

it('renders the question as text when there is nowhere to go', () => {
  render(<TopicRow topic={aTopic()} />)
  expect(screen.queryByRole('link')).toBeNull()
  expect(screen.getByText('Who funded the study?')).toBeInTheDocument()
})

it('renders only the affordances it was given', () => {
  const { rerender } = render(<TopicRow topic={aTopic()} />)

  // A row knows nothing about dispatch. The view passes the verb because the
  // view owns the reason it is disabled.
  expect(screen.queryByRole('button')).toBeNull()

  rerender(
    <TopicRow topic={aTopic()} slots={{ primary: <button type="button">Synthesise</button> }} />,
  )
  expect(screen.getByRole('button', { name: 'Synthesise' })).toBeInTheDocument()
})

it('marks blocked ahead of flagged, and flagged ahead of closed', () => {
  // The precedence the domain's own `byUrgency` sorts in. A topic that is both
  // blocked and closed is blocked: it is waiting on a person either way, and
  // dimming it as closed is how it stops being noticed.
  const { container, rerender } = render(
    <TopicRow topic={aTopic({ isBlocked: true, needsAttention: true, status: 'superseded' })} />,
  )
  const row = () => container.querySelector('.ent-topic-row')
  expect(row()).toHaveClass('is-blocked')
  expect(row()).not.toHaveClass('needs-attention')
  expect(row()).not.toHaveClass('is-closed')

  rerender(<TopicRow topic={aTopic({ needsAttention: true, status: 'superseded' })} />)
  expect(row()).toHaveClass('needs-attention')
  expect(row()).not.toHaveClass('is-closed')

  rerender(<TopicRow topic={aTopic({ status: 'superseded' })} />)
  expect(row()).toHaveClass('is-closed')
})

it('renders the same elements for a long question as for a short one', () => {
  // The structural half of the height guarantee. The visual half — that the
  // question clamps to one line instead of wrapping — is CSS and needs a
  // browser; this is what a test can hold, and it is what would fail if
  // somebody added a "show more" disclosure to a row.
  const short = render(<TopicRow topic={aTopic({ question: 'Why?' })} />)
  const shortCount = short.container.querySelectorAll('*').length
  short.unmount()

  const long = render(<TopicRow topic={aTopic({ question: 'Why '.repeat(200) })} />)
  expect(long.container.querySelectorAll('*').length).toBe(shortCount)
})

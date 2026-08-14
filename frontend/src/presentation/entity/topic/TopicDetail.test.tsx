import { render, screen } from '@testing-library/react'
import { expect, it } from 'vitest'

import type { TopicDetail as TopicDetailView } from '@domain/research/topic.ts'
import { TopicId } from '@domain/shared/identifier.ts'

import { TopicDetail } from './TopicDetail.tsx'

/** The `Detail` density exists to render what no list shows, so that is what
 *  this file asserts.
 *
 * R-F3.10 counts five fields fetched by what is now `TopicManagePane` and
 * rendered nowhere in `presentation/`: `rationale`, `scope`, `sourceIds`,
 * `findingNotes` and `contested`. `TopicList.tsx` fetches the detail fresh
 * *because* the manage panel needs the rationale and the scope, and the panel
 * renders neither. Each of the five has an assertion here, and those five are
 * the reason the component exists.
 */

const aDetail = (over: Partial<TopicDetailView> = {}): TopicDetailView => ({
  topicId: TopicId('22222222-2222-2222-2222-222222222222'),
  question: 'Who funded the study?',
  status: 'investigating',
  sources: 2,
  findings: 1,
  openSubQuestions: 1,
  triggers: [],
  needsAttention: false,
  isBlocked: false,
  rationale: 'The funding decides how much the conclusion is worth.',
  scope: 'A named funder with a citation.',
  subQuestions: [{ key: 'a', question: 'Which grant?', answer: null, resolved: false }],
  sourceIds: ['doc-7', 'doc-9'],
  findingNotes: ['Two of the three authors declare the same grant.'],
  contested: false,
  ...over,
})

it('renders the rationale the manage pane fetches and never shows', () => {
  render(<TopicDetail topic={aDetail()} />)
  expect(screen.getByText('The funding decides how much the conclusion is worth.')).toBeVisible()
})

it('renders the scope the manage pane fetches and never shows', () => {
  render(<TopicDetail topic={aDetail()} />)
  expect(screen.getByText('A named funder with a citation.')).toBeVisible()
})

it('renders the finding notes as well as the count', () => {
  render(<TopicDetail topic={aDetail()} />)

  // Two wire fields, not one: `findings` is an int and `finding_notes` a list
  // of strings, and `presenters.py` warns in a comment that the two collide by
  // name. A contract mapping both onto `findings` would be a bug that
  // typechecks.
  expect(screen.getByText('1 finding from 2 sources')).toBeInTheDocument()
  expect(screen.getByText('Two of the three authors declare the same grant.')).toBeVisible()
})

it('says what to do next when there are no findings', () => {
  render(<TopicDetail topic={aDetail({ findings: 0, findingNotes: [] })} />)

  // "Empty states that do not say what to do next" is a named defect in two of
  // the four reports. The count line alone would be one.
  expect(screen.getByText(/Investigating this topic is what writes findings/)).toBeVisible()
})

it('renders the source ids', () => {
  render(<TopicDetail topic={aDetail()} />)
  expect(screen.getByText('doc-7')).toBeVisible()
  expect(screen.getByText('doc-9')).toBeVisible()
})

it('says when a topic is contested and stays quiet when it is not', () => {
  const { rerender } = render(<TopicDetail topic={aDetail({ contested: true })} />)
  expect(screen.getByText('contested')).toBeInTheDocument()

  rerender(<TopicDetail topic={aDetail({ contested: false })} />)
  expect(screen.queryByText('contested')).toBeNull()
})

it('says when a topic is blocked, which it used not to say at all', () => {
  // `isBlocked` was in the props type and read by nothing here, so a blocked
  // topic and an open one rendered identically. `TopicRow` says it with a red
  // left border and a detail has no rows to border, so the word is the only
  // form left — and the better one, since a detail is read rather than
  // scanned. Fails with the change reverted: the chip does not exist.
  const { rerender } = render(<TopicDetail topic={aDetail({ isBlocked: true })} />)
  expect(screen.getByText('blocked')).toBeInTheDocument()

  rerender(<TopicDetail topic={aDetail({ isBlocked: false })} />)
  expect(screen.queryByText('blocked')).toBeNull()
})

it('tones both flags apart from an ordinary status', () => {
  // The other half of the same finding. Both flags were missing from the tone
  // map, so both took the `neutral` default and drew exactly like `open` — the
  // story named two states and showed neither. This fails on the tone map
  // alone, with the chips rendering perfectly well.
  const { container } = render(
    <TopicDetail topic={aDetail({ isBlocked: true, contested: true })} />,
  )
  expect(screen.getByText('blocked').closest('.ent-status')).toHaveClass('ent-status-bad')
  expect(screen.getByText('contested').closest('.ent-status')).toHaveClass('ent-status-bad')
  // And the status itself is untouched by either: the fixture is
  // `investigating`, which is `live` with or without a flag beside it.
  expect(container.querySelector('.ent-status')).toHaveClass('ent-status-live')
})

it('omits a heading rather than heading an empty section', () => {
  // A topic opened in a hurry has no rationale. "Why this is being asked"
  // followed by nothing is worse than silence — it reads as a field that
  // failed to load.
  render(<TopicDetail topic={aDetail({ rationale: '   ', scope: '' })} />)

  expect(screen.queryByRole('heading', { name: 'Why this is being asked' })).toBeNull()
  expect(screen.queryByRole('heading', { name: 'What counts as an answer' })).toBeNull()
})

it('leads with a heading, not a borrowed drawer title', () => {
  render(<TopicDetail topic={aDetail()} />)

  // The manage panel once rendered this field as `<h3 className="drawer-title">`
  // — the `Drawer` component's own class, in a file that did not use `Drawer` —
  // while the queue rendered it as `<div className="topic-question">`: two
  // markups for one entity, sharing no class name at all. Both have since
  // moved on, so what this holds is the heading *level* and the role, which is
  // what the test name has always been about and is what a borrowed title
  // class cost.
  expect(screen.getByRole('heading', { name: 'Who funded the study?', level: 2 })).toBeVisible()
})

it('takes sub-questions from the view rather than resolving them itself', () => {
  render(<TopicDetail topic={aDetail()} slots={{ subQuestions: <p>a list the view owns</p> }} />)

  // `SubQuestionRow` is the one row component in the codebase that is not
  // props-pure — `useContainer()` and `useMutation` sit inside the row. A
  // detail that rendered them itself would inherit that coupling.
  expect(screen.getByText('a list the view owns')).toBeVisible()
})

import { describe, expect, it } from 'vitest'

import { TopicId } from '@domain/shared/identifier.ts'

import { byUrgency, CLOSED_STATUSES, isClosed, type TopicStatus, type TopicView } from './topic.ts'

const topic = (over: Partial<TopicView> = {}): TopicView => ({
  topicId: TopicId('11111111-1111-1111-1111-111111111111'),
  question: 'q',
  status: 'open',
  sources: 0,
  findings: 0,
  openSubQuestions: 0,
  triggers: [],
  needsAttention: false,
  isBlocked: false,
  ...over,
})

describe('isClosed', () => {
  it('treats not_pursuing and superseded as closed, everything else as live', () => {
    const statuses: readonly [TopicStatus, boolean][] = [
      ['open', false],
      ['investigating', false],
      ['answered', false],
      ['not_pursuing', true],
      ['superseded', true],
    ]

    for (const [status, expected] of statuses) {
      expect(isClosed(topic({ status }))).toBe(expected)
    }
  })

  it('lists exactly the closed statuses, in CLOSED_STATUSES', () => {
    expect(CLOSED_STATUSES).toEqual(['not_pursuing', 'superseded'])
  })
})

describe('byUrgency', () => {
  it('puts blocked topics above merely flagged ones', () => {
    const blocked = topic({ question: 'b', isBlocked: true, needsAttention: true })
    const flagged = topic({ question: 'a', isBlocked: false, needsAttention: true })

    expect([flagged, blocked].sort(byUrgency)).toEqual([blocked, flagged])
  })

  it('orders ties by question so a refetch does not reshuffle the list', () => {
    // Two rows with identical urgency have no natural order, and a sort that
    // leaves them in arrival order will swap them whenever the server's own
    // ordering shifts. The list is read top-down; it must hold still.
    const a = topic({ question: 'a' })
    const b = topic({ question: 'b' })

    expect([b, a].sort(byUrgency)).toEqual([a, b])
  })

  it('ranks needing-attention above a merely live topic', () => {
    const flagged = topic({ question: 'b', needsAttention: true })
    const live = topic({ question: 'a', status: 'investigating' })

    expect([live, flagged].sort(byUrgency)).toEqual([flagged, live])
  })

  it('ranks a live topic above a closed one', () => {
    const live = topic({ question: 'b', status: 'investigating' })
    const closed = topic({ question: 'a', status: 'superseded' })

    expect([closed, live].sort(byUrgency)).toEqual([live, closed])
  })

  it('holds the full order: blocked, needing attention, live, closed', () => {
    const blocked = topic({ question: 'blocked', isBlocked: true })
    const flagged = topic({ question: 'flagged', needsAttention: true })
    const live = topic({ question: 'live', status: 'open' })
    const closed = topic({ question: 'closed', status: 'not_pursuing' })

    expect([closed, live, flagged, blocked].sort(byUrgency)).toEqual([
      blocked,
      flagged,
      live,
      closed,
    ])
  })
})

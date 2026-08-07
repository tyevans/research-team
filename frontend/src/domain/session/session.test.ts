import { describe, expect, it } from 'vitest'

import { SessionId } from '../shared/identifier.ts'
import { ScrubPoint } from './scrub-point.ts'
import { EventIndex } from './event-index.ts'
import { compactedThrough, forkOrigin, totalEvents, type SessionProjection } from './session.ts'

const session = (over: Partial<SessionProjection> = {}): SessionProjection => ({
  id: SessionId('s1'),
  projectId: null,
  holdsProject: null,
  knowledgeAttached: null,
  modelName: null,
  systemPrompt: null,
  turnIndex: 0,
  failedTurns: 0,
  forkedFrom: null,
  forkedAt: null,
  eventCount: 0,
  compactedThrough: null,
  compactionSummary: null,
  at: null,
  files: [],
  messages: [],
  ...over,
})

describe('totalEvents', () => {
  it('takes whichever source has seen more', () => {
    // The declared count and the fetched log can disagree briefly mid-turn.
    // A log shorter than the count is one this tab has not caught up with; a
    // count shorter than the log cannot happen.
    expect(totalEvents(12, 9)).toBe(12)
    expect(totalEvents(9, 12)).toBe(12)
  })

  it('falls back to the log when nothing was declared', () => {
    expect(totalEvents(null, 7)).toBe(7)
    expect(totalEvents(undefined, 0)).toBe(0)
  })
})

describe('compactedThrough', () => {
  it('is zero when nothing has been compacted', () => {
    expect(compactedThrough(null, 10)).toBe(0)
    expect(compactedThrough(0, 10)).toBe(0)
  })

  it('reports the boundary', () => {
    expect(compactedThrough(4, 10)).toBe(4)
  })

  it('never lets a stale count eat the whole conversation', () => {
    // A fold scrubbed to before the compaction holds fewer messages than the
    // count that came with it.
    expect(compactedThrough(40, 3)).toBe(3)
  })

  it('ignores a nonsense value rather than rendering one', () => {
    expect(compactedThrough(Number.NaN, 10)).toBe(0)
    expect(compactedThrough(-2, 10)).toBe(0)
  })
})

describe('forkOrigin', () => {
  it('reports where a fork came from and where it diverged', () => {
    const origin = forkOrigin(session({ forkedFrom: SessionId('parent'), forkedAt: 7 }))
    expect(origin).toEqual({ from: 'parent', at: EventIndex(7) })
  })

  it('is null for a session that was not forked', () => {
    expect(forkOrigin(session())).toBeNull()
    expect(forkOrigin(null)).toBeNull()
  })

  it('reports the parent even when the divergence point is missing', () => {
    const origin = forkOrigin(session({ forkedFrom: SessionId('parent') }))
    expect(origin).toEqual({ from: 'parent', at: null })
  })
})

describe('ScrubPoint', () => {
  it('treats HEAD and a position as different states, not different numbers', () => {
    expect(ScrubPoint.isHistorical(ScrubPoint.head())).toBe(false)
    expect(ScrubPoint.isHistorical(ScrubPoint.at(EventIndex(3)))).toBe(true)
  })

  it('round-trips through the nullable form the route and wire use', () => {
    expect(ScrubPoint.toNullable(ScrubPoint.head())).toBeNull()
    expect(ScrubPoint.toNullable(ScrubPoint.fromNullable(5))).toBe(5)
  })

  it('reads an absent or impossible position as HEAD', () => {
    expect(ScrubPoint.fromNullable(null).kind).toBe('head')
    expect(ScrubPoint.fromNullable(0).kind).toBe('head')
    expect(ScrubPoint.fromNullable(Number.NaN).kind).toBe('head')
  })

  it('compares by value, so a re-render does not read as a move', () => {
    expect(ScrubPoint.equals(ScrubPoint.head(), ScrubPoint.head())).toBe(true)
    expect(ScrubPoint.equals(ScrubPoint.at(EventIndex(2)), ScrubPoint.at(EventIndex(2)))).toBe(true)
    expect(ScrubPoint.equals(ScrubPoint.at(EventIndex(2)), ScrubPoint.at(EventIndex(3)))).toBe(false)
    expect(ScrubPoint.equals(ScrubPoint.head(), ScrubPoint.at(EventIndex(1)))).toBe(false)
  })
})

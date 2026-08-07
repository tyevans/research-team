import { describe, expect, it } from 'vitest'

import { EventIndex } from './event-index.ts'
import { classifyEventType, humaniseEventType, isTurnEndType } from './event-kind.ts'
import {
  appendEntry,
  endsATurn,
  entryAt,
  isCancellation,
  kindOf,
  lastFailedTurnIndex,
  type LogEntry,
} from './log-entry.ts'

const entry = (index: number, over: Partial<LogEntry> = {}): LogEntry => ({
  index: EventIndex(index),
  type: 'UserMessageSent',
  occurredAt: '2026-01-01T00:00:00.000Z',
  summary: '',
  path: null,
  turnIndex: null,
  isError: null,
  cancelled: null,
  ...over,
})

describe('classifyEventType', () => {
  it('buckets the types the backend actually emits', () => {
    expect(classifyEventType('FileWritten')).toBe('file')
    expect(classifyEventType('ToolResultRecorded')).toBe('tool')
    expect(classifyEventType('SessionForkedFrom')).toBe('session')
    expect(classifyEventType('ConversationCompacted')).toBe('compaction')
    expect(classifyEventType('TurnCompleted')).toBe('turn')
    expect(classifyEventType('AssistantMessageAdded')).toBe('message')
  })

  it('gives an unrecognised type a bucket rather than losing it', () => {
    // The point of matching on substrings: a type added later still gets a
    // sane colour instead of vanishing.
    expect(classifyEventType('SomethingNewEntirely')).toBe('other')
    expect(classifyEventType('BudgetFileRotated')).toBe('file')
  })

  it('lets housekeeping win over the generic buckets', () => {
    // `ConversationCompacted` contains neither "file" nor "tool", but a future
    // `ToolOutputCompacted` would — and it is still housekeeping.
    expect(classifyEventType('ToolOutputCompacted')).toBe('compaction')
  })

  it('reads a failure as a failure even when it also names a session', () => {
    expect(classifyEventType('SessionFailed')).toBe('failure')
  })

  it('survives a missing type', () => {
    expect(classifyEventType(null)).toBe('other')
  })
})

describe('isTurnEndType', () => {
  it('recognises both ways a turn ends', () => {
    expect(isTurnEndType('TurnCompleted')).toBe(true)
    expect(isTurnEndType('TurnFailed')).toBe(true)
  })

  it('does not mistake a turn starting for one ending', () => {
    expect(isTurnEndType('TurnStarted')).toBe(false)
    expect(isTurnEndType('FileWritten')).toBe(false)
  })
})

describe('humaniseEventType', () => {
  it('reads PascalCase as prose', () => {
    expect(humaniseEventType('ToolResultRecorded')).toBe('tool result recorded')
    expect(humaniseEventType('SessionForkedFrom')).toBe('session forked from')
  })
})

describe('isCancellation', () => {
  it('separates a deliberate stop from a crash, though both are TurnFailed', () => {
    expect(isCancellation(entry(1, { type: 'TurnFailed', cancelled: true }))).toBe(true)
    expect(isCancellation(entry(1, { type: 'TurnFailed', cancelled: false }))).toBe(false)
    // Null on everything that is not a failed turn.
    expect(isCancellation(entry(1, { type: 'FileWritten' }))).toBe(false)
  })
})

describe('kindOf', () => {
  it('draws a cancellation as its own thing, never as a failure', () => {
    expect(kindOf(entry(1, { type: 'TurnFailed', cancelled: true }))).toBe('cancelled')
    expect(kindOf(entry(1, { type: 'TurnFailed' }))).toBe('failure')
  })
})

describe('endsATurn', () => {
  it('is true for either closing event', () => {
    expect(endsATurn(entry(1, { type: 'TurnCompleted' }))).toBe(true)
    expect(endsATurn(entry(1, { type: 'TurnFailed' }))).toBe(true)
    expect(endsATurn(entry(1))).toBe(false)
  })
})

describe('lastFailedTurnIndex', () => {
  it('finds the most recent failure, which is where discarded content belongs', () => {
    const log = [
      entry(1, { type: 'TurnFailed' }),
      entry(2, { type: 'FileWritten' }),
      entry(3, { type: 'TurnFailed' }),
      entry(4, { type: 'TurnCompleted' }),
    ]
    expect(lastFailedTurnIndex(log)).toBe(3)
  })

  it('is null when nothing has failed', () => {
    expect(lastFailedTurnIndex([entry(1), entry(2)])).toBeNull()
    expect(lastFailedTurnIndex([])).toBeNull()
  })
})

describe('entryAt', () => {
  it('finds by log position, not by array offset', () => {
    // A tab that connected mid-session holds a partial log, where the two
    // disagree.
    const partial = [entry(10), entry(11), entry(12)]
    expect(entryAt(partial, EventIndex(11))?.index).toBe(11)
  })

  it('falls back to the offset for a log whose indices are absent', () => {
    expect(entryAt([entry(1), entry(2)], EventIndex(2))?.index).toBe(2)
  })

  it('is null for a position the log does not hold', () => {
    expect(entryAt([entry(1)], EventIndex(99))).toBeNull()
  })
})

describe('appendEntry', () => {
  it('inserts in index order however the frame arrived', () => {
    let log: readonly LogEntry[] = []
    log = appendEntry(log, entry(3))
    log = appendEntry(log, entry(1))
    log = appendEntry(log, entry(2))
    expect(log.map((e) => e.index)).toEqual([1, 2, 3])
  })

  it('returns the same array for a frame it already holds', () => {
    // A reconnect replays; identity is what stops a hundred replayed frames
    // costing a hundred renders.
    const log = appendEntry([], entry(1))
    expect(appendEntry(log, entry(1))).toBe(log)
  })
})

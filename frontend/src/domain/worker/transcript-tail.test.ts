import { describe, expect, it } from 'vitest'

import { EventIndex } from '@domain/session/event-index.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import { SessionId } from '@domain/shared/identifier.ts'

import {
  MAX_TRACKED,
  remember,
  sample,
  SAMPLE_CHARS,
  type TranscriptTails,
} from './transcript-tail.ts'

const SESSION = SessionId('11111111-1111-1111-1111-111111111111')
const OTHER = SessionId('22222222-2222-2222-2222-222222222222')

const entry = (over: Partial<LogEntry> = {}): LogEntry => ({
  index: EventIndex(1),
  type: 'AssistantMessageAdded',
  occurredAt: '2026-08-09T12:00:00Z',
  summary: 'thinking about retention',
  path: null,
  turnIndex: 1,
  isError: null,
  cancelled: null,
  ...over,
})

const empty: TranscriptTails = new Map()

describe('remember', () => {
  it('keeps the latest assistant statement', () => {
    const tails = remember(empty, SESSION, entry({ summary: 'checking the corpus' }))
    expect(tails.get(SESSION)?.say).toBe('checking the corpus')
  })

  it('keeps the latest tool call beside the statement rather than replacing it', () => {
    // The row shows both, so a tool call must not erase the prose that
    // explains it -- which a single "last thing that happened" field would.
    const said = remember(
      empty,
      SESSION,
      entry({ index: EventIndex(1), summary: 'checking the corpus' }),
    )
    const tooled = remember(
      said,
      SESSION,
      entry({ index: EventIndex(2), type: 'ToolCalled', summary: 'grep' }),
    )

    expect(tooled.get(SESSION)).toMatchObject({ say: 'checking the corpus', tool: 'grep' })
  })

  it('ignores the operator’s own message', () => {
    // Both classify as `message`. Showing the operator their own prompt back
    // under a heading saying an agent is running is actively misleading.
    const tails = remember(empty, SESSION, entry({ type: 'UserMessageSent', summary: 'go' }))
    expect(tails.has(SESSION)).toBe(false)
  })

  it('ignores frames that are neither a statement nor a tool call', () => {
    const tails = remember(empty, SESSION, entry({ type: 'FileWritten', summary: 'notes.md' }))
    expect(tails).toBe(empty)
  })

  it('drops a replayed frame that is older than what is already shown', () => {
    // A reconnect resends the gap from the cursor. Without the index check the
    // row would visibly jump backwards to an older statement; this test fails
    // if `at` stops being compared.
    const latest = remember(empty, SESSION, entry({ index: EventIndex(9), summary: 'newest' }))
    const replayed = remember(latest, SESSION, entry({ index: EventIndex(4), summary: 'older' }))

    expect(replayed.get(SESSION)?.say).toBe('newest')
    expect(replayed).toBe(latest)
  })

  it('returns the same map when a frame changes nothing, so no render is spent', () => {
    const once = remember(empty, SESSION, entry({ index: EventIndex(3) }))
    expect(remember(once, SESSION, entry({ index: EventIndex(3) }))).toBe(once)
  })

  it('keeps sessions apart', () => {
    const one = remember(empty, SESSION, entry({ summary: 'mine' }))
    const two = remember(one, OTHER, entry({ summary: 'theirs' }))

    expect(two.get(SESSION)?.say).toBe('mine')
    expect(two.get(OTHER)?.say).toBe('theirs')
  })

  it('ignores a frame whose summary is blank', () => {
    expect(remember(empty, SESSION, entry({ summary: '   ' }))).toBe(empty)
  })
})

describe('the size cap', () => {
  it('keeps only the most recent sessions once it is full', () => {
    // What bounds the map. Filtering against the running roster instead was
    // the first implementation and raced with it -- see MAX_TRACKED.
    let tails: TranscriptTails = new Map()
    for (let i = 0; i < MAX_TRACKED + 5; i += 1) {
      tails = remember(tails, SessionId(`session-${i}`), entry({ index: EventIndex(1) }))
    }

    expect(tails.size).toBe(MAX_TRACKED)
    expect(tails.has(SessionId('session-0'))).toBe(false)
    expect(tails.has(SessionId(`session-${MAX_TRACKED + 4}`))).toBe(true)
  })

  it('evicts the session that has been silent longest, not the oldest to start', () => {
    // A long-running agent must not be dropped in favour of a chattier newer
    // one. Fails if `remember` stops re-inserting the key it touches.
    let tails: TranscriptTails = new Map()
    const veteran = SessionId('veteran')
    tails = remember(tails, veteran, entry({ index: EventIndex(1) }))
    for (let i = 0; i < MAX_TRACKED - 1; i += 1) {
      tails = remember(tails, SessionId(`session-${i}`), entry({ index: EventIndex(1) }))
    }

    // The veteran speaks again, then the map is pushed past its cap.
    tails = remember(tails, veteran, entry({ index: EventIndex(2), summary: 'still here' }))
    tails = remember(tails, SessionId('newcomer'), entry({ index: EventIndex(1) }))

    expect(tails.has(veteran)).toBe(true)
    expect(tails.has(SessionId('session-0'))).toBe(false)
  })
})

describe('sample', () => {
  it('flattens a multi-line summary onto one line', () => {
    // The row must not grow, and `nowrap` alone would still leave the newline
    // in the accessible name a screen reader reads out.
    expect(sample('first\n\nsecond')).toBe('first second')
  })

  it('truncates a long statement and marks that it was cut', () => {
    const long = 'a'.repeat(SAMPLE_CHARS + 40)
    const cut = sample(long)

    expect(cut).toHaveLength(SAMPLE_CHARS + 1)
    expect(cut?.endsWith('…')).toBe(true)
  })

  it('leaves a short statement exactly as it was', () => {
    expect(sample('grep')).toBe('grep')
  })

  it('answers null for nothing, so a row can ask once', () => {
    expect(sample(null)).toBeNull()
    expect(sample('   ')).toBeNull()
  })
})

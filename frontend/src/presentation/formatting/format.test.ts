import { describe, expect, it } from 'vitest'

import { bytes, clockTime, elapsed, elapsedSince, plural, relativeTime } from './format.ts'

const NOW = new Date('2026-08-07T12:00:00.000Z')
const ago = (ms: number) => new Date(NOW.getTime() - ms).toISOString()

const SECOND = 1_000
const MINUTE = 60 * SECOND
const HOUR = 60 * MINUTE
const DAY = 24 * HOUR

describe('relativeTime', () => {
  it('says "just now" inside the first three quarters of a minute', () => {
    expect(relativeTime(ago(10 * SECOND), NOW)).toBe('just now')
    expect(relativeTime(ago(44 * SECOND), NOW)).toBe('just now')
  })

  it('counts minutes up to an hour and a half', () => {
    expect(relativeTime(ago(51 * MINUTE), NOW)).toBe('51m ago')
    expect(relativeTime(ago(89 * MINUTE), NOW)).toBe('89m ago')
  })

  it('switches to hours, then days', () => {
    expect(relativeTime(ago(5 * HOUR), NOW)).toBe('5h ago')
    expect(relativeTime(ago(3 * DAY), NOW)).toBe('3d ago')
  })

  it('says so rather than guessing when there is no timestamp', () => {
    expect(relativeTime(null, NOW)).toBe('unknown')
    expect(relativeTime('not a date', NOW)).toBe('unknown')
  })
})

describe('clockTime', () => {
  it('pads to a fixed width so the column stays aligned', () => {
    expect(clockTime(new Date(2026, 0, 1, 4, 5, 6).toISOString())).toBe('04:05:06')
  })

  it('renders a placeholder of the same width for a missing time', () => {
    expect(clockTime(null)).toBe('--:--:--')
  })
})

describe('elapsed', () => {
  it('reports seconds below ninety and minutes above', () => {
    expect(elapsed(NOW.getTime() - 45 * SECOND, NOW.getTime())).toBe('45s')
    expect(elapsed(NOW.getTime() - 5 * MINUTE, NOW.getTime())).toBe('5m')
  })

  it('is empty when nothing has started', () => {
    expect(elapsed(null)).toBe('')
  })
})

describe('elapsedSince', () => {
  it('prefers the start time, which keeps counting up', () => {
    expect(elapsedSince(ago(30 * SECOND), 2, NOW.getTime())).toBe('30s')
  })

  it('falls back to the snapshot when there is no start time', () => {
    expect(elapsedSince(null, 42, NOW.getTime())).toBe('42s')
  })

  it('is null when neither is known, so a caller can say something else', () => {
    expect(elapsedSince(null, null, NOW.getTime())).toBeNull()
  })
})

describe('bytes', () => {
  it('scales through the units', () => {
    expect(bytes(512)).toBe('512 B')
    expect(bytes(2048)).toBe('2.0 KB')
    expect(bytes(5 * 1024 * 1024)).toBe('5.0 MB')
  })

  it('shows a dash rather than NaN for a missing size', () => {
    expect(bytes(null)).toBe('-')
    expect(bytes(Number.NaN)).toBe('-')
  })
})

describe('plural', () => {
  it('agrees with its count', () => {
    expect(plural(1, 'event')).toBe('1 event')
    expect(plural(2, 'event')).toBe('2 events')
    expect(plural(0, 'event')).toBe('0 events')
  })

  it('takes an irregular plural when given one', () => {
    expect(plural(2, 'entry', 'entries')).toBe('2 entries')
  })
})

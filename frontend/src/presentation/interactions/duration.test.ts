import { describe, expect, it } from 'vitest'

import { ABSENT, durationMs } from './duration.ts'

describe('durationMs', () => {
  it('reads a sub-minute duration to a tenth, which is the band the log lives in', () => {
    expect(durationMs(2310)).toBe('2.3s')
    expect(durationMs(400)).toBe('0.4s')
  })

  it('switches to minutes and seconds where the tenth stops helping', () => {
    expect(durationMs(72_000)).toBe('1m 12s')
    expect(durationMs(120_000)).toBe('2m')
  })

  it('reaches hours for the backgrounded tab this median exists to survive', () => {
    expect(durationMs(3_600_000)).toBe('1h')
    expect(durationMs(7_500_000)).toBe('2h 5m')
  })

  it('never spells one duration two ways at the minute boundary', () => {
    // Without the 59_950 threshold this is "60.0s", which sits beside "1m 0s"
    // in the same column and is the same length of time.
    expect(durationMs(59_980)).toBe('1m')
  })

  it('renders a real zero as a real zero', () => {
    // The whole reason `null` is handled separately below: a hidden slice of
    // nothing is a fact, and `0.0s` is what it says.
    expect(durationMs(0)).toBe('0.0s')
  })

  it('renders an absent median as an em-dash and never as zero', () => {
    expect(durationMs(null)).toBe(ABSENT)
    expect(durationMs(undefined)).toBe(ABSENT)
    expect(durationMs(Number.NaN)).toBe(ABSENT)
    expect(durationMs(null)).not.toBe('0.0s')
  })

  it('clamps a negative rather than rendering a puzzle', () => {
    expect(durationMs(-500)).toBe('0.0s')
  })
})

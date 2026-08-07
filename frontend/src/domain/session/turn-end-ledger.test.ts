import { describe, expect, it } from 'vitest'

import { TurnEndLedger } from './turn-end-ledger.ts'

const T0 = '2026-01-01T00:00:00.000Z'
const T1 = '2026-01-01T00:00:10.000Z'
const T2 = '2026-01-01T00:00:20.000Z'

describe('TurnEndLedger', () => {
  it('trusts a running answer when no turn has ever ended', () => {
    const ledger = TurnEndLedger.empty()
    expect(ledger.trustsRunning(ledger.sequence, T1)).toBe(true)
  })

  it('distrusts an answer that raced a turn ending', () => {
    const before = TurnEndLedger.empty()
    const after = before.recordEnding(T1, Date.now())
    // The request was sent before the ending; its answer arrived after.
    expect(after.trustsRunning(before.sequence, T2)).toBe(false)
  })

  it('distrusts an answer naming a turn that started before the last ending', () => {
    const ledger = TurnEndLedger.empty().recordEnding(T1, Date.now())
    // Sequence is unchanged across the request — this is the server-side lag
    // case, which only the timestamp comparison can catch.
    expect(ledger.trustsRunning(ledger.sequence, T0)).toBe(false)
  })

  it('trusts a turn that started after the last ending, however many times an index repeats', () => {
    const ledger = TurnEndLedger.empty().recordEnding(T1, Date.now())
    expect(ledger.trustsRunning(ledger.sequence, T2)).toBe(true)
  })

  it('trusts an answer with no start time rather than suppressing it', () => {
    const ledger = TurnEndLedger.empty().recordEnding(T1, Date.now())
    expect(ledger.trustsRunning(ledger.sequence, null)).toBe(true)
  })

  it('falls back to the local clock when a frame carries no timestamp', () => {
    const now = Date.parse(T2)
    const ledger = TurnEndLedger.empty().recordEnding(null, now)
    expect(ledger.lastEndedAt).toBe(now)
    expect(ledger.trustsRunning(ledger.sequence, T1)).toBe(false)
  })
})

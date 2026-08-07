import { describe, expect, it } from 'vitest'

import { EventIndex } from './event-index.ts'
import { TurnState, turnNote } from './turn.ts'

const watched = { turnIndex: 3, startedAt: null, elapsedSeconds: null, from: null }

/** Three states, and the distinction between the middle two is the one the
 *  previous implementation carried in two booleans read together everywhere.
 *  They disable the same controls and mean completely different things. */
describe('TurnState', () => {
  it('treats both busy states as busy', () => {
    expect(TurnState.isBusy(TurnState.idle())).toBe(false)
    expect(TurnState.isBusy(TurnState.sending(1))).toBe(true)
    expect(TurnState.isBusy(TurnState.watching(watched))).toBe(true)
  })

  it('knows which turns this tab owns the outcome of', () => {
    // Only a turn we posted gets a 499 to interpret.
    expect(TurnState.isOurs(TurnState.sending(1))).toBe(true)
    expect(TurnState.isOurs(TurnState.watching(watched))).toBe(false)
    expect(TurnState.isOurs(TurnState.idle())).toBe(false)
  })

  it('cannot have a cancel outstanding while idle', () => {
    expect(TurnState.isCancelRequested(TurnState.idle())).toBe(false)
    expect(TurnState.isCancelRequested(TurnState.withCancelRequested(TurnState.sending(1)))).toBe(
      true,
    )
  })

  it('ignores a cancel request against an idle composer', () => {
    expect(TurnState.withCancelRequested(TurnState.idle())).toEqual(TurnState.idle())
  })

  it('records where a watched turn began, once', () => {
    // The first frame after it started is its UserMessageSent — nothing else on
    // the wire says where a foreign turn opened.
    const first = TurnState.withWatchedOrigin(TurnState.watching(watched), EventIndex(7))
    expect(first.status === 'watching' && first.turn.from).toBe(7)

    const later = TurnState.withWatchedOrigin(first, EventIndex(9))
    expect(later.status === 'watching' && later.turn.from).toBe(7)
  })

  it('does not give a turn we sent a watched origin', () => {
    const sending = TurnState.sending(1)
    expect(TurnState.withWatchedOrigin(sending, EventIndex(7))).toBe(sending)
  })
})

describe('turnNote', () => {
  it('carries a tone that is not derived from the text', () => {
    // A cancelled turn arrives as a TurnFailed; reading the type would call it
    // a failure, and it is an outcome.
    expect(turnNote('calm', 'turn cancelled').tone).toBe('calm')
  })

  it('defaults to no range and no re-check', () => {
    expect(turnNote('good', 'done')).toEqual({
      tone: 'good',
      text: 'done',
      range: null,
      recheck: false,
    })
  })

  it('carries a range when the turn reported one', () => {
    const range = { turnIndex: 1, from: EventIndex(2), to: EventIndex(5) }
    expect(turnNote('good', 'turn complete', { range }).range).toBe(range)
  })
})

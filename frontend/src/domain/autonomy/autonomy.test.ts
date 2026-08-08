import { describe, expect, it } from 'vitest'

import { emptyPolicy, levelTally, type AutonomyPolicyView } from './autonomy.ts'

const policy = (levels: Record<string, string>, gated?: readonly string[]): AutonomyPolicyView => ({
  ...emptyPolicy,
  gated: gated ?? Object.keys(levels),
  levels: new Map(Object.entries(levels)),
})

describe('levelTally', () => {
  it('counts the gated tools at each level, commonest first', () => {
    expect(levelTally(policy({ a: 'ask', b: 'ask', c: 'auto' }))).toEqual([
      ['ask', 2],
      ['auto', 1],
    ])
  })

  it('breaks a tie by level name, so the summary does not reshuffle on a refetch', () => {
    expect(levelTally(policy({ a: 'deny', b: 'ask' }))).toEqual([
      ['ask', 1],
      ['deny', 1],
    ])
  })

  it('counts a level this build does not know rather than dropping it', () => {
    // The case `levelsToOffer` exists for: a tool sitting at a level this
    // build cannot name is exactly what a summary must not hide.
    expect(levelTally(policy({ a: 'sometimes' }))).toEqual([['sometimes', 1]])
  })

  it('leaves out a gated tool the server gave no level, rather than inventing one', () => {
    expect(levelTally(policy({ a: 'ask' }, ['a', 'b']))).toEqual([['ask', 1]])
  })

  it('tallies an empty policy as nothing at all', () => {
    expect(levelTally(emptyPolicy)).toEqual([])
  })
})

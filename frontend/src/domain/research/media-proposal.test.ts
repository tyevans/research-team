import { describe, expect, it } from 'vitest'

import { curationSummary } from './media-proposal.ts'

const outcome = (over: Partial<Parameters<typeof curationSummary>[0]> = {}) => ({
  needs: 2,
  candidates: 0,
  ignored: 0,
  rejectedParses: 0,
  searchedEmpty: 0,
  judgedOut: 0,
  ...over,
})

describe('curationSummary', () => {
  it('reports the candidates when there are any', () => {
    expect(curationSummary(outcome({ candidates: 3 }))).toBe(
      'Found 3 media candidates across 2 needs.',
    )
  })

  it('singularises one candidate and one need', () => {
    expect(curationSummary(outcome({ needs: 1, candidates: 1 }))).toBe(
      'Found 1 media candidate across 1 need.',
    )
  })

  it('says why a run found nothing, rather than only that it did', () => {
    // The whole point of the function. A bare "no candidates found" is what
    // this replaced, and it left four different failures looking identical --
    // see the domain comment. Fails if any count stops reaching the message.
    expect(curationSummary(outcome({ searchedEmpty: 2 }))).toBe(
      'No media candidates found (2 needs identified; 2 needs found nothing).',
    )
    expect(curationSummary(outcome({ rejectedParses: 1 }))).toBe(
      'No media candidates found (2 needs identified; 1 unreadable reply).',
    )
    expect(curationSummary(outcome({ ignored: 4 }))).toBe(
      'No media candidates found (2 needs identified; 4 ignored).',
    )
    // The case that reproduced the original report: gemma-4-26b-qat judged
    // ten real video results and kept none, leaving every other count clean.
    expect(curationSummary(outcome({ judgedOut: 2 }))).toBe(
      'No media candidates found (2 needs identified; 2 needs judged out).',
    )
  })

  it('lists several reasons in the chain order they occur in', () => {
    expect(
      curationSummary(outcome({ searchedEmpty: 1, ignored: 2, judgedOut: 1, rejectedParses: 3 })),
    ).toBe(
      'No media candidates found (2 needs identified; 1 need found nothing, 2 ignored, 1 need judged out, 3 unreadable replies).',
    )
  })

  it('stays quiet when a zero has no fault to report', () => {
    // A topic that genuinely wants no imagery reaches zero with every count
    // clean, and should not read like a list of things that went wrong.
    expect(curationSummary(outcome({ needs: 0 }))).toBe(
      'No media candidates found (0 needs identified).',
    )
  })
})

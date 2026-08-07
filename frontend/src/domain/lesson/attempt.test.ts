import { describe, expect, it } from 'vitest'

import {
  freshAttempt,
  mcqResponse,
  resetAttempt,
  withStoredProgress,
  type ItemProgress,
  type Verdict,
} from './attempt.ts'

const stored = (over: Partial<ItemProgress> = {}): ItemProgress => ({
  attempts: 0,
  correct: false,
  bestScore: 0,
  lastScore: 0,
  checked: [],
  ...over,
})

const verdict: Verdict = {
  correct: true,
  score: 1,
  feedback: ['Yes.'],
  rationale: null,
  correctOptions: [1],
  blanks: [],
  progress: null,
}

describe('withStoredProgress', () => {
  it('restores the ticks a learner made', () => {
    const restored = withStoredProgress(freshAttempt(), stored({ checked: [0, 2] }))
    expect(restored.ticked).toEqual({ 0: true, 2: true })
  })

  it('restores that they got it right before, and after how many tries', () => {
    const restored = withStoredProgress(freshAttempt(), stored({ attempts: 3, correct: true }))
    expect(restored.previouslyCorrect).toBe(true)
    expect(restored.attempts).toBe(3)
  })

  it('does not reconstruct a verdict', () => {
    // The record holds counts and scores, not the author's feedback text.
    // Inventing a panel out of a score would put words in their mouth.
    const restored = withStoredProgress(freshAttempt(), stored({ correct: true, bestScore: 1 }))
    expect(restored.verdict).toBeNull()
  })

  it('keeps ticks already made in this session', () => {
    const inProgress = { ...freshAttempt(), ticked: { 5: true } }
    expect(withStoredProgress(inProgress, stored({ checked: [1] })).ticked).toEqual({
      1: true,
      5: true,
    })
  })
})

describe('resetAttempt', () => {
  it('clears the answer and the verdict for another go', () => {
    const answered = { ...freshAttempt(), verdict, picked: [1], typed: { 0: 'x' }, error: 'nope' }
    const reset = resetAttempt(answered)
    expect(reset.verdict).toBeNull()
    expect(reset.picked).toEqual([])
    expect(reset.typed).toEqual({})
    expect(reset.error).toBeNull()
  })

  it('keeps what the durable record knows — that is about the learner, not this attempt', () => {
    const answered = { ...freshAttempt(), previouslyCorrect: true, attempts: 2, verdict }
    const reset = resetAttempt(answered)
    expect(reset.previouslyCorrect).toBe(true)
    expect(reset.attempts).toBe(2)
  })
})

describe('mcqResponse', () => {
  it('sends a sorted list for a multiple-answer question', () => {
    expect(mcqResponse([3, 1, 2], true)).toEqual([1, 2, 3])
  })

  it('sends a bare index for a single-answer one', () => {
    expect(mcqResponse([2], false)).toBe(2)
  })

  it('sends nothing selected as an empty list rather than as index zero', () => {
    // `0` is a real option; an unanswered question is not option zero.
    expect(mcqResponse([], false)).toEqual([])
  })
})

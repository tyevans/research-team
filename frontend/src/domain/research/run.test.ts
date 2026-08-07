import { describe, expect, it } from 'vitest'

import { ProjectId, RunId, SessionId } from '../shared/identifier.ts'
import { endingFor, isLive, parseRoundCap, type ResearchRun, type RunProgress } from './run.ts'

const run = (progress: Partial<RunProgress> | null): ResearchRun => ({
  runId: RunId('r1'),
  projectId: ProjectId('p1'),
  sessionId: SessionId('s1'),
  progress:
    progress === null
      ? null
      : {
          status: 'running',
          rounds: 0,
          turns: 0,
          findings: 0,
          stopReason: null,
          workingOn: null,
          quietRounds: 0,
          failures: 0,
          budget: { maxRounds: null, quietRounds: null },
          readOnly: false,
          ...progress,
        },
})

describe('isLive', () => {
  it('counts a run that has begun and not been folded as live', () => {
    // The 202 body: ids only. The alternative is one frame of "ended, reason
    // unknown" between starting a run and the first poll.
    expect(isLive(run(null))).toBe(true)
  })

  it('counts running and new as live', () => {
    expect(isLive(run({ status: 'running' }))).toBe(true)
    expect(isLive(run({ status: 'new' }))).toBe(true)
  })

  it('does not count a stopped run, or no run at all', () => {
    expect(isLive(run({ status: 'stopped' }))).toBe(false)
    expect(isLive(null)).toBe(false)
  })
})

describe('endingFor', () => {
  it('gives exactly one ending the "done" tone', () => {
    // Every other ending describes a run that stopped with topics still on the
    // queue, which is not success and must not be dressed as it.
    expect(endingFor('queue_empty').tone).toBe('done')

    for (const reason of ['max_rounds', 'budget_exhausted', 'no_new_findings', 'cancelled']) {
      expect(endingFor(reason).tone).not.toBe('done')
    }
  })

  it('marks a run that failed its way to a stop as bad, not merely short', () => {
    expect(endingFor('error_rate').tone).toBe('bad')
  })

  it('reads an unrecognised ending the un-finished way', () => {
    const unknown = endingFor('some_future_reason')
    expect(unknown.tone).toBe('short')
    expect(unknown.label).toBe('some_future_reason')
    expect(unknown.text).toContain('rather than one that finished')
  })

  it('never claims completion for a missing reason', () => {
    expect(endingFor(null).tone).not.toBe('done')
  })
})

describe('parseRoundCap', () => {
  it('reads an empty cap as a real choice: the domain’s own budget', () => {
    expect(parseRoundCap('')).toEqual({ kind: 'domainBudget' })
    expect(parseRoundCap('   ')).toEqual({ kind: 'domainBudget' })
  })

  it('reads a whole number as a cap', () => {
    expect(parseRoundCap('12')).toEqual({ kind: 'capped', rounds: 12 })
    expect(parseRoundCap(' 3 ')).toEqual({ kind: 'capped', rounds: 3 })
  })

  it('rejects a cap that would mean nothing', () => {
    expect(parseRoundCap('0').kind).toBe('invalid')
    expect(parseRoundCap('-4').kind).toBe('invalid')
    expect(parseRoundCap('lots').kind).toBe('invalid')
  })
})

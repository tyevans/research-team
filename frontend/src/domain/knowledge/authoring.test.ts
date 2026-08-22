import { describe, expect, it } from 'vitest'

import {
  courseLinks,
  isRunning,
  progressOf,
  type AuthoringRun,
  type AuthoringStatus,
} from './authoring.ts'

const run = (over: Partial<AuthoringRun> = {}): AuthoringRun => ({
  runId: 'r1',
  status: 'done',
  kind: 'path',
  targets: ['one', 'two'],
  completed: ['one', 'two'],
  sessions: ['s1', 's2'],
  current: null,
  failures: [],
  ...over,
})

const status = (over: Partial<AuthoringStatus> = {}): AuthoringStatus => ({
  current: null,
  last: null,
  ...over,
})

describe('courseLinks', () => {
  it('pairs each finished course with the session that wrote it', () => {
    expect(courseLinks(run())).toEqual([
      { target: 'one', sessionId: 's1' },
      { target: 'two', sessionId: 's2' },
    ])
  })

  it('drops a pair it cannot make rather than guessing at one', () => {
    // An older server, or a frame from before `sessions` existed. Pairing
    // `two` with `s1` would open something real, which is what makes a wrong
    // link worse than a missing one: nobody suspects it.
    expect(courseLinks(run({ sessions: ['s1'] }))).toEqual([{ target: 'one', sessionId: 's1' }])
  })

  it('has nothing to offer for a run that completed nothing', () => {
    expect(courseLinks(run({ completed: [], sessions: [] }))).toEqual([])
  })
})

describe('isRunning', () => {
  it('is false when nothing is current', () => {
    expect(isRunning(status())).toBe(false)
  })

  it('is false for a finished run still sitting in `current`', () => {
    expect(isRunning(status({ current: run({ status: 'done' }) }))).toBe(false)
  })

  it('is true only while a run says it is running', () => {
    expect(isRunning(status({ current: run({ status: 'running' }) }))).toBe(true)
  })
})

describe('progressOf', () => {
  it('is the fraction of targets completed', () => {
    expect(progressOf(run({ completed: ['one'] }))).toBe(0.5)
  })

  it('is null rather than zero when there is nothing to do', () => {
    // A bar at 0% asserts that work is pending, and a run with no targets has
    // none. The server refuses to start such a run, so this is unreachable --
    // it is here because dividing by zero renders `NaN%` rather than failing,
    // which is the kind of bug that survives to production.
    expect(progressOf(run({ targets: [], completed: [] }))).toBeNull()
  })
})

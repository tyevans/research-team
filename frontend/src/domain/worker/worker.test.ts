import { describe, expect, it } from 'vitest'

import { ProjectId, SessionId } from '@domain/shared/identifier.ts'

import { isBusy, nest, type Roster, type Worker } from './worker.ts'

const worker = (over: Partial<Worker> = {}): Worker => ({
  kind: 'turn',
  ref: 'ref',
  detail: 'turn 1',
  sessionId: null,
  parent: null,
  startedAt: null,
  ...over,
})

const roster = (over: Partial<Roster> = {}): Roster => ({
  projectId: ProjectId('11111111-1111-1111-1111-111111111111'),
  workers: [],
  idleSessionIds: [],
  ...over,
})

describe('nest', () => {
  it('hangs a child under the parent it names', () => {
    const run = worker({ kind: 'run', ref: 'run-1', detail: 'autonomous run' })
    const extraction = worker({ kind: 'extraction', ref: 'src-1', parent: 'run-1' })

    const tree = nest([run, extraction])

    expect(tree).toHaveLength(1)
    expect(tree[0]?.worker.ref).toBe('run-1')
    expect(tree[0]?.children.map((node) => node.worker.ref)).toEqual(['src-1'])
  })

  it('keeps a child whose parent is absent at the top level', () => {
    // The roster is polled, so a parent can vanish between the poll that
    // named it and this render. Dropping the child would hide live work.
    const orphan = worker({ kind: 'extraction', ref: 'src-1', parent: 'gone' })

    const tree = nest([orphan])

    expect(tree.map((node) => node.worker.ref)).toEqual(['src-1'])
  })

  it('preserves the order the server sent', () => {
    const tree = nest([worker({ ref: 'a' }), worker({ ref: 'b' }), worker({ ref: 'c' })])
    expect(tree.map((node) => node.worker.ref)).toEqual(['a', 'b', 'c'])
  })

  it('does not loop on a worker that parents itself', () => {
    // Not something the server should ever send. It must not hang a browser
    // if it does.
    const tree = nest([worker({ ref: 'a', parent: 'a' })])
    expect(tree.map((node) => node.worker.ref)).toEqual(['a'])
  })
})

describe('isBusy', () => {
  it('is false when nothing is working, whatever is attached', () => {
    expect(
      isBusy(roster({ idleSessionIds: [SessionId('22222222-2222-2222-2222-222222222222')] })),
    ).toBe(false)
  })

  it('is true as soon as there is one worker', () => {
    expect(isBusy(roster({ workers: [worker()] }))).toBe(true)
  })
})

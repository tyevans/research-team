import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@application/ports/errors.ts'
import type { FeedFrame } from '@application/ports/event-stream.ts'
import type {
  ApprovalRepository,
  RunningTurn,
  SessionRepository,
  TurnRepository,
} from '@application/ports/repositories.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import type { LogEntry } from '@domain/session/log-entry.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { SessionId, MessageId } from '@domain/shared/identifier.ts'

import { createSessionStore, type SessionStore } from './session-store.ts'

const SESSION = SessionId('11111111-2222-3333-4444-555555555555')

const projection = (over: Partial<SessionProjection> = {}): SessionProjection => ({
  id: SESSION,
  projectId: null,
  holdsProject: null,
  knowledgeAttached: null,
  modelName: 'test-model',
  systemPrompt: null,
  turnIndex: 0,
  failedTurns: 0,
  forkedFrom: null,
  forkedAt: null,
  eventCount: 0,
  compactedThrough: null,
  compactionSummary: null,
  at: null,
  files: [],
  messages: [],
  ...over,
})

const entry = (over: Omit<Partial<LogEntry>, 'index'> & { index: number }): LogEntry => ({
  type: 'UserMessageSent',
  occurredAt: '2026-01-01T00:00:00.000Z',
  summary: '',
  path: null,
  turnIndex: null,
  isError: null,
  cancelled: null,
  ...over,
  index: EventIndex(over.index),
})

const idle: RunningTurn = {
  running: false,
  turnIndex: null,
  startedAt: null,
  elapsedSeconds: null,
}

/** Defaults every test starts from. Overridden per case rather than configured,
 *  so each test states only the behaviour it is actually about. */
const defaultSessions = (): SessionRepository => ({
  list: vi.fn(async () => []),
  tree: vi.fn(async () => []),
  create: vi.fn(async () => SESSION),
  read: vi.fn(async () => projection()),
  log: vi.fn(async () => [] as readonly LogEntry[]),
  fork: vi.fn(async () => SessionId('forked')),
  release: vi.fn(async () => true),
})

const makeStore = (over: {
  sessions?: Partial<SessionRepository>
  turns?: Partial<TurnRepository>
  approvals?: Partial<ApprovalRepository>
  now?: () => number
} = {}): { store: SessionStore; notify: ReturnType<typeof vi.fn> } => {
  const notify = vi.fn()
  const store = createSessionStore({
    sessions: { ...defaultSessions(), ...over.sessions },
    turns: {
      send: vi.fn(async () => null),
      cancel: vi.fn(async () => ({ cancelled: true, settled: true })),
      current: vi.fn(async () => idle),
      activity: vi.fn(async () => ({ running: [], discarded: [] })),
      ...over.turns,
    },
    approvals: {
      pending: vi.fn(async () => []),
      decide: vi.fn(async () => undefined),
      ...over.approvals,
    },
    now: over.now ?? (() => 1_000),
    notify,
  })
  return { store, notify }
}

describe('session store — opening', () => {
  it('loads head, log, running state and approvals together', async () => {
    const { store } = makeStore({
      sessions: { log: async () => [entry({ index: 1 })] },
    })
    await store.getState().open(SESSION, ScrubPoint.head())

    expect(store.getState().sessionId).toBe(SESSION)
    expect(store.getState().log).toHaveLength(1)
    expect(store.getState().error).toBeNull()
  })

  it('starts the composer enabled even if the previous session had a turn in flight', async () => {
    const { store } = makeStore()
    await store.getState().open(SESSION, ScrubPoint.head())
    store.setState({ turn: { status: 'sending', startedAt: 1, cancelRequested: false } })

    await store.getState().open(SessionId('other'), ScrubPoint.head())
    expect(store.getState().turn.status).toBe('idle')
  })

  it('surfaces a load failure rather than rendering an empty session', async () => {
    const { store } = makeStore({
      sessions: {
        read: vi.fn(async () => {
          throw new ApiError('no session', 404)
        }),
      },
    })
    await store.getState().open(SESSION, ScrubPoint.head())
    expect(store.getState().error).toBe('no session')
  })
})

describe('session store — sending a turn', () => {
  let store: SessionStore

  beforeEach(async () => {
    store = makeStore().store
    await store.getState().open(SESSION, ScrubPoint.head())
  })

  it('ignores an empty input', async () => {
    await store.getState().send('   ')
    expect(store.getState().turn.status).toBe('idle')
  })

  it('marks the reported span fresh and notes the range', async () => {
    const range = { turnIndex: 1, from: EventIndex(2), to: EventIndex(5) }
    const { store: sending } = makeStore({ turns: { send: vi.fn(async () => range) } })
    await sending.getState().open(SESSION, ScrubPoint.head())
    await sending.getState().send('hello')

    expect(sending.getState().note).toMatchObject({ tone: 'good', text: 'turn complete', range })
    expect([...sending.getState().fresh.keys()]).toEqual([2, 3, 4, 5])
  })

  it('treats a 499 as an outcome, not a failure', async () => {
    const { store: cancelled, notify } = makeStore({
      turns: {
        send: vi.fn(async () => {
          throw new ApiError('cancelled', 499)
        }),
      },
    })
    await cancelled.getState().open(SESSION, ScrubPoint.head())
    await cancelled.getState().send('hello')

    expect(cancelled.getState().note?.tone).toBe('calm')
    expect(notify).not.toHaveBeenCalled()
  })

  it('offers a re-check when another tab holds the turn', async () => {
    const { store: conflicted } = makeStore({
      turns: {
        send: vi.fn(async () => {
          throw new ApiError('a turn is already running', 409)
        }),
      },
    })
    await conflicted.getState().open(SESSION, ScrubPoint.head())
    await conflicted.getState().send('hello')

    expect(conflicted.getState().note).toMatchObject({ tone: 'warn', recheck: true })
  })

  it('re-enables the composer even when the turn failed', async () => {
    const { store: failed } = makeStore({
      turns: {
        send: vi.fn(async () => {
          throw new ApiError('boom', 500)
        }),
      },
    })
    await failed.getState().open(SESSION, ScrubPoint.head())
    await failed.getState().send('hello')
    expect(failed.getState().turn.status).toBe('idle')
  })
})

describe('session store — a turn running elsewhere', () => {
  const running: RunningTurn = {
    running: true,
    turnIndex: 3,
    startedAt: '2026-01-01T00:00:00.000Z',
    elapsedSeconds: 2,
  }

  it('watches a foreign turn reported at mount', async () => {
    const { store } = makeStore({ turns: { current: vi.fn(async () => running) } })
    await store.getState().open(SESSION, ScrubPoint.head())
    expect(store.getState().turn.status).toBe('watching')
  })

  it('learns where a watched turn began from its first frame', async () => {
    const { store } = makeStore({ turns: { current: vi.fn(async () => running) } })
    await store.getState().open(SESSION, ScrubPoint.head())

    store.getState().handleFrame({
      kind: 'log',
      sessionId: SESSION,
      entry: entry({ index: 7 }),
    })

    const turn = store.getState().turn
    expect(turn.status === 'watching' && turn.turn.from).toBe(7)
  })

  it('ends the watch on a turn-end frame and says so', async () => {
    const { store } = makeStore({ turns: { current: vi.fn(async () => running) } })
    await store.getState().open(SESSION, ScrubPoint.head())

    store.getState().handleFrame({
      kind: 'log',
      sessionId: SESSION,
      entry: entry({ index: 9, type: 'TurnCompleted' }),
    })

    expect(store.getState().turn.status).toBe('idle')
    expect(store.getState().note?.text).toBe('the turn running elsewhere finished')
  })

  it('reads a cancelled TurnFailed as a cancellation, not a failure', async () => {
    const { store } = makeStore({ turns: { current: vi.fn(async () => running) } })
    await store.getState().open(SESSION, ScrubPoint.head())

    store.getState().handleFrame({
      kind: 'log',
      sessionId: SESSION,
      entry: entry({ index: 9, type: 'TurnFailed', cancelled: true }),
    })

    expect(store.getState().note?.tone).toBe('calm')
  })

  it('does not let a stale running answer resurrect a turn it already saw end', async () => {
    const current = vi.fn(async () => running)
    const { store } = makeStore({ turns: { current } })
    await store.getState().open(SESSION, ScrubPoint.head())

    // The turn ends on the stream…
    store.getState().handleFrame({
      kind: 'log',
      sessionId: SESSION,
      entry: entry({ index: 9, type: 'TurnCompleted', occurredAt: '2026-01-01T00:00:05.000Z' }),
    })
    // …and the server keeps saying "running" about that same turn.
    await store.getState().refreshRunning()

    expect(store.getState().turn.status).toBe('idle')
  })
})

describe('session store — log frames', () => {
  it('ignores frames for another session', async () => {
    const { store } = makeStore()
    await store.getState().open(SESSION, ScrubPoint.head())

    store.getState().handleFrame({
      kind: 'log',
      sessionId: SessionId('somebody-else'),
      entry: entry({ index: 4 }),
    })
    expect(store.getState().log).toHaveLength(0)
  })

  it('does not duplicate a frame a reconnect replays', async () => {
    const { store } = makeStore()
    await store.getState().open(SESSION, ScrubPoint.head())
    const frame: FeedFrame = { kind: 'log', sessionId: SESSION, entry: entry({ index: 4 }) }

    store.getState().handleFrame(frame)
    store.getState().handleFrame(frame)

    expect(store.getState().log).toHaveLength(1)
  })

  it('keeps a failed turn’s provisional content against its row', async () => {
    const { store } = makeStore()
    await store.getState().open(SESSION, ScrubPoint.head())
    store.setState({ turn: { status: 'sending', startedAt: 1, cancelRequested: false } })

    store.getState().handleFrame({
      kind: 'activity',
      entry: {
        messageId: MessageId('m1'),
        sessionId: SESSION,
        kind: 'delta',
        text: 'thinking…',
        payload: null,
      },
    })
    store.getState().handleFrame({
      kind: 'log',
      sessionId: SESSION,
      entry: entry({ index: 12, type: 'TurnFailed' }),
    })

    expect(store.getState().discarded.get(EventIndex(12))).toHaveLength(1)
    expect(store.getState().activity.size).toBe(0)
  })

  it('drops provisional content outright when the turn succeeded', async () => {
    const { store } = makeStore()
    await store.getState().open(SESSION, ScrubPoint.head())
    store.setState({ turn: { status: 'sending', startedAt: 1, cancelRequested: false } })

    store.getState().handleFrame({
      kind: 'activity',
      entry: {
        messageId: MessageId('m1'),
        sessionId: SESSION,
        kind: 'delta',
        text: 'thinking…',
        payload: null,
      },
    })
    store.getState().handleFrame({
      kind: 'log',
      sessionId: SESSION,
      entry: entry({ index: 12, type: 'TurnCompleted' }),
    })

    expect(store.getState().discarded.size).toBe(0)
    expect(store.getState().activity.size).toBe(0)
  })
})

describe('session store — approvals', () => {
  it('clears a card when it settles anywhere, not only here', async () => {
    const { store } = makeStore()
    await store.getState().open(SESSION, ScrubPoint.head())
    const approval = {
      id: 'a1' as never,
      sessionId: SESSION,
      toolName: 'fetch',
      description: null,
      args: {},
    }

    store.getState().handleFrame({ kind: 'approvalRequested', approval })
    expect(store.getState().approvals.size).toBe(1)

    store.getState().handleFrame({
      kind: 'approvalSettled',
      sessionId: SESSION,
      approvalId: approval.id,
    })
    expect(store.getState().approvals.size).toBe(0)
  })

  it('stays quiet when a decision races somebody else’s', async () => {
    const decide = vi.fn(async () => {
      throw new ApiError('gone', 404)
    })
    const { store, notify } = makeStore({ approvals: { decide } })
    await store.getState().open(SESSION, ScrubPoint.head())

    await store.getState().decide(
      { id: 'a1' as never, sessionId: SESSION, toolName: 'fetch', description: null, args: {} },
      'approve',
    )
    expect(notify).not.toHaveBeenCalled()
  })
})

describe('session store — scrubbing', () => {
  it('folds to a point and back to live', async () => {
    const read = vi.fn(async (_id: SessionId, at: ScrubPoint) =>
      projection({ at: ScrubPoint.toNullable(at) }),
    )
    const { store } = makeStore({ sessions: { read } })
    await store.getState().open(SESSION, ScrubPoint.head())

    await store.getState().scrubTo(ScrubPoint.at(EventIndex(3)))
    expect(store.getState().snapshot?.at).toBe(3)

    await store.getState().scrubTo(ScrubPoint.head())
    expect(store.getState().snapshot).toBeNull()
  })

  it('discards a fold the reader already scrubbed past', async () => {
    let release = (): void => {}
    const held = new Promise<void>((resolve) => {
      release = resolve
    })
    const read = vi.fn(async (_id: SessionId, at: ScrubPoint) => {
      if (ScrubPoint.toNullable(at) === 3) await held
      return projection({ at: ScrubPoint.toNullable(at) })
    })
    const { store } = makeStore({ sessions: { read } })
    await store.getState().open(SESSION, ScrubPoint.head())

    const slow = store.getState().scrubTo(ScrubPoint.at(EventIndex(3)))
    await store.getState().scrubTo(ScrubPoint.at(EventIndex(9)))
    release()
    await slow

    expect(store.getState().snapshot?.at).toBe(9)
  })
})

describe('session store — fresh marks', () => {
  it('expires a highlight once its window has passed', async () => {
    let clock = 1_000
    const { store } = makeStore({ now: () => clock })
    await store.getState().open(SESSION, ScrubPoint.head())

    store.getState().handleFrame({ kind: 'log', sessionId: SESSION, entry: entry({ index: 1 }) })
    expect(store.getState().fresh.size).toBe(1)

    clock += 5_000
    store.getState().sweepFresh()
    expect(store.getState().fresh.size).toBe(0)
  })
})

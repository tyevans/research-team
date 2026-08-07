import { create, type StoreApi, type UseBoundStore } from 'zustand'

import {
  activityEntries,
  emptyActivity,
  putActivity,
  type ActivityBuffer,
  type ActivityEntry,
} from '@domain/activity/activity.ts'
import type { Approval, ApprovalDecision } from '@domain/approval/approval.ts'
import { EventIndex } from '@domain/session/event-index.ts'
import {
  appendEntry,
  endsATurn,
  isCancellation,
  lastFailedTurnIndex,
  type LogEntry,
} from '@domain/session/log-entry.ts'
import { isTurnFailedType } from '@domain/session/event-kind.ts'
import { ScrubPoint } from '@domain/session/scrub-point.ts'
import type { SessionProjection } from '@domain/session/session.ts'
import { TurnEndLedger } from '@domain/session/turn-end-ledger.ts'
import { TurnState, turnNote, type TurnNote } from '@domain/session/turn.ts'
import type { ApprovalId, SessionId } from '@domain/shared/identifier.ts'

import { ApiError, errorMessage } from '../ports/errors.ts'
import type { FeedFrame } from '../ports/event-stream.ts'
import type {
  ApprovalRepository,
  RunningTurn,
  SessionRepository,
  TurnRepository,
} from '../ports/repositories.ts'

/** How long a newly-arrived event stays highlighted. */
const FRESH_MS = 1_500

export interface SessionStoreDeps {
  readonly sessions: SessionRepository
  readonly turns: TurnRepository
  readonly approvals: ApprovalRepository
  /** Injected so tests can drive it. Everything time-dependent in this store
   *  goes through it rather than calling `Date.now()` inline. */
  readonly now: () => number
  /** Called when a turn or a fork produces something worth announcing outside
   *  this session's panes. Injected rather than imported so the store stays
   *  free of any dependency on how the shell renders. */
  readonly notify: (message: string, tone: 'good' | 'bad') => void
}

export interface SessionState {
  readonly sessionId: SessionId | null
  readonly head: SessionProjection | null
  readonly log: readonly LogEntry[]
  readonly scrub: ScrubPoint
  readonly snapshot: SessionProjection | null
  readonly loadingSnapshot: boolean
  readonly snapshotError: string | null
  readonly error: string | null

  readonly turn: TurnState
  readonly note: TurnNote | null
  readonly ledger: TurnEndLedger
  /** A cancel that returned `settled: false` left the turn unwinding; its
   *  closing frame is the signal that the log is finally trustworthy. */
  readonly awaitingUnwind: boolean

  readonly activity: ActivityBuffer
  /** Failed-turn index → the provisional content that turn discarded. */
  readonly discarded: ReadonlyMap<EventIndex, readonly ActivityEntry[]>

  readonly approvals: ReadonlyMap<ApprovalId, Approval>
  readonly deciding: ApprovalId | null

  /** Event index → the moment it arrived, for the arrival highlight. */
  readonly fresh: ReadonlyMap<EventIndex, number>
}

export interface SessionActions {
  open(id: SessionId, at: ScrubPoint): Promise<void>
  close(): void
  reload(): Promise<void>
  scrubTo(at: ScrubPoint): Promise<void>
  send(input: string): Promise<void>
  cancel(): Promise<void>
  fork(at: EventIndex): Promise<SessionId | null>
  decide(approval: Approval, decision: ApprovalDecision): Promise<void>
  dismissNote(): void
  handleFrame(frame: FeedFrame): void
  handleReconnect(resumable: boolean): Promise<void>
  /** Ask the server whether a turn is running. `announce` says so in the
   *  composer even when the answer did not change anything. */
  refreshRunning(announce?: boolean): Promise<void>
  sweepFresh(): void
}

export type SessionStore = UseBoundStore<StoreApi<SessionState & SessionActions>>

const initialState = (): SessionState => ({
  sessionId: null,
  head: null,
  log: [],
  scrub: ScrubPoint.head(),
  snapshot: null,
  loadingSnapshot: false,
  snapshotError: null,
  error: null,
  turn: TurnState.idle(),
  note: null,
  ledger: TurnEndLedger.empty(),
  awaitingUnwind: false,
  activity: emptyActivity(),
  discarded: new Map(),
  approvals: new Map(),
  deciding: null,
  fresh: new Map(),
})

/** Everything a session view does, as one aggregate with explicit transitions.
 *
 * This is the module that earns the refactor. The behaviour it holds — a turn
 * that may be running in another tab, provisional content that may never be
 * recorded, a cancel that may not have settled, and a stream whose frames
 * arrive in three different channels with two different replay guarantees — was
 * previously spread across twenty mutable module-level variables and read from
 * fourteen render functions. The rules were correct and hard-won; what was
 * missing was one place where they are all stated.
 *
 * Two invariants hold everywhere below and are worth stating once:
 *
 *  - Every async action re-checks `sessionId` before writing. A user can
 *    navigate away mid-request, and a response landing in a session it was not
 *    asked about is the single easiest way to show one session's work under
 *    another's name.
 *
 *  - A turn-end *frame* always outranks a `/turns/current` *answer*. See
 *    `TurnEndLedger` for why.
 */
export const createSessionStore = (deps: SessionStoreDeps): SessionStore =>
  create<SessionState & SessionActions>((set, get) => {
    /** Guard for an async continuation: true when it still concerns the session
     *  the store is on. */
    const stillOn = (id: SessionId): boolean => get().sessionId === id

    const setNote = (note: TurnNote | null) => set({ note })

    const markFresh = (from: EventIndex, to: EventIndex) => {
      const at = deps.now()
      const fresh = new Map(get().fresh)
      for (let i: number = from; i <= to; i += 1) fresh.set(EventIndex(i), at)
      set({ fresh })
    }

    /** Reconcile "is a turn running" with what this tab is doing.
     *
     * `watching` is only ever about a turn we did *not* start: our own POST
     * owns the `sending` state, and a running answer that arrives while we are
     * sending is describing our own turn back to us. */
    const applyRunning = (running: RunningTurn) => {
      const state = get()
      if (TurnState.isOurs(state.turn)) return
      const foreign = running.running
      const wasWatching = state.turn.status === 'watching'
      if (foreign === wasWatching) return

      if (foreign) {
        set({
          note: null,
          turn: TurnState.watching({
            turnIndex: running.turnIndex,
            startedAt: running.startedAt,
            elapsedSeconds: running.elapsedSeconds,
            from: null,
          }),
        })
      } else {
        set({ turn: TurnState.idle() })
      }
    }

    /** `GET /turns/current`, with a positive answer checked against what this
     *  connection already knows to have ended. */
    const fetchRunning = async (id: SessionId): Promise<RunningTurn> => {
      const sequenceAtRequest = get().ledger.sequence
      const answer = await deps.turns.current(id)
      if (answer.running && !get().ledger.trustsRunning(sequenceAtRequest, answer.startedAt)) {
        return { running: false, turnIndex: null, startedAt: null, elapsedSeconds: null }
      }
      return answer
    }

    /** Best-effort catch-up for provisional content.
     *
     * Activity frames carry no feed position, so `Last-Event-ID` cannot replay
     * them the way it does the log — a tab that reloaded mid-turn, or whose
     * connection dropped, has no other way to learn what is in flight.
     *
     * The guard is subtle and load-bearing: a positive answer is accepted only
     * if something is *already* believed to be running by the frame-based path,
     * because this GET has the same non-atomicity as `/turns/current` and can
     * describe a turn that has already ended. Callers who cannot yet be sure —
     * a reconnect, where a turn may have started entirely during the gap — must
     * refresh that belief first, which `handleReconnect` does. */
    const catchUpActivity = async (id: SessionId): Promise<void> => {
      const sequenceAtRequest = get().ledger.sequence
      try {
        const body = await deps.turns.activity(id)
        if (!stillOn(id)) return
        const state = get()
        if (state.ledger.sequence === sequenceAtRequest && TurnState.isBusy(state.turn)) {
          let buffer = state.activity
          for (const entry of body.running) buffer = putActivity(buffer, entry)
          set({ activity: buffer })
        }
        if (body.discarded.length > 0) {
          // The discarded buffer is "the last failed turn's content" server-side
          // and carries no index, so pin it where a live frame would have.
          const index = lastFailedTurnIndex(get().log)
          if (index !== null) {
            set({ discarded: new Map(get().discarded).set(index, body.discarded) })
          }
        }
      } catch {
        // Catch-up is best effort; the next reconnect or reload tries again.
      }
    }

    const loadSnapshot = async (id: SessionId, at: ScrubPoint): Promise<void> => {
      if (at.kind === 'head') {
        set({ snapshot: null, loadingSnapshot: false, snapshotError: null })
        return
      }
      set({ loadingSnapshot: true, snapshotError: null })
      try {
        const snapshot = await deps.sessions.read(id, at)
        if (!stillOn(id) || !ScrubPoint.equals(get().scrub, at)) return
        set({ snapshot, loadingSnapshot: false })
      } catch (error) {
        if (!stillOn(id) || !ScrubPoint.equals(get().scrub, at)) return
        set({ snapshot: null, loadingSnapshot: false, snapshotError: errorMessage(error) })
      }
    }

    const load = async (id: SessionId): Promise<void> => {
      try {
        const [head, log, running, approvals] = await Promise.all([
          deps.sessions.read(id, ScrubPoint.head()),
          deps.sessions.log(id),
          // Advisory: a failure here must not fail the whole load. A turn may
          // already be running in another tab, or this may be a reload
          // mid-turn.
          fetchRunning(id).catch(() => null),
          deps.approvals.pending(id).catch(() => [] as readonly Approval[]),
        ])
        if (!stillOn(id)) return
        set({
          head,
          log,
          error: null,
          approvals: new Map(approvals.map((approval) => [approval.id, approval])),
        })
        if (running) applyRunning(running)
        await loadSnapshot(id, get().scrub)
        void catchUpActivity(id)
      } catch (error) {
        if (!stillOn(id)) return
        set({ error: errorMessage(error) })
      }
    }

    /** A turn started elsewhere ended on the stream.
     *
     * Its span is derivable from the frames themselves: the closing frame's own
     * index is the end, and the first frame seen after it started — its
     * `UserMessageSent` — is the beginning. */
    const foreignTurnEnded = (entry: LogEntry) => {
      const state = get()
      const watched = state.turn.status === 'watching' ? state.turn.turn : null
      const to = entry.index
      const from = watched?.from ?? to

      set({ turn: TurnState.idle() })

      if (isCancellation(entry)) {
        setNote(turnNote('calm', 'the turn running elsewhere was cancelled — its events were discarded'))
      } else if (isTurnFailedType(entry.type)) {
        setNote(turnNote('warn', 'the turn running elsewhere failed'))
      } else {
        markFresh(from, to)
        setNote(
          turnNote('good', 'the turn running elsewhere finished', {
            range: { turnIndex: entry.turnIndex ?? watched?.turnIndex ?? null, from, to },
          }),
        )
      }
      // Stream frames are timeline rows only — no message content, no file
      // contents. The conversation and workspace panes can only be brought up
      // to date by refetching, so a turn ending always costs one load.
      void get().reload()
    }

    return {
      ...initialState(),

      async open(id, at) {
        // A turn in flight belongs to the session being left; the composer
        // about to be mounted is a different one and must start enabled.
        set({ ...initialState(), sessionId: id, scrub: at })
        await load(id)
      },

      close() {
        set(initialState())
      },

      async reload() {
        const id = get().sessionId
        if (id) await load(id)
      },

      async scrubTo(at) {
        const id = get().sessionId
        if (!id) return
        set({ scrub: at })
        await loadSnapshot(id, at)
      },

      async send(input) {
        const state = get()
        const id = state.sessionId
        if (!id || TurnState.isBusy(state.turn)) return
        const text = input.trim()
        if (!text) return

        set({ turn: TurnState.sending(deps.now()), note: null })
        try {
          const range = await deps.turns.send(id, text)
          if (range) {
            markFresh(range.from, range.to)
            setNote(turnNote('good', 'turn complete', { range }))
          } else {
            setNote(turnNote('good', 'turn complete'))
          }
          deps.notify('Turn complete.', 'good')
        } catch (error) {
          if (error instanceof ApiError && error.isCancelled) {
            // Cancelled on purpose. Not a failure — no toast, no red.
            setNote(
              turnNote(
                'calm',
                get().awaitingUnwind
                  ? 'cancel delivered — the turn is still unwinding'
                  : 'turn cancelled — its events were discarded',
              ),
            )
          } else if (error instanceof ApiError && error.isConflict) {
            setNote(turnNote('warn', error.message, { recheck: true }))
          } else {
            setNote(turnNote('warn', `turn failed — ${errorMessage(error)}`))
            deps.notify(`Turn failed: ${errorMessage(error)}`, 'bad')
          }
        } finally {
          // Always clear the in-flight state, even if the user navigated away
          // while the turn ran — otherwise the composer stays disabled for good.
          if (get().turn.status === 'sending') set({ turn: TurnState.idle() })
          if (stillOn(id)) {
            // The turn is atomic, so refetch the whole log rather than trusting
            // the events that streamed in mid-flight.
            await load(id)
          }
        }
      },

      async cancel() {
        const state = get()
        const id = state.sessionId
        if (!id || TurnState.isCancelRequested(state.turn)) return
        const wasOurs = TurnState.isOurs(state.turn)
        set({ turn: TurnState.withCancelRequested(state.turn) })
        try {
          const result = await deps.turns.cancel(id)
          if (!stillOn(id)) return
          if (result.cancelled) {
            set({ awaitingUnwind: !result.settled })
            // The POST /turns still in flight settles as a 499 and writes the
            // note itself; only speak up here when this tab is not the sender.
            if (!wasOurs) {
              set({ turn: TurnState.idle() })
              setNote(
                turnNote(
                  'calm',
                  result.settled
                    ? 'turn cancelled — its events were discarded'
                    : 'cancel delivered — the turn is still unwinding',
                ),
              )
            }
          } else {
            set({ turn: TurnState.idle() })
            setNote(turnNote('calm', 'nothing was running'))
          }
        } catch (error) {
          if (!stillOn(id)) return
          setNote(turnNote('warn', `could not cancel — ${errorMessage(error)}`, { recheck: true }))
          deps.notify(`Cancel failed: ${errorMessage(error)}`, 'bad')
        } finally {
          if (stillOn(id) && !TurnState.isOurs(get().turn)) await load(id)
        }
      },

      async fork(at) {
        const id = get().sessionId
        if (!id) return null
        try {
          const forked = await deps.sessions.fork(id, at)
          deps.notify(`Forked at event ${at}.`, 'good')
          return forked
        } catch (error) {
          deps.notify(`Fork failed: ${errorMessage(error)}`, 'bad')
          return null
        }
      },

      async decide(approval, decision) {
        if (get().deciding) return
        set({ deciding: approval.id })
        try {
          await deps.approvals.decide(approval.sessionId, approval.id, decision)
        } catch (error) {
          // A 404 means somebody else already answered it; `ApprovalSettled`
          // will have cleared the card, so there is nothing left to undo.
          if (!(error instanceof ApiError && error.isNotFound)) {
            deps.notify(`Could not record decision: ${errorMessage(error)}`, 'bad')
          }
        } finally {
          if (get().deciding === approval.id) set({ deciding: null })
        }
      },

      dismissNote() {
        if (get().note) set({ note: null })
      },

      handleFrame(frame) {
        const state = get()

        if (frame.kind === 'approvalRequested') {
          if (frame.approval.sessionId !== state.sessionId) return
          set({ approvals: new Map(state.approvals).set(frame.approval.id, frame.approval) })
          return
        }

        if (frame.kind === 'approvalSettled') {
          if (frame.sessionId !== state.sessionId) return
          const approvals = new Map(state.approvals)
          approvals.delete(frame.approvalId)
          set({
            approvals,
            deciding: state.deciding === frame.approvalId ? null : state.deciding,
          })
          return
        }

        if (frame.kind === 'activity') {
          if (frame.entry.sessionId !== state.sessionId) return
          set({ activity: putActivity(state.activity, frame.entry) })
          // A turn's ordinary log frames only arrive in a burst when it commits,
          // so a tab that did not send this turn has no other early signal that
          // one is running. But activity and log frames are pumped by two
          // independent tasks, so a frame can straggle in after the turn it
          // belongs to has committed — and nothing on the frame tells the two
          // cases apart. Rather than trust its mere arrival, which would
          // resurrect an ended turn and leave a bubble nothing clears, ask.
          if (!TurnState.isBusy(state.turn)) void get().refreshRunning()
          return
        }

        if (frame.sessionId !== state.sessionId) return

        const log = appendEntry(state.log, frame.entry)
        const isNew = log !== state.log
        if (isNew) {
          set({ log })
          markFresh(frame.entry.index, frame.entry.index)
        }

        // Where a watched turn began: its first frame is the UserMessageSent
        // that opened it.
        if (state.turn.status === 'watching' && !endsATurn(frame.entry)) {
          set({ turn: TurnState.withWatchedOrigin(get().turn, frame.entry.index) })
        }

        // Everything below reconciles a turn ending and must run once per turn.
        // Guarded on `isNew` — a genuinely unseen frame — rather than on the
        // turn state, because a reconnect can replay an already-known turn end,
        // and unlike the turn state (which `refreshRunning` can flip from
        // outside this handler) the log's own contents are this handler's.
        if (isNew && endsATurn(frame.entry)) {
          set({ ledger: get().ledger.recordEnding(frame.entry.occurredAt, deps.now()) })

          // On success the real log events are the record now, so provisional
          // content is dropped: it would only duplicate what is about to
          // render. On failure nothing was appended but the marker itself, so
          // what streamed is the only trace of the attempt — keep it, behind a
          // disclosure, on that row.
          if (isTurnFailedType(frame.entry.type)) {
            const provisional = activityEntries(get().activity)
            if (provisional.length > 0) {
              set({ discarded: new Map(get().discarded).set(frame.entry.index, provisional) })
            }
          }
          set({ activity: emptyActivity() })

          // A turn-end frame for a turn we did not start is authoritative
          // regardless of what we believed: `refreshRunning` can set the
          // watching state a moment *after* this frame said otherwise, and if
          // this branch were conditional on that flag there would be nothing
          // left to correct it.
          if (!TurnState.isOurs(get().turn)) {
            foreignTurnEnded(frame.entry)
            return
          }
        }

        if (get().awaitingUnwind && endsATurn(frame.entry)) {
          set({ awaitingUnwind: false })
          setNote(turnNote('calm', 'turn cancelled — its events were discarded'))
          void get().reload()
        }
      },

      async handleReconnect(resumable) {
        const id = get().sessionId
        if (!id) return
        if (!resumable) {
          // No cursor to resume from: the server cannot place this connection,
          // so everything has to be refetched.
          await load(id)
          return
        }
        if (TurnState.isOurs(get().turn)) return
        // Approval and activity frames carry no feed position, so the cursor
        // resumed the log but not these. `refreshRunning` runs first and is
        // awaited on purpose: a turn may have started entirely during the gap,
        // and `catchUpActivity`'s guard trusts the turn state, so that belief
        // has to be current before the guard checks it.
        await Promise.all([
          deps.approvals
            .pending(id)
            .then((pending) => {
              if (stillOn(id)) set({ approvals: new Map(pending.map((a) => [a.id, a])) })
            })
            .catch(() => undefined),
          get()
            .refreshRunning()
            .then(() => (stillOn(id) ? catchUpActivity(id) : undefined)),
        ])
      },

      async refreshRunning(announce = false) {
        const id = get().sessionId
        if (!id) return
        try {
          const wasWatching = get().turn.status === 'watching'
          const answer = await fetchRunning(id)
          if (!stillOn(id)) return
          applyRunning(answer)
          if (wasWatching && get().turn.status !== 'watching') {
            setNote(turnNote('good', 'the turn running elsewhere finished'))
            await load(id)
          } else if (announce && !TurnState.isBusy(get().turn)) {
            setNote(turnNote('good', 'nothing is running — you can send a turn'))
          }
        } catch (error) {
          if (!stillOn(id)) return
          if (announce) {
            setNote(turnNote('warn', `could not check — ${errorMessage(error)}`, { recheck: true }))
          }
        }
      },

      sweepFresh() {
        const now = deps.now()
        const fresh = new Map(get().fresh)
        let changed = false
        for (const [index, at] of fresh) {
          if (now - at >= FRESH_MS) {
            fresh.delete(index)
            changed = true
          }
        }
        if (changed) set({ fresh })
      },
    }
  })

/** The projection the panes read: HEAD, or the fold the reader scrubbed to. */
export const currentView = (state: SessionState): SessionProjection | null =>
  state.scrub.kind === 'head' ? state.head : state.snapshot

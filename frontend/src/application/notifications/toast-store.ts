import { create } from 'zustand'

export type ToastTone = 'neutral' | 'good' | 'bad'

export interface Toast {
  readonly id: number
  readonly message: string
  readonly tone: ToastTone
  /** How much longer this toast has, in milliseconds. Counted down by the
   *  sweeper rather than stored as a deadline, so a hold does not need to
   *  rewrite every toast's expiry when it is released. */
  readonly remainingMs: number
}

interface ToastState {
  readonly toasts: readonly Toast[]
  /** How many reasons there are not to expire anything right now. A counter
   *  rather than a boolean because the pointer and the keyboard can hold the
   *  stack at the same time -- hovering one toast while focus is in another --
   *  and a boolean would let whichever left first release both. */
  readonly holds: number
  push(message: string, tone?: ToastTone): void
  dismiss(id: number): void
  hold(): void
  release(): void
  /** Advance every toast's clock and drop whatever ran out. Exported on the
   *  store rather than hidden in a closure so tests can step time without
   *  faking timers, which `vitest.setup.ts` and BACKLOG B4 both argue for:
   *  a test that waits a duration is a test that fails on a loaded machine. */
  tick(elapsedMs: number): void
}

/** A bad toast stays up longer than a good one: it is more likely to be the
 *  thing somebody needs to read, and more likely to arrive while they are
 *  looking somewhere else. */
const LIFETIME_MS: Readonly<Record<ToastTone, number>> = {
  neutral: 3_800,
  good: 3_800,
  bad: 7_000,
}

/** How often the sweeper runs. Coarse on purpose -- this drives a fade, not a
 *  countdown anybody reads, and a 250ms granularity on a 3.8s lifetime is
 *  invisible while costing four wakeups a second instead of sixty. */
const SWEEP_MS = 250

let nextId = 0

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  holds: 0,

  push(message, tone = 'neutral') {
    const id = (nextId += 1)
    set({ toasts: [...get().toasts, { id, message, tone, remainingMs: LIFETIME_MS[tone] }] })
    startSweeping()
  },

  dismiss(id) {
    set({ toasts: get().toasts.filter((toast) => toast.id !== id) })
  },

  hold() {
    set({ holds: get().holds + 1 })
  },

  release() {
    // Clamped at zero: a release without a matching hold is a bug somewhere
    // else, and letting the count go negative would make the *next* hold fail
    // to hold, which is a far more confusing symptom than the original.
    set({ holds: Math.max(0, get().holds - 1) })
  },

  tick(elapsedMs) {
    // Held: the reader is pointing at or typing into the toast stack, so
    // nothing expires. Their clocks do not advance either -- a toast that
    // silently used up its life while being read would vanish the instant
    // attention left it, which is the behaviour a hold exists to prevent.
    if (get().holds > 0) return

    const toasts = get()
      .toasts.map((toast) => ({ ...toast, remainingMs: toast.remainingMs - elapsedMs }))
      .filter((toast) => toast.remainingMs > 0)

    // Only write when something actually changed, so an idle console is not
    // re-rendering every subscriber four times a second forever.
    if (toasts.length !== get().toasts.length) set({ toasts })
  },
}))

/** One interval for the whole store, started on the first toast and stopped
 *  when the last one goes.
 *
 * This replaces a `setTimeout` per toast, and the reason is the hold: a
 * timeout cannot be paused, only cancelled and re-armed with a recomputed
 * delay, so pausing would have meant tracking a deadline and a remaining
 * duration per toast anyway -- and getting the re-arm wrong is how a toast
 * ends up immortal.
 */
let sweeper: ReturnType<typeof setInterval> | null = null

const startSweeping = () => {
  if (sweeper !== null) return
  sweeper = setInterval(() => {
    useToasts.getState().tick(SWEEP_MS)
    if (useToasts.getState().toasts.length === 0 && sweeper !== null) {
      clearInterval(sweeper)
      sweeper = null
    }
  }, SWEEP_MS)
}

/** The store's `push`, callable from a non-component (the session store's
 *  `notify` port) without importing React. */
export const notify = (message: string, tone: ToastTone = 'neutral'): void => {
  useToasts.getState().push(message, tone)
}

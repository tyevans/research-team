import { create } from 'zustand'

export type ToastTone = 'neutral' | 'good' | 'bad'

export interface Toast {
  readonly id: number
  readonly message: string
  readonly tone: ToastTone
}

interface ToastState {
  readonly toasts: readonly Toast[]
  push(message: string, tone?: ToastTone): void
  dismiss(id: number): void
}

/** A bad toast stays up longer than a good one: it is more likely to be the
 *  thing somebody needs to read, and more likely to arrive while they are
 *  looking somewhere else. */
const LIFETIME_MS: Readonly<Record<ToastTone, number>> = {
  neutral: 3_800,
  good: 3_800,
  bad: 7_000,
}

let nextId = 0

export const useToasts = create<ToastState>((set, get) => ({
  toasts: [],
  push(message, tone = 'neutral') {
    const id = (nextId += 1)
    set({ toasts: [...get().toasts, { id, message, tone }] })
    setTimeout(() => get().dismiss(id), LIFETIME_MS[tone])
  },
  dismiss(id) {
    set({ toasts: get().toasts.filter((toast) => toast.id !== id) })
  },
}))

/** The store's `push`, callable from a non-component (the session store's
 *  `notify` port) without importing React. */
export const notify = (message: string, tone: ToastTone = 'neutral'): void => {
  useToasts.getState().push(message, tone)
}

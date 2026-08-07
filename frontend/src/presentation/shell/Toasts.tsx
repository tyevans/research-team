import clsx from 'clsx'

import { useToasts } from '@application/notifications/toast-store.ts'

export const Toasts = () => {
  const toasts = useToasts((state) => state.toasts)

  return (
    <div id="toasts" className="toasts" aria-live="polite">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={clsx('toast', toast.tone !== 'neutral' && toast.tone)}
          onClick={() => useToasts.getState().dismiss(toast.id)}
        >
          {toast.message}
        </div>
      ))}
    </div>
  )
}

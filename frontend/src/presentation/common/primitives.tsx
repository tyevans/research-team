import clsx from 'clsx'
import { useId, type ButtonHTMLAttributes, type ReactNode } from 'react'

/** The handful of shapes every view in this console reaches for.
 *
 * Extracted because the previous implementation built each of them inline at
 * every call site, which is how three subtly different empty states and four
 * spellings of the same chip came to exist. */

export type ButtonTone = 'default' | 'accent' | 'quiet' | 'danger' | 'ghost'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  tone?: ButtonTone
  small?: boolean
}

export const Button = ({ tone = 'default', small, className, ...rest }: ButtonProps) => (
  <button
    type="button"
    className={clsx('btn', small && 'btn-sm', tone !== 'default' && `btn-${tone}`, className)}
    {...rest}
  />
)

export const Chip = ({
  tone,
  title,
  children,
}: {
  tone?: string
  title?: string
  children: ReactNode
}) => <span className={clsx('chip', tone && `chip-${tone}`)} title={title}>{children}</span>

export const EmptyState = ({ title, detail }: { title: string; detail?: ReactNode }) => (
  <div className="empty">
    <strong>{title}</strong>
    {detail}
  </div>
)

export const Loading = ({ what }: { what: string }) => (
  <div className="empty">loading {what}…</div>
)

export const ErrorBox = ({
  title,
  message,
  onRetry,
}: {
  title: string
  message: string
  onRetry?: () => void
}) => (
  <div className="error-box">
    <strong>{title}</strong>
    {message}
    {onRetry ? (
      <div>
        <Button small onClick={onRetry}>
          Retry
        </Button>
      </div>
    ) : null}
  </div>
)

/** A labelled fold.
 *
 * A `<button>` driving an `aria-controls` region rather than `<details>`,
 * because the open state has to survive a re-render driven from elsewhere —
 * a tool run stays open while its conversation refetches — and `<details>`
 * owns that state itself. */
export const Disclosure = ({
  label,
  open,
  onToggle,
  className,
  children,
}: {
  label: ReactNode
  open: boolean
  onToggle: () => void
  className?: string
  children: ReactNode
}) => {
  const id = useId()
  return (
    <div className={clsx('disc', className)}>
      <button
        type="button"
        className="disc-head"
        aria-expanded={open}
        aria-controls={id}
        onClick={onToggle}
      >
        <span className="disc-caret" aria-hidden="true">
          {open ? '▾' : '▸'}
        </span>
        {label}
      </button>
      <div className="disc-body" id={id} hidden={!open}>
        {open ? children : null}
      </div>
    </div>
  )
}

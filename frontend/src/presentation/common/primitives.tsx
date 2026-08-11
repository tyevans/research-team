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

/** A chip carries no explanation of its own.
 *
 * It had a `title` prop, and eleven call sites used it — which made this one
 * component the single largest source of the S-D3 defect in the console: a
 * `<span>` is focusable by nothing, so every one of those sentences was
 * available to a hovering mouse and to no other reader. The prop is gone
 * rather than deprecated so that the eleven were a compile error rather than a
 * grep, and an explained chip is now `<Tooltip><Chip>…</Chip></Tooltip>`,
 * which supplies the tab stop the chip cannot. */
export const Chip = ({ tone, children }: { tone?: string; children: ReactNode }) => (
  <span className={clsx('chip', tone && `chip-${tone}`)}>{children}</span>
)

/** `heading` rather than `title` throughout this file, and in `Drawer`,
 *  `Confirm` and `ErrorBox` for the same reason. A prop named `title` on a
 *  React component is one keystroke and one careless refactor away from the
 *  HTML attribute of that name, and the two have nothing in common: this one
 *  renders as a heading, the attribute renders as a hover nobody can reach.
 *  With the name gone from every component in `presentation`, a bare `title=`
 *  there is unambiguous, which is what lets `check-deleted.mjs` forbid it
 *  outright instead of trying to tell the two apart with a regex. */
export const EmptyState = ({ heading, detail }: { heading: string; detail?: ReactNode }) => (
  <div className="empty">
    <strong>{heading}</strong>
    {detail}
  </div>
)

export const Loading = ({ what }: { what: string }) => <div className="empty">loading {what}…</div>

export const ErrorBox = ({
  heading,
  message,
  onRetry,
}: {
  heading: string
  message: string
  onRetry?: () => void
}) => (
  <div className="error-box">
    <strong>{heading}</strong>
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

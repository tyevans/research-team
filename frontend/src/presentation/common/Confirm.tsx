import { Button, type ButtonTone } from './primitives.tsx'
import { Drawer } from './Drawer.tsx'

/** "Are you sure" in the console's own chrome rather than the browser's.
 *
 * The wording these carry was already right — a take-over says what survives
 * it, a delete says what a delete does *not* take with it — and it is kept
 * verbatim. What changes is the container. `window.confirm` blocks the whole
 * tab, cannot be styled, cannot say more than one paragraph legibly, and in an
 * app that already ships a focus-trapping drawer it reads as something that
 * escaped from another program.
 *
 * Built on `Drawer` rather than beside it, so the keyboard contract is the one
 * every other dialog here has: focus in on open and back on close, Escape
 * closes, and Tab cannot walk out into the page behind.
 */
export const Confirm = ({
  heading,
  lines,
  confirmLabel,
  tone = 'accent',
  onConfirm,
  onCancel,
}: {
  heading: string
  /** The body, one paragraph per entry. A list rather than one string because
   *  these sentences are deliberately separate thoughts, and joining them with
   *  newlines was only ever a limitation of the native dialog. */
  lines: readonly string[]
  confirmLabel: string
  tone?: ButtonTone
  onConfirm: () => void
  onCancel: () => void
}) => (
  <Drawer heading={heading} label={heading} onClose={onCancel}>
    <div className="confirm">
      {lines.map((line) => (
        <p key={line}>{line}</p>
      ))}
      <div className="confirm-actions">
        <Button onClick={onCancel}>Cancel</Button>
        <Button tone={tone} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </div>
  </Drawer>
)

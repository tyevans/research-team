import * as RadioGroup from '@radix-ui/react-radio-group'
import clsx from 'clsx'
import type { ReactNode } from 'react'

import { Tooltip } from './Tooltip.tsx'

/** One choice with a fixed set of answers, laid out as a row of buttons.
 *
 * **Not `Tabs`, and the difference is not cosmetic.** A tab claims to control a
 * panel and carries an `aria-controls` saying which; these controls change how
 * a single panel draws itself. `FileView`'s `rendered`/`source` and
 * `author`/`learner` rows were built from the same `TabGroup` as its real tabs
 * and looked the part, which is how one header came to hold three identical
 * rows meaning two different things. `Tabs.tsx` states the test for choosing
 * between them.
 *
 * **Why a library rather than the eight lines this looks like.** Those eight
 * lines already exist twice: this component's predecessor, and `TopicQueue`'s
 * `role="radiogroup"` of four `role="radio"` buttons. Both announce a
 * radiogroup and neither behaves like one -- every option is its own tab stop,
 * and the arrow keys a screen-reader user is told to expect do nothing. The
 * declaration and the behaviour were two facts that could disagree, and did.
 *
 * **`RadioGroup` rather than `ToggleGroup`, which was tried first.**
 * `ToggleGroup type="single"` renders the same markup and is the obvious
 * candidate -- and its arrow keys move focus without changing the selection,
 * because it is built for a formatting toolbar where the pressed item is a
 * separate question from the focused one. That is the wrong contract under a
 * `radiogroup` role: the APG has selection follow focus for radios, and a
 * screen reader announces these as radios either way. It also allows the
 * pressed item to be pressed off again, reporting `''` -- there is no "neither
 * rendered nor source", so that would have needed a guard of ours, and a
 * primitive whose first act is to suppress half of what its library does is the
 * wrong library. `RadioGroup` has both properties without being asked, at the
 * cost of a dependency whose name says radio in a row of controls that do not
 * look like radios. `Choices.test.tsx` fails on both if this is swapped back.
 */
export const Choices = <T extends string>({
  label,
  options,
  value,
  onValueChange,
  className,
}: {
  /** Names the group for a screen reader. "How to show this file" rather than
   *  "mode" -- the row's two words are the answers, and nothing on screen says
   *  what the question was. */
  label: string
  options: readonly { id: T; label: string; explanation?: ReactNode }[]
  value: T
  onValueChange: (value: T) => void
  className?: string
}) => (
  <RadioGroup.Root
    value={value}
    // Radix types this as `(value: string) => void` because a radio group's
    // value is a string to the DOM. The cast is narrowing it back to the union
    // the caller passed in `options`, and is safe for exactly as long as
    // nothing else writes a value into the group -- nothing can, since the
    // items are rendered here from those same options.
    onValueChange={(next) => onValueChange(next as T)}
    // `horizontal` so the left/right arrows are the ones that move, matching
    // how the row is drawn. Radix's default is vertical, which would leave a
    // visibly horizontal group answering to up and down.
    orientation="horizontal"
    className={clsx('tabs', className)}
    aria-label={label}
  >
    {options.map((option) => (
      <Choice key={option.id} option={option} />
    ))}
  </RadioGroup.Root>
)

/** One option, wrapped in its explanation only when it has one.
 *
 * Inherited from the component this replaces, along with its reasoning: two of
 * `FileView`'s eight controls carry a sentence -- author and learner, where the
 * difference between the two views is the whole reason the switch exists and is
 * not deducible from the two words on the buttons. The other six are
 * self-describing, and wrapping them anyway would put a `Tooltip` around
 * "contents" for the sake of uniformity.
 *
 * `asChild` on the tooltip: the `RadioGroup.Item` is already a real button that
 * forwards a ref, and it is the *item* that has to carry the roving tabindex.
 * `Tooltip`'s own wrapper button would take that away and put a second
 * focusable element around the first.
 */
const Choice = <T extends string>({
  option,
}: {
  option: { id: T; label: string; explanation?: ReactNode }
}) => {
  const item = (
    <RadioGroup.Item value={option.id} className="tab">
      {option.label}
    </RadioGroup.Item>
  )
  if (!option.explanation) return item
  return (
    <Tooltip asChild explanation={option.explanation}>
      {item}
    </Tooltip>
  )
}

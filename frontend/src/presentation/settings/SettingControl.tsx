import type { SettingSpec } from '@domain/settings/spec.ts'

import { Choices } from '../common/Choices.tsx'

/** The control for one setting, chosen from its declaration.
 *
 * There is no map from key to control anywhere in this directory. `type`
 * decides, `minimum`/`maximum` bound, `choices` fills the menu — all off the
 * schema, so a fortieth setting needs no frontend change at all. That is the
 * whole reason `settings.py` publishes a registry rather than a settings page
 * publishing a copy of one.
 *
 * **The control is live on an inherited row, not locked.** Typing into a row
 * that reads `tenant` and committing creates the override. The rejected
 * alternative is a per-row "Override" toggle that unlocks the control: two
 * clicks for the common case, and the toggle's state is a second thing that
 * can disagree with the data — a row reading `tenant` with the toggle on is a
 * state somebody would have to define.
 *
 * **Booleans post `on`/`off` and nothing else, and the client never parses
 * one.** `TRUE_WORDS` and `FALSE_WORDS` are Python constants the schema does
 * not publish, so any client-side parse would be a guess at a list it cannot
 * see. Two controls posting a two-element subset the server is guaranteed to
 * accept needs no guess. The server stays the authority in every case here;
 * `min`/`max` and the menu exist to save a round trip, not to be the rule.
 */
export const SettingControl = ({
  spec,
  value,
  onChange,
  onCommit,
  disabled,
  describedBy,
  id,
  suggestions = [],
}: {
  spec: SettingSpec
  /** The draft, always a string. One representation for five types, because
   *  the write route takes a string whatever the type — carrying a number
   *  through the component and stringifying at the edge would be two
   *  representations and one place for them to disagree about `''`. */
  value: string
  onChange: (next: string) => void
  /** Blur, Enter, or a choice being made. Per field, because the contract is
   *  per key and there is no batch.
   *
   *  **Takes the value explicitly rather than reading the parent's draft.**
   *  A `<select>` and a `Choices` hand back the new value and commit in the
   *  same event, where the parent's draft is still one render behind — so a
   *  no-argument `onCommit` would save the *previous* choice on every
   *  press. Silent, and off by exactly one interaction, which is the shape of
   *  bug that survives a demo. */
  onCommit: (value: string) => void
  disabled: boolean
  describedBy: string | undefined
  id: string
  /** Values worth offering, from somewhere that knows more than the schema
   *  does -- today, the models a connection test just found at this group's
   *  endpoint.
   *
   *  A `<datalist>` rather than a `<select>`, and the difference is the point:
   *  a list that came back from one endpoint is a *suggestion*, not the set of
   *  legal values. A model can be servable without appearing in `/v1/models`,
   *  and an endpoint that has not been tested offers nothing at all -- so a
   *  control that refused anything unlisted would refuse correct input in both
   *  cases. Free text stays free; the list saves the typing.
   *
   *  Only for text: `enum` already has its choices from the schema and
   *  numerics have bounds, so neither has anything to learn from a probe. */
  suggestions?: readonly string[]
}) => {
  if (spec.type === 'boolean') {
    return (
      // A `<fieldset disabled>` rather than a `disabled` prop on `Choices`,
      // which has none. The attribute disables every form control inside it
      // natively -- including Radix's radio buttons, which are real `<button>`
      // elements -- so it also takes them out of the tab order, which a
      // hand-rolled `aria-disabled` would not. `border-0 p-0 m-0` because a
      // fieldset carries a browser border and padding that would otherwise
      // draw a box around one row's switch and nothing else's.
      <fieldset disabled={disabled} className="m-0 border-0 p-0">
        <Choices
          label={spec.label}
          options={BOOLEAN_OPTIONS}
          // Anything that is not the literal `on` draws as off, including an
          // empty draft. A third visual state for "we are not sure" would be a
          // state the server has no spelling for.
          value={value === 'on' ? 'on' : 'off'}
          onValueChange={(next) => {
            onChange(next)
            // Committed on the press rather than on a later blur: a two-button
            // row has no blur a person would recognise as "done", and a switch
            // that has visibly moved but not saved is the disagreement between
            // control state and data this page is built to avoid.
            onCommit(next)
          }}
        />
      </fieldset>
    )
  }

  if (spec.type === 'enum') {
    return (
      <select
        id={id}
        className="input"
        value={value}
        disabled={disabled}
        aria-describedby={describedBy}
        onChange={(event) => {
          onChange(event.target.value)
          onCommit(event.target.value)
        }}
      >
        {/* An empty option only while the draft is empty, so a value the
            schema no longer offers is visible as "nothing chosen" rather than
            silently snapping to the first choice -- which would be the page
            changing a setting nobody touched. */}
        {value === '' ? <option value="">—</option> : null}
        {spec.choices.map((choice) => (
          <option key={choice} value={choice}>
            {choice}
          </option>
        ))}
      </select>
    )
  }

  const numeric = spec.type === 'integer' || spec.type === 'number'
  const listId = !numeric && suggestions.length > 0 ? `${id}-suggestions` : undefined

  return (
    <>
      <input
        id={id}
        className="input w-full"
        type={numeric ? 'number' : 'text'}
        value={value}
        disabled={disabled}
        aria-describedby={describedBy}
        list={listId}
        // Both from the declaration. `?? undefined` rather than `?? ''`: an
        // empty `min` attribute is not the same as an absent one to a browser's
        // own validation, and `exactOptionalPropertyTypes` makes the difference
        // a type error rather than a surprise.
        min={numeric ? (spec.minimum ?? undefined) : undefined}
        max={numeric ? (spec.maximum ?? undefined) : undefined}
        step={spec.type === 'integer' ? 1 : undefined}
        onChange={(event) => onChange(event.target.value)}
        onBlur={() => onCommit(value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter') {
            event.preventDefault()
            onCommit(value)
          }
        }}
      />
      {listId ? (
        <datalist id={listId}>
          {suggestions.map((suggestion) => (
            <option key={suggestion} value={suggestion} />
          ))}
        </datalist>
      ) : null}
    </>
  )
}

/** The two spellings `SettingSpec.parse` is guaranteed to accept. */
const BOOLEAN_OPTIONS = [
  { id: 'on' as const, label: 'on' },
  { id: 'off' as const, label: 'off' },
]

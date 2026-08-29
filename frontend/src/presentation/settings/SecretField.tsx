import type { ResolvedSetting } from '@domain/settings/layer.ts'
import type { SettingSpec } from '@domain/settings/spec.ts'

import { Button } from '../common/primitives.tsx'

/** A credential field. Three states and no fourth.
 *
 * **Unset** — an empty `<input type="password">` with a `paste a key`
 * placeholder, and the server's own `masked.display` (`not set`) as help text.
 *
 * **Set, untouched** — *no input element with a value in it at all*. The
 * display is text, `set (…1234)`, beside `Replace` and `Clear`.
 *
 * **Replacing** — an empty password input plus `Cancel`, which returns to
 * set-and-untouched. The draft is `''` until the person types and is never
 * seeded from anything.
 *
 * **There is deliberately no row of bullets, and that is the load-bearing
 * decision rather than a styling preference.** A bullet string is a *value*: it
 * lives in an input, it is submittable, and it is one careless change — an
 * `onChange` that fires on mount, a form that posts every field, a password
 * manager that decides to help — away from being round-tripped to the server
 * as the literal password. The masked state holds no input, so there is
 * nothing to submit. `secret-field.test.tsx` asserts that directly by querying
 * for an input and expecting none, which is an assertion that fails the moment
 * anybody reintroduces one for the look of it.
 *
 * `autoComplete="off"` and `data-1p-ignore` on every password input here, for
 * the same reason one step further: a masked display that looks like a filled
 * password field is an invitation to a manager, and a manager filling it is
 * precisely the round trip the contract forbids. `data-1p-ignore` is 1Password's
 * opt-out specifically; `autoComplete="off"` is what the rest honour. Neither
 * alone covers the field, which is why both are here.
 *
 * **A failed save keeps the paste.** This component never clears, resets or
 * refetches its draft on failure — the parent renders the server's `detail`
 * beside it and the text stays exactly where it was. A form that loses a
 * pasted API key on a 422 is the defect this design exists to remove, and the
 * 422 that will actually happen most is "a secret with no `AGENT_SETTINGS_KEY`
 * configured", which the person cannot fix from this page at all.
 */
export const SecretField = ({
  spec,
  resolved,
  draft,
  onDraftChange,
  onCommit,
  onClear,
  canEdit,
  busy,
  describedBy,
  id,
}: {
  spec: SettingSpec
  /** This scope's resolution for the key. `value` is `null` by contract; the
   *  mask is what says whether anything is stored. */
  resolved: ResolvedSetting
  /** `null` when not replacing, a string (possibly empty) when replacing.
   *  The two are different states and a bare `''` cannot tell them apart —
   *  "the person opened Replace and has typed nothing" has a Cancel button and
   *  "the person is looking at the masked display" does not. */
  draft: string | null
  onDraftChange: (next: string | null) => void
  onCommit: (value: string) => void
  onClear: () => void
  canEdit: boolean
  busy: boolean
  describedBy: string | undefined
  id: string
}) => {
  const stored = resolved.masked?.present ?? false
  const replacing = draft !== null

  // Read-only for a caller `canEdit` refuses. The display, never the input:
  // rendering a disabled password box would put a control in the accessibility
  // tree that can never do anything, and the point of the denied state is that
  // there is nothing to reach.
  if (!canEdit) {
    return (
      <p className="m-0 font-mono text-sm text-fg-dim" id={id}>
        {resolved.masked?.display ?? 'not set'}
      </p>
    )
  }

  if (stored && !replacing) {
    return (
      <div className="flex flex-wrap items-center gap-2">
        {/* Text, not an input. See the docstring: there is no element here
            holding a value, which is what makes the round trip impossible
            rather than merely unlikely. */}
        <span className="font-mono text-sm text-fg" id={id}>
          {resolved.masked?.display ?? 'set'}
        </span>
        <Button small onClick={() => onDraftChange('')} disabled={busy}>
          Replace
        </Button>
        <Button small tone="danger" onClick={onClear} disabled={busy}>
          Clear
        </Button>
      </div>
    )
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      <input
        id={id}
        className="input min-w-56 flex-1"
        type="password"
        // Empty string, always, on both the unset and the replacing paths. The
        // one thing this must never do is seed from the resolution -- which
        // could not carry a credential anyway, and writing `?? resolved.value`
        // here would be a line that compiles, does nothing today, and starts
        // leaking the day the contract changes.
        value={draft ?? ''}
        placeholder="paste a key"
        autoComplete="off"
        data-1p-ignore
        data-lpignore="true"
        disabled={busy}
        aria-describedby={describedBy}
        aria-label={spec.label}
        onChange={(event) => onDraftChange(event.target.value)}
        onKeyDown={(event) => {
          if (event.key === 'Enter' && draft) {
            event.preventDefault()
            onCommit(draft)
          }
        }}
      />
      <Button small tone="accent" disabled={busy || !draft} onClick={() => onCommit(draft ?? '')}>
        Save
      </Button>
      {/* Cancel only while replacing. On the unset path there is nothing to
          return to, and a Cancel that puts an empty field back the way it was
          is a control that does nothing. */}
      {stored ? (
        <Button small onClick={() => onDraftChange(null)} disabled={busy}>
          Cancel
        </Button>
      ) : null}
    </div>
  )
}

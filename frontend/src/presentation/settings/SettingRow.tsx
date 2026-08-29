import clsx from 'clsx'
import { useId, useState } from 'react'

import {
  displayValue,
  isOverriddenAt,
  type ResolvedSetting,
  type ScopeRef,
} from '@domain/settings/layer.ts'
import type { Scope, SettingSpec } from '@domain/settings/spec.ts'

import { Confirm } from '../common/Confirm.tsx'
import { Button } from '../common/primitives.tsx'
import { LayerChip } from './LayerChip.tsx'
import { SecretField } from './SecretField.tsx'
import { SettingControl } from './SettingControl.tsx'
import { DENIED_COPY, useCanEdit } from './permissions.ts'
import { useMarkUnsaved } from './use-unsaved-guard.ts'
import { useSettingCommit } from './use-setting-commit.ts'

/** One setting, as a row.
 *
 * A row and not a form field, and the difference is that a row carries its own
 * provenance and its own verb. Left to right: a 2px bar coloured by layer, the
 * label and its help text, the control, the layer chip, and `Clear` when this
 * scope is the one that set it. Under an overridden row, one more line saying
 * what clearing it would reveal.
 *
 * **The bar is `border-l-2` and nothing else.** Not `border-solid` beside it,
 * which is the shorthand and would give the other three sides a style with no
 * width — falling back to the browser's `medium` and drawing a box where one
 * edge was asked for. Not `border-0 border-l-2` either: that is the *other*
 * entry in CLAUDE.md's border section, two width utilities whose winner is
 * decided by the built stylesheet's sort order rather than by this file. A
 * directional width alone resolves to solid in this build and draws, which was
 * verified against the built stylesheet rather than reasoned.
 *
 * **The `default` layer draws no bar at all**, rather than a transparent one:
 * most rows on a fresh page are defaults, and twenty-five faint vertical lines
 * saying "nothing to see" is noise that makes the three that mean something
 * harder to find.
 */
export const SettingRow = ({
  spec,
  resolved,
  fallback,
  scope,
  scopeId,
  chain,
  below,
}: {
  spec: SettingSpec
  resolved: ResolvedSetting
  /** The same key from the resolution taken with this scope *omitted*. This is
   *  where the fallback line comes from, and the whole reason it is a second
   *  request rather than the schema's `default`: the default is wrong whenever
   *  a user, tenant or environment layer sits in between — which is the case
   *  the feature exists for — and it is `null` for every secret, always, so it
   *  cannot answer the one field where "what happens if I clear this" is
   *  frightening. */
  fallback: ResolvedSetting | undefined
  scope: Scope
  scopeId: string
  chain: readonly ScopeRef[]
  below: readonly ScopeRef[]
}) => {
  const canEdit = useCanEdit()
  const editable = canEdit(spec.key)
  const overridden = isOverriddenAt(resolved, scope, scopeId)

  const { save, clear, busy, outcome, resetOutcome } = useSettingCommit({
    scope,
    scopeId,
    chain,
    below,
  })

  const [draft, setDraft] = useState(() => displayValue(resolved))
  /** `null` when the masked display is showing, a string while replacing. See
   *  `SecretField` — the two are different states and `''` cannot tell them
   *  apart. */
  const [secretDraft, setSecretDraft] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)

  const serverValue = displayValue(resolved)
  /** The server value the draft was last seeded from, so a change can be
   *  detected without an effect. */
  const [seededFrom, setSeededFrom] = useState(serverValue)

  // Re-seed the draft when the server's answer moves under it -- a refetch
  // after somebody else's write, or this row's own successful clear falling
  // back to another layer.
  //
  // Adjusted during render rather than in an effect, which is React's own
  // documented shape for "state derived from a prop that changed" and the one
  // `react-hooks/set-state-in-effect` allows: a setState during the render of
  // the *same* component re-runs this component before anything is painted, so
  // there is no flash of the stale value and no cascading render of the tree.
  //
  // Not for secrets: `serverValue` is `''` for every secret at every moment,
  // so this would fire on nothing, and re-seeding a credential draft is the
  // one thing `SecretField` must never do.
  if (!spec.secret && seededFrom !== serverValue) {
    setSeededFrom(serverValue)
    setDraft(serverValue)
  }

  // Only a *typed* secret counts as unsaved. An open-but-empty Replace box has
  // nothing in it to lose, and prompting on it would make the guard routine —
  // which is how a prompt stops being read.
  useMarkUnsaved(spec.key, spec.secret && secretDraft !== null && secretDraft !== '')

  const controlId = useId()
  const helpId = useId()
  const outcomeId = useId()

  const commit = (value: string) => {
    // Nothing to do if the value is already what this scope resolved to *and*
    // this scope is what set it. The second half matters: on an inherited row
    // the draft equals the inherited value, and a blur that skipped the write
    // would silently refuse to create the override -- which is the one
    // interaction the live-not-locked control exists for.
    if (value === serverValue && overridden) return
    save(spec.key, value)
  }

  const commitSecret = (value: string) => {
    save(spec.key, value)
    // The draft is deliberately *not* cleared here. On success the outcome
    // transition below returns the field to its masked display; on failure the
    // paste survives, which is the whole point.
  }

  // A saved secret returns to its masked display, and only on the *transition*
  // into `saved` -- so pressing Replace again afterwards does not immediately
  // snap shut, which is what watching the value rather than the edge would do.
  // Adjusted during render for the reason above.
  const [seenOutcome, setSeenOutcome] = useState(outcome.kind)
  if (seenOutcome !== outcome.kind) {
    setSeenOutcome(outcome.kind)
    if (outcome.kind === 'saved' && spec.secret) setSecretDraft(null)
  }

  const help = [spec.description, spec.requiredWhen].filter(Boolean).join(' ')

  return (
    <div
      // `pl-3` rather than `pl-0` on the unbarred case, so a default row's text
      // lines up with an overridden one's. A bar that shifts the content two
      // pixels when it appears would make every commit look like a reflow.
      className={clsx(
        'flex flex-col gap-1 py-3 pl-3',
        overridden && 'border-l-2 border-accent',
        !overridden && resolved.layer !== 'default' && 'border-l-2 border-line-strong',
      )}
      data-testid={`setting-${spec.key}`}
      data-layer={resolved.layer}
    >
      <div className="flex flex-wrap items-baseline gap-2">
        <label className="text-md text-fg" htmlFor={controlId}>
          {spec.label}
        </label>
        {/* The env var, always visible rather than on hover. It is how
            operators arrive at this page and it is what they will paste back
            into a compose file; a `title` would put it where only a mouse can
            reach it, which is the defect `Chip`'s docstring records. */}
        <code className="font-mono text-xs text-fg-faint">{spec.envVar}</code>
      </div>

      {help ? (
        <p className="m-0 text-sm text-fg-dim" id={helpId}>
          {help}
        </p>
      ) : null}

      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-56 flex-1">
          {spec.secret ? (
            <SecretField
              spec={spec}
              resolved={resolved}
              draft={secretDraft}
              onDraftChange={(next) => {
                setSecretDraft(next)
                resetOutcome()
              }}
              onCommit={commitSecret}
              onClear={() => setConfirming(true)}
              canEdit={editable}
              busy={busy}
              describedBy={help ? helpId : undefined}
              id={controlId}
            />
          ) : editable ? (
            <SettingControl
              spec={spec}
              value={draft}
              onChange={setDraft}
              onCommit={commit}
              disabled={busy}
              describedBy={help ? helpId : undefined}
              id={controlId}
            />
          ) : (
            // A denied row renders *no control at all* rather than a disabled
            // one. That is what the permission test asserts -- the control is
            // absent from the tab order -- and it is a stronger claim than
            // `disabled`, which leaves an element in the tree that reads as
            // "you could change this, later".
            <p className="m-0 font-mono text-sm text-fg-dim" id={controlId}>
              {serverValue === '' ? 'not set' : serverValue}
            </p>
          )}
        </div>

        <LayerChip resolved={resolved} fallback={fallback} label={spec.label} />

        {/* Present only when this scope set it. `DELETE` answers 404 when
            there is no override, deliberately -- clearing a key that was never
            set is almost always a misspelling -- and a button whose only
            possible outcome is that 404 should not be on screen. Secrets get
            their `Clear` from `SecretField` instead, beside `Replace`. */}
        {overridden && editable && !spec.secret ? (
          <Button small tone="quiet" disabled={busy} onClick={() => setConfirming(true)}>
            Clear
          </Button>
        ) : null}
      </div>

      {overridden ? <FallbackLine fallback={fallback} /> : null}

      {!editable ? <p className="m-0 text-sm text-fg-faint">{DENIED_COPY}</p> : null}

      {/* `role="alert"` on the refusal only. A save that worked needs no
          announcement -- the chip and the bar already changed, which is the
          feedback -- and announcing every keystroke's commit would make the
          page unusable with a screen reader on. */}
      {outcome.kind === 'refused' ? (
        <p className="m-0 text-sm text-k-failure" id={outcomeId} role="alert">
          {outcome.detail}
        </p>
      ) : null}
      {outcome.kind === 'nothing-to-clear' ? (
        <p className="m-0 text-sm text-fg-dim" role="alert">
          There was no override here to clear. The value already came from {resolved.layer}.
        </p>
      ) : null}

      {confirming ? (
        <Confirm
          heading={`Clear ${spec.label}?`}
          lines={confirmLines(spec, fallback)}
          confirmLabel="Clear"
          tone="danger"
          onConfirm={() => {
            setConfirming(false)
            setSecretDraft(null)
            clear(spec.key)
          }}
          onCancel={() => setConfirming(false)}
        />
      ) : null}
    </div>
  )
}

/** What clearing this row would reveal, and which layer would answer.
 *
 * Under an overridden row only. `undefined` -- the second resolution has not
 * arrived, or does not carry the key -- prints nothing rather than a guess: a
 * fallback line that is wrong is worse than one that is absent, because the
 * whole reason the line exists is that people do not trust the page about
 * this. */
const FallbackLine = ({ fallback }: { fallback: ResolvedSetting | undefined }) => {
  if (!fallback) return null
  const shown = fallback.secret
    ? (fallback.masked?.display ?? 'not set')
    : fallback.value === null
      ? 'not set'
      : String(fallback.value)
  return (
    <p className="m-0 text-xs text-fg-faint">
      clearing this falls back to <code className="font-mono">{shown}</code> ({fallback.layer})
    </p>
  )
}

/** "Clear" means *fall back*, and the confirm has to say to what.
 *
 * Naming the destination rather than asking "are you sure" is the whole value
 * of the second resolution reaching this far: "the project will use the
 * tenant's key (…9f21)" is a sentence somebody can act on, and "this cannot be
 * undone" is not. Where the fallback is nothing at all the confirm says so
 * instead, because clearing into nothing is the case worth a moment's pause —
 * for a credential it is the difference between changing a key and turning a
 * provider off. */
const confirmLines = (spec: SettingSpec, fallback: ResolvedSetting | undefined): string[] => {
  if (!fallback) {
    return [
      `This removes the override on ${spec.label} at this scope.`,
      'What it will fall back to is not known yet — the fallback lookup has not answered. Reload before clearing if that matters.',
    ]
  }
  const shown = fallback.secret
    ? (fallback.masked?.display ?? 'not set')
    : fallback.value === null
      ? 'not set'
      : String(fallback.value)
  const nothing = shown === 'not set'
  return [
    `This removes the override on ${spec.label} at this scope.`,
    nothing
      ? `Nothing below this scope holds a value, so ${spec.label} will be unset.`
      : `It will then use ${shown}, from ${fallback.layer}.`,
  ]
}

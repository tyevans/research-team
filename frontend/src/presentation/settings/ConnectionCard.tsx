import { useState } from 'react'

import type { ResolvedSetting } from '@domain/settings/layer.ts'
import {
  fillPlaceholders,
  isFilled,
  placeholdersIn,
  type ProbeResult,
  type Provider,
} from '@domain/settings/provider.ts'
import type { Scope, SettingSpec } from '@domain/settings/spec.ts'

import { Tooltip } from '../common/Tooltip.tsx'
import { Button, Chip } from '../common/primitives.tsx'
import { SecretField } from './SecretField.tsx'
import { TestOutcome } from './TestOutcome.tsx'
import { useCanEdit } from './permissions.ts'

/** One configured provider: what it is, what it needs, and whether it answers.
 *
 * **`Test` is not validation; it is how the model picker gets filled.** The
 * response carries up to twenty-five model names, and that is the argument for
 * giving the test a real button on a card rather than a row in a table — it is
 * the step that turns an empty picker into a list. Where no list comes back,
 * the model field falls back to free text with the outcome's own explanation
 * for why, rather than an empty menu that looks broken.
 *
 * **The key sent is the one currently typed, before saving.** Test-then-save
 * puts the common failure — a mistyped key — before storage rather than after
 * it. For an already-saved key the field is empty and the person re-pastes,
 * which the contract requires (there is no route that reads a secret back) and
 * which the help text states plainly rather than leaving as a surprise.
 */
export const ConnectionCard = ({
  provider,
  credentialSpecs,
  resolved,
  scope,
  onTest,
  testing,
  result,
  onSaveCredential,
  onClearCredential,
}: {
  provider: Provider
  /** The synthesised `provider_key.*` specs for this provider's credentials,
   *  keyed by credential name. From the schema, like everything else — the
   *  card does not construct a key, it looks one up, so the dynamic namespace
   *  stays the backend's business. */
  credentialSpecs: ReadonlyMap<string, SettingSpec>
  /** This scope's resolution for each of those keys, by credential name. */
  resolved: ReadonlyMap<string, ResolvedSetting>
  scope: Scope
  onTest: (credentials: { apiKey?: string; baseUrl?: string }) => void
  testing: boolean
  result: ProbeResult | undefined
  onSaveCredential: (settingKey: string, value: string) => void
  onClearCredential: (settingKey: string) => void
}) => {
  const canEdit = useCanEdit()
  const markers = placeholdersIn(provider.baseUrl)

  /** Typed credential values, by credential name. Secrets live here only
   *  between a paste and a save — the same rule `SecretField` enforces, one
   *  level up: nothing seeds this from the server, because the server has no
   *  route that would. */
  const [typed, setTyped] = useState<Record<string, string | null>>({})
  const [placeholders, setPlaceholders] = useState<Record<string, string>>({})

  const url = fillPlaceholders(provider.baseUrl, placeholders)
  const ready = isFilled(provider.baseUrl, placeholders)

  /** The credential the probe route means by `api_key`: the first required
   *  secret this provider declares. Bedrock declares three credentials and the
   *  card assumes none of that — it sends the one the route has a field for
   *  and lets the outcome explain the rest, rather than inventing a body
   *  shape the contract does not have. */
  const primary = provider.credentials.find(
    (credential) => credential.secret && credential.required,
  )
  const typedPrimary = primary ? (typed[primary.name] ?? '') : ''

  return (
    <section className="flex flex-col gap-3 rounded-[5px] border border-line p-3">
      <header className="flex flex-wrap items-baseline gap-2">
        <h3 className="m-0 text-md">{provider.displayName}</h3>
        <code className="font-mono text-xs text-fg-faint">{url}</code>
        <div className="flex flex-wrap gap-1">
          {provider.capabilities.map((capability) => (
            <Tooltip
              key={capability}
              // The contract is explicit that a catalogue cannot know whether a
              // given *model* has vision. Without this sentence a chip beside a
              // model name reads as a promise about that model, which is the
              // stronger claim and the wrong one.
              explanation={`${provider.displayName} offers ${capability}. This describes the provider, not any particular model — it is what decides whether a role is worth offering here at all.`}
            >
              <Chip>{capability}</Chip>
            </Tooltip>
          ))}
        </div>
      </header>

      {provider.notes ? <p className="m-0 text-sm text-fg-dim">{provider.notes}</p> : null}

      {/* One field per `{placeholder}`, parsed out of the base url rather than
          read from a second list of which providers have which — Azure and
          Bedrock only today, and a list would drift the first time one moved. */}
      {markers.length > 0 ? (
        <div className="flex flex-col gap-2">
          {markers.map((marker) => (
            <label key={marker} className="flex flex-wrap items-center gap-2 text-sm">
              <span className="min-w-24 font-mono text-xs text-fg-dim">{marker}</span>
              <input
                className="input min-w-48 flex-1"
                value={placeholders[marker] ?? ''}
                // Not a secret: the contract declares these `secret=false`
                // precisely so a region or a deployment name is readable.
                // Masking them would make this card useless for the two
                // providers that need it most.
                onChange={(event) =>
                  setPlaceholders((previous) => ({ ...previous, [marker]: event.target.value }))
                }
                disabled={!canEdit(provider.id)}
              />
            </label>
          ))}
        </div>
      ) : null}

      <div className="flex flex-col gap-2">
        {provider.credentials.map((credential) => {
          const spec = credentialSpecs.get(credential.name)
          const row = resolved.get(credential.name)
          if (!spec || !row) {
            // The schema did not carry a spec for this credential. Said out
            // loud rather than skipped: a silently missing field is
            // indistinguishable from a provider that needs nothing, and this
            // is the seam where the catalogue and the dynamic namespace have to
            // agree.
            return (
              <p key={credential.name} className="m-0 text-sm text-k-failure">
                {credential.label} has no setting in this build’s schema ({provider.id}.
                {credential.name}).
              </p>
            )
          }
          return (
            <div key={credential.name} className="flex flex-col gap-1">
              <span className="text-sm text-fg-dim">
                {credential.label}
                {credential.required ? '' : ' (optional)'}
              </span>
              <SecretField
                spec={spec}
                resolved={row}
                draft={typed[credential.name] ?? (row.masked?.present ? null : '')}
                onDraftChange={(next) =>
                  setTyped((previous) => ({ ...previous, [credential.name]: next }))
                }
                onCommit={(value) => onSaveCredential(spec.key, value)}
                onClear={() => onClearCredential(spec.key)}
                canEdit={canEdit(spec.key)}
                busy={testing}
                describedBy={undefined}
                id={`${provider.id}-${credential.name}`}
              />
            </div>
          )
        })}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button
          tone="accent"
          small
          // Disabled until every placeholder is filled. An unfilled url answers
          // `unsupported` anyway, so this is the honest second line of defence
          // rather than the only one -- but a button that can only fail is
          // still a button worth not offering.
          disabled={!ready || testing || !canEdit(provider.id)}
          // Spread rather than a literal with `undefined` in it:
          // `exactOptionalPropertyTypes` makes "absent" and "present and
          // undefined" different types, and the route means different things by
          // them -- no `api_key` is "test what you can without one", which is
          // how a provider needing no auth is tested at all.
          onClick={() =>
            onTest({ ...(typedPrimary ? { apiKey: typedPrimary } : {}), baseUrl: url })
          }
        >
          {testing ? 'Testing…' : 'Test'}
        </Button>
        <span className="text-xs text-fg-faint">
          {primary && (resolved.get(primary.name)?.masked?.present ?? false) && !typedPrimary
            ? 'A saved key cannot be read back, so testing one means pasting it again.'
            : 'The key is sent once for this test and is not stored by it.'}
        </span>
      </div>

      {result ? <TestOutcome result={result} /> : null}
      {/* Stated on the card rather than only in a design document: which scope
          a credential typed here lands in. The card is reachable from three
          scopes and looks identical on all of them. */}
      <p className="m-0 text-xs text-fg-faint">Credentials save at {scope} scope.</p>
    </section>
  )
}

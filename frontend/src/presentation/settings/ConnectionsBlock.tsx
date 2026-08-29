import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import type { ResolvedSetting, ScopeRef } from '@domain/settings/layer.ts'
import type { ProbeResult, Provider } from '@domain/settings/provider.ts'
import type { Scope, SettingSpec, SettingsSchema } from '@domain/settings/spec.ts'

import { EmptyState } from '../common/primitives.tsx'
import { ConnectionCard } from './ConnectionCard.tsx'
import { useSettingCommit } from './use-setting-commit.ts'

/** The providers this scope has configured, plus a picker over the rest.
 *
 * **A provider is "configured" when a credential for it is stored**, which is
 * read off the resolution rather than kept as a separate list. There is no
 * "connections" table and there should not be one: a second record of which
 * providers you use would immediately disagree with which providers have keys,
 * and the key is the thing that decides whether the connection works.
 *
 * The consequence, worth stating because it is not obvious: a provider needing
 * no credential at all can never be "configured" by that rule, so it is
 * offered from the picker every time. That is honest — there is nothing to
 * store for it — and it is why the picker is a full list rather than a list of
 * what is left.
 */
export const ConnectionsBlock = ({
  providers,
  schema,
  resolved,
  scope,
  scopeId,
  chain,
  below,
}: {
  providers: readonly Provider[]
  schema: SettingsSchema
  resolved: ReadonlyMap<string, ResolvedSetting>
  scope: Scope
  scopeId: string
  chain: readonly ScopeRef[]
  below: readonly ScopeRef[]
}) => {
  const { providers: catalogue } = useContainer()
  const client = useQueryClient()
  const commit = useSettingCommit({ scope, scopeId, chain, below })

  const [opened, setOpened] = useState<readonly string[]>([])
  const [results, setResults] = useState<Record<string, ProbeResult>>({})

  /** Every spec in the schema, by key. The dynamic `provider_key.*` specs are
   *  in here because the schema route now lists them beside the static
   *  declarations — so the card looks a key up rather than building one, and
   *  the naming convention stays entirely on the backend. */
  const specs = new Map<string, SettingSpec>(
    schema.groups.flatMap((group) => group.settings.map((spec) => [spec.key, spec])),
  )

  const specsFor = (provider: Provider) => {
    const found = new Map<string, SettingSpec>()
    for (const credential of provider.credentials) {
      // `settingKey` when the catalogue names a static one, otherwise the
      // dynamic key. Both are looked up in the schema; neither is constructed
      // by string-building here, which is what would rot when the namespace
      // changes shape.
      const candidates = [
        credential.settingKey,
        `provider_key.${provider.id}.${credential.name}`,
        `provider_key.${provider.id}`,
      ].filter((key): key is string => key !== null)
      const key = candidates.find((candidate) => specs.has(candidate))
      const spec = key === undefined ? undefined : specs.get(key)
      if (spec) found.set(credential.name, spec)
    }
    return found
  }

  const resolvedFor = (credentialSpecs: ReadonlyMap<string, SettingSpec>) => {
    const found = new Map<string, ResolvedSetting>()
    for (const [name, spec] of credentialSpecs) {
      const row = resolved.get(spec.key)
      if (row) found.set(name, row)
    }
    return found
  }

  const isConfigured = (provider: Provider) => {
    const credentialSpecs = specsFor(provider)
    return [...credentialSpecs.values()].some(
      (spec) => resolved.get(spec.key)?.masked?.present ?? false,
    )
  }

  const probe = useMutation({
    mutationFn: ({
      providerId,
      credentials,
    }: {
      providerId: string
      credentials: { apiKey?: string; baseUrl?: string }
    }) => catalogue.test(providerId, credentials),
    onSuccess: (result) => setResults((previous) => ({ ...previous, [result.providerId]: result })),
    onError: (error, variables) =>
      // A failed *request* is rendered in the same place as a failed probe, as
      // `error` — which is the outcome the contract already has for "the test
      // itself failed, which is not the same as the provider refusing". One
      // surface rather than two for the same question.
      setResults((previous) => ({
        ...previous,
        [variables.providerId]: {
          providerId: variables.providerId,
          outcome: 'error',
          ok: false,
          detail: error instanceof Error ? error.message : String(error),
          models: [],
          latencyMs: null,
        },
      })),
  })

  const shown = providers.filter(
    (provider) => isConfigured(provider) || opened.includes(provider.id),
  )
  const rest = providers.filter((provider) => !shown.includes(provider))

  return (
    <section className="flex flex-col gap-3">
      <h2 className="m-0 text-md">Connections</h2>

      {shown.length === 0 ? (
        <EmptyState
          heading="No provider configured yet"
          detail="Connect a provider to choose models per role. Everything below still runs on this deployment’s own endpoint until you do."
        />
      ) : null}

      {shown.map((provider) => {
        const credentialSpecs = specsFor(provider)
        return (
          <ConnectionCard
            key={provider.id}
            provider={provider}
            credentialSpecs={credentialSpecs}
            resolved={resolvedFor(credentialSpecs)}
            scope={scope}
            testing={probe.isPending && probe.variables?.providerId === provider.id}
            result={results[provider.id]}
            onTest={(credentials) => probe.mutate({ providerId: provider.id, credentials })}
            onSaveCredential={(key, value) => {
              commit.save(key, value)
              void client.invalidateQueries({ queryKey: queryKeys.settings.all() })
            }}
            onClearCredential={(key) => commit.clear(key)}
          />
        )
      })}

      {rest.length > 0 ? (
        <label className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-fg-dim">Add connection</span>
          <select
            className="input"
            value=""
            aria-label="Add a provider connection"
            onChange={(event) => {
              const id = event.target.value
              if (id) setOpened((previous) => [...previous, id])
            }}
          >
            <option value="">choose a provider…</option>
            {rest.map((provider) => (
              <option key={provider.id} value={provider.id}>
                {provider.displayName}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {commit.outcome.kind === 'refused' ? (
        <p className="m-0 text-sm text-k-failure" role="alert">
          {commit.outcome.detail}
        </p>
      ) : null}
    </section>
  )
}

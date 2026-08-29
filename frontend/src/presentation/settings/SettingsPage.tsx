import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import { queryKeys } from '@application/queries/keys.ts'
import { byKey, isOverriddenAt, type ScopeRef } from '@domain/settings/layer.ts'
import {
  connectionForGroup,
  groupsForScope,
  specMatches,
  type Scope,
} from '@domain/settings/spec.ts'

import { Confirm } from '../common/Confirm.tsx'
import { Disclosure, EmptyState, ErrorBox, Loading } from '../common/primitives.tsx'
import { ConnectionTest } from './ConnectionTest.tsx'
import { GroupRail } from './GroupRail.tsx'
import { SettingRow } from './SettingRow.tsx'
import { SCOPE_COPY } from './scope-copy.ts'
import { UnsavedSecretsProvider, useUnsavedGuard, useUnsavedSecrets } from './use-unsaved-guard.ts'

/** One scope's settings.
 *
 * **The page makes three requests and two of them are the same route.**
 * `schema` is static and cached forever. `resolved` is asked twice: once for
 * the chain this page edits, and once with *this scope omitted*, which is the
 * only correct answer to "what would this fall back to if I cleared the
 * override". Reading the schema's `default` instead is free and wrong — wrong
 * whenever a user, tenant or environment layer sits in between, which is the
 * case the feature exists for, and `null` for every secret by contract, so it
 * cannot answer the one field where the question is frightening.
 *
 * **Parametrised by scope, and only `project` is reachable today.** The three
 * places a scope actually matters are all values rather than components: which
 * settings render (`spec.scopes`), how deep the chain below is (derived from
 * `RESOLUTION_ORDER`), and the copy (`SCOPE_COPY`). Nothing branches, which is
 * what makes S5 a routing change rather than a second page.
 *
 * **Schema fine, resolved failing renders the page disabled with the error,
 * never an empty page.** This is CLAUDE.md's read-model trap arriving as a UI
 * question, and it will happen the first time a column is added against an
 * existing database. An empty settings page reads as "this project has no
 * settings", which is a wrong answer rather than an absent one.
 */
export const SettingsPage = ({ scope, scopeId, group }: SettingsPageProps) => {
  const unsaved = useUnsavedSecrets()
  return (
    <UnsavedSecretsProvider value={unsaved}>
      <SettingsBody
        scope={scope}
        scopeId={scopeId}
        group={group}
        dirtyCount={unsaved.dirty.length}
      />
    </UnsavedSecretsProvider>
  )
}

export interface SettingsPageProps {
  scope: Scope
  scopeId: string
  /** A group to open on landing, from the route. `null` opens the default
   *  set — the first two, per the design's "collapsed groups, not an advanced
   *  tier". */
  group: string | null
}

const SettingsBody = ({
  scope,
  scopeId,
  group,
  dirtyCount,
}: SettingsPageProps & { dirtyCount: number }) => {
  const { settings } = useContainer()
  const [search, setSearch] = useState('')
  const [onlyOverridden, setOnlyOverridden] = useState(false)
  const [opened, setOpened] = useState<ReadonlySet<string>>(() => new Set(group ? [group] : []))

  /** What this page's requests name. One entry, and that is a fact about
   *  today rather than a simplification: the console has no identity endpoint,
   *  so a project page cannot learn which user or tenant sits under it. When
   *  W-A supplies them this becomes the fuller chain and nothing else here
   *  changes. */
  const chain: readonly ScopeRef[] = useMemo(() => [{ scope, scopeId }], [scope, scopeId])

  /** The same route with *this* scope omitted -- where the fallback line comes
   *  from. Derived from `chain` rather than written as `[]`, which it happens
   *  to equal today for every scope because `chain` holds one entry. Written
   *  as a filter so that the day `chain` grows, this stays correct instead of
   *  silently resolving the wrong layer as the fallback. */
  const below: readonly ScopeRef[] = useMemo(
    () => chain.filter((ref) => ref.scope !== scope),
    [chain, scope],
  )

  const schema = useQuery({
    queryKey: queryKeys.settings.schema(),
    queryFn: () => settings.schema(),
    // Static: no scope, no credentials, answers on a build with nothing wired.
    staleTime: Infinity,
    retry: false,
  })

  const resolved = useQuery({
    queryKey: queryKeys.settings.resolved(chain),
    queryFn: () => settings.resolved(chain),
    retry: false,
  })

  const fallback = useQuery({
    queryKey: queryKeys.settings.resolved(below),
    queryFn: () => settings.resolved(below),
    retry: false,
  })

  const guard = useUnsavedGuard(dirtyCount)

  /** What each group's last connection test found, by group name.
   *
   * Held here rather than in `ConnectionTest` because the models are for the
   * *model row*, which is a sibling: the test knows them and the row needs
   * them, and the page is the nearest thing that holds both. Keyed by group so
   * one group's test cannot offer its models to another's endpoint.
   *
   * Deliberately not persisted or cached across a reload. A model list is a
   * statement about what an endpoint was serving a moment ago, and offering
   * yesterday's list as though it were current is the kind of stale
   * suggestion that sends somebody looking for a model that has since been
   * unloaded. */
  const [discovered, setDiscovered] = useState<ReadonlyMap<string, readonly string[]>>(new Map())

  const copy = SCOPE_COPY[scope]

  if (schema.isPending) return <Loading what="settings" />
  if (schema.isError || !schema.data) {
    return (
      <ErrorBox
        heading="The settings schema could not be read"
        message={String(schema.error)}
        onRetry={() => void schema.refetch()}
      />
    )
  }

  const groups = groupsForScope(schema.data, scope)
  const current = resolved.data ? byKey(resolved.data) : null
  const fallbacks = fallback.data ? byKey(fallback.data) : null

  const overrideCounts = new Map(
    groups.map((g) => [
      g.name,
      current
        ? g.settings.filter((spec) => {
            const row = current.get(spec.key)
            return row ? isOverriddenAt(row, scope, scopeId) : false
          }).length
        : 0,
    ]),
  )
  const overriddenTotal = [...overrideCounts.values()].reduce((a, b) => a + b, 0)

  const searching = search.trim() !== ''

  const visible = groups
    .map((g) => ({
      name: g.name,
      settings: g.settings.filter((spec) => {
        if (!specMatches(spec, search)) return false
        if (!onlyOverridden) return true
        const row = current?.get(spec.key)
        return row ? isOverriddenAt(row, scope, scopeId) : false
      }),
    }))
    .filter((g) => g.settings.length > 0)

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <header className="flex flex-col gap-2 border-b border-line px-5 py-3">
        <h1 className="m-0 text-lg">{copy.heading}</h1>
        <p className="m-0 text-sm text-fg-dim">{copy.blurb}</p>
        <div className="flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-2 text-sm text-fg-dim">
            Search
            <input
              className="input w-64"
              type="search"
              value={search}
              placeholder="label, key, or AGENT_… variable"
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          {/* A filter, not the page. A view showing only differences cannot
              answer "what is this project actually using", which is the more
              common question and the one somebody arrives with after a bad
              run — so it is a good second view and a bad first one. */}
          <label className="flex items-center gap-2 text-sm text-fg-dim">
            <input
              type="checkbox"
              checked={onlyOverridden}
              onChange={(event) => setOnlyOverridden(event.target.checked)}
            />
            Overridden here ({overriddenTotal})
          </label>
        </div>
      </header>

      {/* The resolution's own failure, above the form and with the form still
          drawn. `isError` rather than "no data": a page that renders nothing
          here says "this project has no settings", which is the wrong answer
          rather than the absent one. */}
      {resolved.isError ? (
        <div className="px-5 pt-3">
          <ErrorBox
            heading="This scope's values could not be resolved"
            message={`${String(resolved.error)} — the form below is disabled because the console does not know what any of these settings currently are.`}
            onRetry={() => void resolved.refetch()}
          />
        </div>
      ) : null}

      {/* A failure of the *second* resolution is smaller and says so: every
          value on the page is still true, and the one thing missing is what a
          clear would fall back to. Rendering it as the same red box as above
          would overstate it. */}
      {fallback.isError ? (
        <p className="px-5 pt-2 text-sm text-fg-dim" role="status">
          The fallback lookup failed, so rows cannot say what clearing them would reveal. Everything
          shown is still what this scope resolves to.
        </p>
      ) : null}

      <div className="grid flex-1 grid-cols-[10rem_1fr] gap-5 overflow-auto px-5">
        <GroupRail
          groups={groups.map((g) => g.name)}
          active={group}
          overrideCounts={overrideCounts}
          onSelect={(name) =>
            setOpened((previous) => {
              const next = new Set(previous)
              next.add(name)
              return next
            })
          }
        />

        <div className="pb-8 flex flex-col">
          {resolved.isPending ? <Loading what="this scope's values" /> : null}

          {visible.length === 0 && !resolved.isPending ? (
            <EmptyState
              heading="Nothing matches"
              detail={
                onlyOverridden && !searching
                  ? 'This scope has not overridden any setting. Turn off the filter to see what it is using.'
                  : 'No setting here matches that search — try the environment variable name.'
              }
            />
          ) : null}

          {visible.map((g, index) => {
            const connection = connectionForGroup(schema.data, g.name)
            return (
              <Disclosure
                key={g.name}
                label={
                  <span>
                    {g.name}
                    <span className="ml-2 font-mono text-xs text-fg-faint">
                      {g.settings.length}
                    </span>
                  </span>
                }
                // Open when asked for by name, when a search hit is in it, when
                // this scope overrode something in it, or when it is one of the
                // first two. The rest fold. Not an advanced/basic split: the
                // registry carries no such flag and inventing one here is exactly
                // the second hand-written description of forty settings that
                // `settings.py` exists to prevent. If a tier is wanted it is a
                // field on `SettingSpec`, where a test can hold it.
                open={
                  opened.has(g.name) ||
                  searching ||
                  (overrideCounts.get(g.name) ?? 0) > 0 ||
                  (group === null && index < 2)
                }
                onToggle={() =>
                  setOpened((previous) => {
                    const next = new Set(previous)
                    if (next.has(g.name)) next.delete(g.name)
                    else next.add(g.name)
                    return next
                  })
                }
              >
                <div className="flex flex-col">
                  {g.settings.map((spec) => {
                    const row = current?.get(spec.key)
                    if (!row) return null
                    return (
                      <SettingRow
                        key={spec.key}
                        spec={spec}
                        resolved={row}
                        fallback={fallbacks?.get(spec.key)}
                        scope={scope}
                        scopeId={scopeId}
                        chain={chain}
                        below={below}
                        // Only the model row, and only for this group's own
                        // connection: the endpoint and key rows have nothing to
                        // learn from a list of models, and another group's test
                        // says nothing about this one's endpoint.
                        suggestions={
                          connection !== null && spec.key === connection.modelKey
                            ? (discovered.get(g.name) ?? [])
                            : []
                        }
                      />
                    )
                  })}
                </div>
                {/* Below the rows rather than above them: the test is a question
                  about what the rows say, so it reads after them. */}
                {connection !== null ? (
                  <ConnectionTest
                    connection={connection}
                    resolved={current}
                    onModels={(models) =>
                      setDiscovered((previous) => new Map(previous).set(g.name, models))
                    }
                  />
                ) : null}
              </Disclosure>
            )
          })}
        </div>
      </div>

      {guard.pending !== null ? (
        <Confirm
          heading="Leave with an unsaved key?"
          lines={[
            dirtyCount === 1
              ? 'One credential field holds text that has not been saved.'
              : `${dirtyCount} credential fields hold text that has not been saved.`,
            'A pasted key cannot be recovered after you leave this page.',
          ]}
          confirmLabel="Leave anyway"
          tone="danger"
          onConfirm={guard.proceed}
          onCancel={guard.stay}
        />
      ) : null}
    </div>
  )
}

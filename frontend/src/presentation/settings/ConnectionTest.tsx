import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'

import { useContainer } from '@app/container-context.tsx'
import type { Connection, ProbeResult, Provider } from '@domain/settings/spec.ts'
import type { ResolvedSetting } from '@domain/settings/layer.ts'

/** Does this group's endpoint answer, and what does it serve?
 *
 * The question this exists for is the one the console could not answer at all:
 * a wrong `base_url` is not a worse answer, it is a refused connection, and
 * the only way to find out was to start a run and read the error out of a
 * failed turn. Everything here is a `GET /api/providers` and a
 * `POST /api/providers/{id}/test` that have both existed since the settings
 * feature shipped and that the console has never called.
 *
 * **The models it finds are the point, not a detail of the result.** A test
 * that says "reachable" and leaves you to type a model name from memory has
 * answered half the question -- the half that was already easy to guess. The
 * list comes back from the endpoint that will serve the request, moments
 * before it serves it, which is a better answer to "what can I put here" than
 * anything this console could hold. That is why the picker is fed from here
 * rather than being a feature of its own.
 *
 * **It reads the endpoint this group is configured with, not the catalogue's.**
 * `base_url` comes from the resolved row, so the test dials what a run would
 * dial. A test against the provider's published URL would report the vendor
 * healthy while the endpoint actually configured was unreachable, which is a
 * more confusing answer than no test at all.
 */
export const ConnectionTest = ({
  connection,
  resolved,
  onModels,
}: {
  connection: Connection
  /** This scope's resolved rows, keyed as `SettingsPage` holds them. The
   *  endpoint is read from here rather than passed as a string so that a row
   *  inherited from the tenant tests the value it inherited. */
  resolved: ReadonlyMap<string, ResolvedSetting> | null
  /** What the endpoint listed, handed up so the model row can offer it. Called
   *  with an empty list on a failed test, which clears a previous run's
   *  suggestions -- offering the models of an endpoint that has since stopped
   *  answering is worse than offering none. */
  onModels: (models: readonly string[]) => void
}) => {
  const { settings } = useContainer()
  const providers = useQuery({
    queryKey: ['providers'],
    queryFn: () => settings.providers(),
    // Static and credential-free, exactly like the schema, so it is cached for
    // the session rather than refetched per group.
    staleTime: Infinity,
  })

  const configuredUrl = asText(resolved?.get(connection.baseUrlKey)?.value)
  const catalogue = providers.data ?? []
  const [chosen, setChosen] = useState<string | null>(null)
  const [key, setKey] = useState('')

  const providerId = chosen ?? defaultProvider(catalogue, configuredUrl)
  const provider = catalogue.find((p) => p.id === providerId) ?? null

  const probe = useMutation<ProbeResult>({
    mutationFn: () =>
      settings.testProvider(providerId, {
        // `null` rather than `''`: the route reads `null` as "use the
        // catalogue's own", which is a real thing to ask for on a scope that
        // has overridden nothing.
        apiKey: key === '' ? null : key,
        baseUrl: configuredUrl === '' ? null : configuredUrl,
      }),
    onSuccess: (result) => onModels(result.ok ? result.models : []),
    // A failed *request* is not a failed test -- a 404 for an unknown provider
    // or a 503 for a build with no probe says nothing about the endpoint -- so
    // the suggestions are cleared rather than left standing from a previous
    // run that may no longer be true.
    onError: () => onModels([]),
  })

  if (catalogue.length === 0) return null

  return (
    <div className="flex flex-col gap-2 px-5 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <label className="text-xs text-fg-dim" htmlFor={`probe-provider-${connection.group}`}>
          Test as
        </label>
        <select
          id={`probe-provider-${connection.group}`}
          className="input"
          value={providerId}
          onChange={(event) => setChosen(event.target.value)}
        >
          {catalogue.map((entry) => (
            <option key={entry.id} value={entry.id}>
              {entry.displayName}
            </option>
          ))}
        </select>

        {/* Only where a credential would be used. The three local providers
            are `auth: none`, and an always-present key field on those reads as
            "you have not finished configuring this" for the deployments most
            likely to be someone's first. */}
        {provider !== null && provider.auth !== 'none' ? (
          <input
            className="input"
            type="password"
            value={key}
            placeholder="API key for this test"
            aria-label="API key for this test"
            onChange={(event) => setKey(event.target.value)}
          />
        ) : null}

        <button
          type="button"
          className="btn btn-sm"
          disabled={probe.isPending}
          onClick={() => probe.mutate()}
        >
          {probe.isPending ? 'Testing…' : 'Test connection'}
        </button>
      </div>

      {/* `role="status"` rather than `alert`: this is the answer to something
          the reader just pressed, and it is announced without stealing focus
          from the button they are still on. */}
      <p className="font-mono text-xs" role="status">
        {describe(probe.isPending, probe.data ?? null, probe.error, configuredUrl)}
      </p>
    </div>
  )
}

/** What the reader is told, in one line.
 *
 * The endpoint is named in every outcome including success, because the
 * failure this feature exists for is a test that passes against somewhere
 * other than where the work will go -- and a reader who can see the URL can
 * catch that themselves.
 */
const describe = (
  pending: boolean,
  result: ProbeResult | null,
  error: unknown,
  url: string,
): string => {
  const where = url === '' ? "the provider's own endpoint" : url
  if (pending) return `Asking ${where}…`
  if (error) return `Could not run the test: ${error instanceof Error ? error.message : 'failed'}`
  if (result === null) return `Not tested. This would dial ${where}.`

  const latency = result.latencyMs === null ? '' : ` · ${Math.round(result.latencyMs)}ms`
  if (!result.ok) {
    // The outcome word is the server's and is printed verbatim: "unauthorized"
    // and "unreachable" want different next steps, and flattening them into
    // "failed" is exactly the distinction the route split them for.
    return `${result.outcome}${latency} · ${result.detail ?? `${where} did not answer`}`
  }
  const models =
    result.models.length === 0
      ? 'listed no models'
      : `${result.models.length} model${result.models.length === 1 ? '' : 's'}`
  return `ok${latency} · ${where} · ${models}`
}

/** Which provider to test as, before anybody chooses.
 *
 * Matched on the configured endpoint first, so a deployment pointing at
 * Ollama's or LM Studio's default port is recognised without a click. Falls
 * back to vLLM, whose own catalogue note says it is "the shape this project's
 * own default endpoint already has" -- a guess, but the one that is right for
 * the local OpenAI-compatible server this project is usually run against, and
 * one the reader can override in the control beside it.
 */
const defaultProvider = (catalogue: readonly Provider[], url: string): string => {
  const match = catalogue.find((entry) => entry.baseUrl !== '' && entry.baseUrl === url)
  if (match) return match.id
  const vllm = catalogue.find((entry) => entry.id === 'vllm')
  return vllm?.id ?? catalogue[0]?.id ?? 'vllm'
}

/** A resolved value as the string a URL field holds. Numbers and booleans
 *  cannot be endpoints, and `null` is "nothing resolved", so both become the
 *  empty string that means "use the catalogue's". */
const asText = (value: string | number | boolean | null | undefined): string =>
  typeof value === 'string' ? value : ''

import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { expect, it, vi } from 'vitest'

import { ContainerProvider } from '@app/container-context.tsx'
import type { SettingsRepository } from '@application/ports/repositories.ts'
import type { ResolvedSettings, ScopeRef } from '@domain/settings/layer.ts'
import type { Provider, SettingsSchema } from '@domain/settings/spec.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { SettingsPage } from './SettingsPage.tsx'

import { buildContainer } from '../../test/container.ts'

/** The connection test, over the page that renders it.
 *
 * Written against `SettingsPage` rather than `ConnectionTest` alone, and the
 * reason is the defect this whole branch descends from: the backend for this
 * feature -- `GET /api/providers`, `POST /api/providers/{id}/test` -- has
 * existed since the settings feature shipped and the console called neither.
 * A test that mounted `ConnectionTest` directly would prove the component
 * works and could not prove the page renders it, which is precisely the half
 * that was missing before.
 *
 * `providers` and `testProvider` are driven off the port. The probe result is
 * the route's real shape; the assertions are on what a reader is told and on
 * what the model row then offers.
 */

const spec = (over: Partial<SettingsSchema['groups'][number]['settings'][number]> = {}) => ({
  key: 'model',
  envVar: 'AGENT_MODEL',
  type: 'string' as const,
  label: 'Chat model',
  description: '',
  group: 'Models',
  secret: false,
  default: 'qwen',
  choices: [],
  minimum: null,
  maximum: null,
  requiredWhen: null,
  scopes: ['project', 'user', 'tenant'] as const,
  ...over,
})

const SCHEMA: SettingsSchema = {
  groups: [
    {
      name: 'Models',
      settings: [
        spec(),
        spec({ key: 'base_url', envVar: 'AGENT_BASE_URL', label: 'Base URL', default: '' }),
      ],
    },
  ],
  scopes: ['project', 'user', 'tenant'],
  roles: [{ role: 'research', settingKey: 'model' }],
  connections: [
    {
      role: 'research',
      group: 'Models',
      modelKey: 'model',
      baseUrlKey: 'base_url',
      apiKeyKey: 'api_key',
    },
  ],
}

const row = (key: string, value: string) => ({
  key,
  value,
  layer: 'project' as const,
  scopeId: 'p1',
  secret: false,
  masked: null,
})

const RESOLVED: ResolvedSettings = {
  scopeChain: [{ scope: 'project', scopeId: 'p1' }],
  settings: [row('model', 'qwen'), row('base_url', 'http://192.168.1.14:8080/v1/')],
}

const VLLM: Provider = {
  id: 'vllm',
  displayName: 'vLLM',
  baseUrl: 'http://localhost:8000/v1/',
  auth: 'none',
  openaiCompatible: true,
  notes: '',
}

const ANTHROPIC: Provider = {
  id: 'anthropic',
  displayName: 'Anthropic',
  baseUrl: 'https://api.anthropic.com/v1/',
  auth: 'bearer',
  openaiCompatible: false,
  notes: '',
}

const ok = {
  providerId: 'vllm',
  outcome: 'ok',
  ok: true,
  detail: null,
  models: ['qwen3.6-27b-mtp', 'nomic-embed-text'],
  latencyMs: 142,
}

const repository = (over: Partial<SettingsRepository> = {}): SettingsRepository => ({
  schema: vi.fn().mockResolvedValue(SCHEMA),
  resolved: vi.fn((chain: readonly ScopeRef[]) =>
    Promise.resolve(chain.length === 0 ? { scopeChain: [], settings: [] } : RESOLVED),
  ),
  put: vi.fn().mockResolvedValue(undefined),
  clear: vi.fn().mockResolvedValue(true),
  providers: vi.fn().mockResolvedValue([VLLM, ANTHROPIC]),
  testProvider: vi.fn().mockResolvedValue(ok),
  ...over,
})

const draw = (settings: SettingsRepository) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={buildContainer({ settings })}>
        <OverlayHost>
          <SettingsPage scope="project" scopeId="p1" group={null} />
        </OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>,
  )
}

it('offers a test on a group the schema says has a connection', async () => {
  draw(repository())

  expect(await screen.findByRole('button', { name: 'Test connection' })).toBeInTheDocument()
})

it('offers no test on a group the schema gives no connection', async () => {
  /** The whole mapping is the server's. A console that decided for itself
   *  which groups were testable would be a second copy of the registry, which
   *  is what `domain/settings/spec.ts` exists to prevent. */
  draw(repository({ schema: vi.fn().mockResolvedValue({ ...SCHEMA, connections: [] }) }))

  await screen.findByText('Chat model')
  expect(screen.queryByRole('button', { name: 'Test connection' })).not.toBeInTheDocument()
})

it('dials the endpoint this scope resolved, not the catalogue default', async () => {
  /** The failure this guards is a test that passes against somewhere other
   *  than where the work goes: reporting vLLM's published localhost:8000
   *  healthy while the configured 192.168.1.14 was unreachable is a more
   *  confusing answer than no test at all. */
  const testProvider = vi.fn().mockResolvedValue(ok)
  draw(repository({ testProvider }))

  await userEvent.click(await screen.findByRole('button', { name: 'Test connection' }))

  await waitFor(() =>
    expect(testProvider).toHaveBeenCalledWith('vllm', {
      apiKey: null,
      baseUrl: 'http://192.168.1.14:8080/v1/',
    }),
  )
})

it('tells the reader the outcome, the latency and where it went', async () => {
  draw(repository())

  await userEvent.click(await screen.findByRole('button', { name: 'Test connection' }))

  const status = await screen.findByText(/ok/)
  expect(status).toHaveTextContent('142ms')
  expect(status).toHaveTextContent('http://192.168.1.14:8080/v1/')
  expect(status).toHaveTextContent('2 models')
})

it('reports a refusal in the words the route used, not as a generic failure', async () => {
  /** `unauthorized` and `unreachable` want different next steps from the
   *  person reading them, which is why the route returns four outcomes rather
   *  than a boolean. Flattening them here would throw that away at the last
   *  step. */
  draw(
    repository({
      testProvider: vi.fn().mockResolvedValue({
        providerId: 'vllm',
        outcome: 'unreachable',
        ok: false,
        detail: 'connection refused',
        models: [],
        latencyMs: null,
      }),
    }),
  )

  await userEvent.click(await screen.findByRole('button', { name: 'Test connection' }))

  const status = await screen.findByText(/unreachable/)
  expect(status).toHaveTextContent('connection refused')
})

it('offers the models it found on the model row, and only there', async () => {
  draw(repository())
  await userEvent.click(await screen.findByRole('button', { name: 'Test connection' }))

  await waitFor(() => {
    const model = screen.getByLabelText('Chat model')
    expect(model.getAttribute('list')).toBeTruthy()
  })

  const model = screen.getByLabelText('Chat model')
  const list = document.getElementById(model.getAttribute('list')!)
  expect(list?.querySelectorAll('option')).toHaveLength(2)
  expect(list?.textContent ?? '').toBe('')
  expect([...(list?.querySelectorAll('option') ?? [])].map((o) => o.getAttribute('value'))).toEqual(
    ['qwen3.6-27b-mtp', 'nomic-embed-text'],
  )

  // The endpoint row is text too, and a build that offered model names there
  // would be suggesting a model as a URL.
  const url = screen.getByLabelText('Base URL')
  expect(url.getAttribute('list')).toBeNull()
})

it('offers nothing before a test has been run', async () => {
  /** A datalist standing empty is not the same as absent, but a *stale* one is
   *  worse than either: suggesting models from an endpoint that has since
   *  stopped answering sends somebody looking for something that is not
   *  there. */
  draw(repository())

  const model = await screen.findByLabelText('Chat model')
  expect(model.getAttribute('list')).toBeNull()
})

it('clears the suggestions when a later test fails', async () => {
  const testProvider = vi.fn().mockResolvedValueOnce(ok).mockResolvedValueOnce({
    providerId: 'vllm',
    outcome: 'unreachable',
    ok: false,
    detail: 'connection refused',
    models: [],
    latencyMs: null,
  })
  draw(repository({ testProvider }))

  const button = await screen.findByRole('button', { name: 'Test connection' })
  await userEvent.click(button)
  await waitFor(() => expect(screen.getByLabelText('Chat model').getAttribute('list')).toBeTruthy())

  await userEvent.click(button)

  await waitFor(() => expect(screen.getByLabelText('Chat model').getAttribute('list')).toBeNull())
})

it('asks for a key only where a credential would be used', async () => {
  /** The three local providers are `auth: none`, and an always-present key
   *  field on those reads as "you have not finished configuring this" for the
   *  deployments most likely to be somebody's first. */
  draw(repository())

  await screen.findByRole('button', { name: 'Test connection' })
  expect(screen.queryByLabelText('API key for this test')).not.toBeInTheDocument()

  await userEvent.selectOptions(screen.getByLabelText('Test as'), 'anthropic')

  expect(screen.getByLabelText('API key for this test')).toBeInTheDocument()
})

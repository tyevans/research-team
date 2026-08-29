import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ContainerProvider } from '@app/container-context.tsx'
import { ApiError } from '@application/ports/errors.ts'
import type { SettingsRepository } from '@application/ports/repositories.ts'
import type { ResolvedSettings, ScopeRef } from '@domain/settings/layer.ts'
import type { SettingsSchema } from '@domain/settings/spec.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { SettingsPage } from './SettingsPage.tsx'

import { buildContainer } from '../../test/container.ts'

const SCHEMA: SettingsSchema = {
  groups: [
    {
      name: 'Models',
      settings: [
        {
          key: 'model',
          envVar: 'AGENT_MODEL',
          type: 'string',
          label: 'Chat model',
          description: '',
          group: 'Models',
          secret: false,
          default: 'qwen',
          choices: [],
          minimum: null,
          maximum: null,
          requiredWhen: null,
          scopes: ['project', 'user', 'tenant'],
        },
      ],
    },
    {
      name: 'Extraction',
      settings: [
        {
          key: 'extraction_chunk_size',
          envVar: 'AGENT_EXTRACTION_CHUNK_SIZE',
          type: 'integer',
          label: 'Chunk size',
          description: '',
          group: 'Extraction',
          secret: false,
          default: 2000,
          choices: [],
          minimum: 200,
          maximum: 8000,
          requiredWhen: null,
          scopes: ['project', 'user', 'tenant'],
        },
      ],
    },
    {
      name: 'Stores',
      settings: [
        {
          key: 'pgvector_dsn',
          envVar: 'AGENT_PGVECTOR_DSN',
          type: 'string',
          label: 'pgvector DSN',
          description: '',
          group: 'Stores',
          secret: true,
          default: null,
          choices: [],
          minimum: null,
          maximum: null,
          requiredWhen: null,
          // Tenant-only. A project override would point every project's
          // vectors at another database, which is why the declaration refuses
          // it and why this group must not render on a project page at all.
          scopes: ['tenant'],
        },
      ],
    },
  ],
  scopes: ['project', 'user', 'tenant'],
  roles: [{ role: 'research', settingKey: 'model' }],
  connections: [],
}

const RESOLVED: ResolvedSettings = {
  scopeChain: [{ scope: 'project', scopeId: 'p1' }],
  settings: [
    { key: 'model', value: 'mine', layer: 'project', scopeId: 'p1', secret: false, masked: null },
    {
      key: 'extraction_chunk_size',
      value: 2000,
      layer: 'default',
      scopeId: null,
      secret: false,
      masked: null,
    },
  ],
}

const FALLBACK: ResolvedSettings = {
  scopeChain: [],
  settings: [
    { key: 'model', value: 'qwen', layer: 'default', scopeId: null, secret: false, masked: null },
  ],
}

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

const repository = (over: Partial<SettingsRepository> = {}): SettingsRepository => ({
  schema: vi.fn().mockResolvedValue(SCHEMA),
  resolved: vi.fn((chain: readonly ScopeRef[]) =>
    Promise.resolve(chain.length === 0 ? FALLBACK : RESOLVED),
  ),
  put: vi.fn().mockResolvedValue(undefined),
  clear: vi.fn().mockResolvedValue(true),
  providers: vi.fn().mockResolvedValue([]),
  testProvider: vi.fn(),
  ...over,
})

describe('the page', () => {
  it('resolves twice: once for this scope, and once with this scope omitted', async () => {
    const resolved = vi.fn((chain: readonly ScopeRef[]) =>
      Promise.resolve(chain.length === 0 ? FALLBACK : RESOLVED),
    )
    draw(repository({ resolved }))

    await waitFor(() => expect(resolved).toHaveBeenCalledTimes(2))
    // The second call is the whole fallback mechanism. Computing it from the
    // schema's `default` instead is free and wrong — wrong whenever a middle
    // layer answers, and `null` for every secret by contract. If this
    // assertion is deleted, that shortcut becomes invisible.
    expect(resolved.mock.calls.map((call) => call[0])).toEqual([
      [{ scope: 'project', scopeId: 'p1' }],
      [],
    ])
  })

  it('renders no group whose settings this scope cannot set', async () => {
    draw(repository())
    // Two matches per group on purpose -- the rail's link and the section's
    // own heading -- so this counts rather than asserting singularity.
    await screen.findAllByText('Models')
    // `Stores` is tenant-only in full. Filtering on `spec.scopes` is what keeps
    // a pgvector DSN off a project page, and it removes the whole group rather
    // than leaving an empty heading -- which would read as "this is empty for
    // you" instead of "this does not apply here".
    expect(screen.queryAllByText('Stores')).toHaveLength(0)
  })

  it('finds a setting by its environment variable, which is how operators arrive', async () => {
    const user = userEvent.setup()
    draw(repository())
    await screen.findByText('Chunk size')

    await user.type(screen.getByRole('searchbox'), 'AGENT_EXTRACTION_CHUNK')

    expect(screen.getByText('Chunk size')).toBeTruthy()
    // A search over labels alone would send somebody who pasted a compose-file
    // variable straight back to the shell.
    expect(screen.queryByText('Chat model')).toBeNull()
  })

  it('offers "overridden here" as a filter and not as the first view', async () => {
    const user = userEvent.setup()
    draw(repository())
    await screen.findByText('Chat model')

    // Both rows before the filter: a page showing only differences cannot
    // answer "what is this project actually using", which is the more common
    // question and the one somebody arrives with after a bad run.
    expect(screen.getByText('Chunk size')).toBeTruthy()

    await user.click(screen.getByRole('checkbox'))

    expect(screen.getByText('Chat model')).toBeTruthy()
    expect(screen.queryByText('Chunk size')).toBeNull()
  })

  it('draws the form with an error when the resolution fails, never an empty page', async () => {
    draw(
      repository({
        resolved: vi.fn().mockRejectedValue(new ApiError('no such column: masked', 500)),
      }),
    )

    // CLAUDE.md's read-model trap arriving as a UI question -- it will happen
    // the first time a column is added against an existing database. An empty
    // settings page reads as "this project has no settings", which is a wrong
    // answer rather than an absent one.
    await screen.findByText(/could not be resolved/)
    expect(screen.getByText('Project settings')).toBeTruthy()
    expect(screen.getAllByText('Models').length).toBeGreaterThan(0)
  })

  it('reports a failed fallback lookup as smaller than a failed resolution', async () => {
    draw(
      repository({
        resolved: vi.fn((chain: readonly ScopeRef[]) =>
          chain.length === 0
            ? Promise.reject(new ApiError('boom', 500))
            : Promise.resolve(RESOLVED),
        ),
      }),
    )

    // Every value on the page is still true; the one thing missing is what a
    // clear would reveal. Rendering it as the same red box would overstate it.
    await screen.findByText(/fallback lookup failed/)
    expect(screen.queryByText(/could not be resolved/)).toBeNull()
  })

  it('says which layers sit below this scope, in the scope’s own words', async () => {
    draw(repository())
    // `SCOPE_COPY` rather than a second page per scope. The tenant entry says
    // something genuinely different -- it is the deployment default -- which is
    // why it is copy and not a word substitution.
    await screen.findByText(/A value with no override here comes from the user, the tenant/)
  })
})

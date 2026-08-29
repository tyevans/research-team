import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { ContainerProvider } from '@app/container-context.tsx'
import type { SettingsRepository } from '@application/ports/repositories.ts'
import {
  chainFrom,
  layersBelow,
  type ResolvedSettings,
  type ScopeRef,
} from '@domain/settings/layer.ts'
import { SCOPES, type Scope, type SettingsSchema } from '@domain/settings/spec.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { SettingsPage } from './SettingsPage.tsx'
import { SCOPE_COPY } from './scope-copy.ts'

import { buildContainer } from '../../test/container.ts'

/** The same page over three scopes — S5's whole claim.
 *
 * The design's argument is that a scope is a **value**, not a variant: which
 * settings render is `spec.scopes`, how deep the chain is falls out of
 * `RESOLUTION_ORDER`, and the sentences are a record of three. Nothing
 * branches. These tests are what makes that checkable rather than asserted,
 * and they are parametrised over `SCOPES` rather than written three times —
 * a fourth scope added to the tuple fails here rather than rendering
 * something nobody looked at.
 *
 * **Only the project scope has an entry point in the console today**, because
 * there is no identity endpoint to learn a subject or a tenant id from. The
 * user and tenant pages are reachable by URL and are correct when reached;
 * that gap is W-A's and is stated in the PR rather than papered over here
 * with a hardcoded `'local'`.
 */

/** One setting per scope-width, so the filter has something to remove.
 *
 * `deployment_only` mirrors the real registry's shape -- `AGENT_PGVECTOR_DSN`
 * and now `AGENT_AUTH` are tenant-only -- and is the reason a project page and
 * a tenant page are genuinely different documents rather than the same one
 * twice. */
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
      name: 'Authorization',
      settings: [
        {
          key: 'auth',
          envVar: 'AGENT_AUTH',
          type: 'enum',
          label: 'Authorization',
          description: 'Whether permissions are enforced.',
          group: 'Authorization',
          secret: false,
          default: 'off',
          choices: ['off', 'on'],
          minimum: null,
          maximum: null,
          requiredWhen: null,
          scopes: ['tenant'],
        },
      ],
    },
  ],
  scopes: ['project', 'user', 'tenant'],
  roles: [],
}

const resolvedFor = (scope: Scope, scopeId: string): ResolvedSettings => ({
  scopeChain: [{ scope, scopeId }],
  settings: [
    { key: 'model', value: 'mine', layer: scope, scopeId, secret: false, masked: null },
    { key: 'auth', value: 'off', layer: 'default', scopeId: null, secret: false, masked: null },
  ],
})

const draw = (scope: Scope, scopeId: string, settings: SettingsRepository) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={buildContainer({ settings })}>
        <OverlayHost>
          <SettingsPage scope={scope} scopeId={scopeId} group={null} />
        </OverlayHost>
      </ContainerProvider>
    </QueryClientProvider>,
  )
}

const repository = (scopeId: string) => {
  const resolved = vi.fn((chain: readonly ScopeRef[]) =>
    Promise.resolve(
      chain.length === 0 ? { scopeChain: [], settings: [] } : resolvedFor(chain[0]!.scope, scopeId),
    ),
  )
  const settings: SettingsRepository = {
    schema: () => Promise.resolve(SCHEMA),
    resolved,
    put: () => Promise.resolve(),
    clear: () => Promise.resolve(true),
  }
  // The spy is handed back beside the port rather than read off it later:
  // `vi.mocked(settings.resolved)` detaches the method from its object, which
  // this repo's `unbound-method` rule refuses -- and rightly, since a port is
  // an interface and nothing promises its methods are bound.
  return { settings, resolved }
}

describe('the chain a page walks', () => {
  it.each(SCOPES)('starts at %s and runs to the built-in default', (scope) => {
    // Derived by one `slice`, which is what keeps three scopes on one page.
    expect(chainFrom(scope)[0]).toBe(scope)
    expect(chainFrom(scope).at(-1)).toBe('default')
    expect(layersBelow(scope)).toEqual(chainFrom(scope).slice(1))
  })

  it('gives a tenant page three layers and a project page five', () => {
    // The concrete asymmetry S5 exists for. A tenant page's requests name only
    // a tenant, so `project` and `user` cannot answer it.
    expect(chainFrom('tenant')).toEqual(['tenant', 'environment', 'default'])
    expect(chainFrom('project')).toHaveLength(5)
  })
})

describe('the chain popover', () => {
  it('shows no layer above the scope being edited', async () => {
    const user = userEvent.setup()
    draw('tenant', 't1', repository('t1').settings)
    await screen.findByText('Chat model')

    await user.click(screen.getByRole('button', { name: /resolved from tenant/ }))

    expect(screen.getByTestId('chain-tenant')).toBeTruthy()
    // Rendering these greyed would say "consulted and empty", which is a
    // different and false claim: on a tenant page they are not in the chain at
    // all. This is the assertion that fails if the popover goes back to
    // mapping `RESOLUTION_ORDER`.
    expect(screen.queryByTestId('chain-project')).toBeNull()
    expect(screen.queryByTestId('chain-user')).toBeNull()
  })

  it('shows all five on a project page, where all five can answer', async () => {
    const user = userEvent.setup()
    draw('project', 'p1', repository('p1').settings)
    await screen.findByText('Chat model')

    await user.click(screen.getByRole('button', { name: /resolved from project/ }))

    for (const layer of chainFrom('project')) {
      expect(screen.getByTestId(`chain-${layer}`)).toBeTruthy()
    }
  })
})

describe('which settings a scope may set', () => {
  it('keeps a tenant-only group off the project and user pages', async () => {
    for (const scope of ['project', 'user'] as const) {
      const view = draw(scope, 'x1', repository('x1').settings)
      await screen.findAllByText('Models')
      // `AGENT_AUTH` is deployment scope. A project that could turn its own
      // permission checking off would not be a permission system.
      expect(screen.queryAllByText('Authorization')).toHaveLength(0)
      view.unmount()
    }
  })

  it('renders it at tenant scope, where it can actually be written', async () => {
    draw('tenant', 't1', repository('t1').settings)
    // Two matches -- the rail and the section heading.
    expect((await screen.findAllByText('Authorization')).length).toBeGreaterThan(0)
  })
})

describe('the copy', () => {
  it.each(SCOPES)('%s names itself rather than reusing another scope’s words', (scope) => {
    const others = SCOPES.filter((other) => other !== scope)
    for (const other of others) {
      expect(SCOPE_COPY[scope].heading).not.toBe(SCOPE_COPY[other].heading)
      // Not a word substitution: at tenant scope these values are the
      // deployment default every project inherits, which is a different claim
      // about what pressing something here does.
      expect(SCOPE_COPY[scope].blurb).not.toBe(SCOPE_COPY[other].blurb)
    }
  })

  it.each(SCOPES)('renders %s’s own heading on the page', async (scope) => {
    draw(scope, 'x1', repository('x1').settings)
    await screen.findByText(SCOPE_COPY[scope].heading)
  })
})

describe('the fallback resolution', () => {
  it.each(SCOPES)('omits %s from the second request', async (scope) => {
    const { settings, resolved } = repository('x1')
    draw(scope, 'x1', settings)
    await screen.findByText('Chat model')

    const calls = resolved.mock.calls.map((call) => call[0])
    expect(calls).toHaveLength(2)
    expect(calls[0]).toEqual([{ scope, scopeId: 'x1' }])
    // Derived by filtering this scope out of the chain, not written as `[]`.
    // The two happen to agree today because the chain holds one entry; the
    // filter is what stays right when identity lands and it holds three.
    expect(calls[1]).toEqual([])
  })
})

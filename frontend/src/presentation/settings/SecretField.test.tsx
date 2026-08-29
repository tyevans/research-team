import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactElement } from 'react'
import { describe, expect, it, vi } from 'vitest'

import { ContainerProvider } from '@app/container-context.tsx'
import { ApiError } from '@application/ports/errors.ts'
import type { SettingsRepository } from '@application/ports/repositories.ts'
import type { ResolvedSetting } from '@domain/settings/layer.ts'
import type { SettingSpec } from '@domain/settings/spec.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { SettingRow } from './SettingRow.tsx'
import { CanEditProvider } from './permissions.ts'

import { buildContainer } from '../../test/container.ts'

/** The secret field's three states, and the fourth that must not exist.
 *
 * Driven through `SettingRow` rather than `SecretField` alone, on purpose: the
 * two assertions that matter most are about the *seam* -- that a failed save
 * leaves the paste alone, and that a successful one returns to the masked
 * display -- and both of those are decided by who owns the draft. A test over
 * the leaf component with a hand-held draft would assert that a prop was
 * rendered, which is not the claim.
 */

const SECRET: SettingSpec = {
  key: 'api_key',
  envVar: 'AGENT_API_KEY',
  type: 'string',
  label: 'API key',
  description: 'The credential the provider is called with.',
  group: 'Models',
  secret: true,
  // `null` for every secret, always. The schema never carries a credential,
  // including a placeholder one -- which is why the fallback for this field
  // can only come from the second resolution.
  default: null,
  choices: [],
  minimum: null,
  maximum: null,
  requiredWhen: null,
  scopes: ['project', 'user', 'tenant'],
}

const unset: ResolvedSetting = {
  key: 'api_key',
  value: null,
  layer: 'default',
  scopeId: null,
  secret: true,
  masked: { present: false, lastFour: null, display: 'not set' },
}

const stored: ResolvedSetting = {
  key: 'api_key',
  value: null,
  layer: 'project',
  scopeId: 'p1',
  secret: true,
  masked: { present: true, lastFour: '1234', display: 'set (…1234)' },
}

const settingsFake = (over: Partial<SettingsRepository> = {}): SettingsRepository => ({
  schema: vi.fn(),
  resolved: vi.fn(),
  put: vi.fn().mockResolvedValue(undefined),
  clear: vi.fn().mockResolvedValue(true),
  providers: vi.fn().mockResolvedValue([]),
  testProvider: vi.fn(),
  ...over,
})

const draw = (
  element: ReactElement,
  { settings, canEdit }: { settings?: SettingsRepository; canEdit?: (key: string) => boolean } = {},
) => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const container = buildContainer({ settings: settings ?? settingsFake() })
  return render(
    <QueryClientProvider client={client}>
      <ContainerProvider container={container}>
        <CanEditProvider value={canEdit ?? (() => true)}>
          <OverlayHost>{element}</OverlayHost>
        </CanEditProvider>
      </ContainerProvider>
    </QueryClientProvider>,
  )
}

const secretRow = (resolved: ResolvedSetting, fallback?: ResolvedSetting) => (
  <SettingRow
    spec={SECRET}
    resolved={resolved}
    fallback={fallback}
    scope="project"
    scopeId="p1"
    chain={[{ scope: 'project', scopeId: 'p1' }]}
    below={[]}
  />
)

describe('unset', () => {
  it('is an empty password box asking for a paste, and says the server calls it "not set"', () => {
    draw(secretRow(unset))
    const field: HTMLInputElement = screen.getByLabelText('API key')
    expect(field.type).toBe('password')
    expect(field.value).toBe('')
    expect(field.placeholder).toBe('paste a key')
    // There is nothing to cancel back to.
    expect(screen.queryByRole('button', { name: 'Cancel' })).toBeNull()
  })
})

describe('set and untouched', () => {
  it('holds no input element at all — never a row of bullets', () => {
    draw(secretRow(stored))

    // The load-bearing assertion of this whole slice. A bullet string is a
    // *value*: it lives in an input, it is submittable, and it is one careless
    // change away from being round-tripped to the server as the literal
    // password. This goes red the moment anybody reintroduces a masked input
    // "for the look of it", which is exactly how that defect arrives.
    expect(document.querySelectorAll('input')).toHaveLength(0)
    expect(screen.getByText('set (…1234)')).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Replace' })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'Clear' })).toBeTruthy()
  })

  it('shows the server’s own display string rather than rebuilding one', () => {
    // Rebuilt from `present` and `lastFour` the console and the API could come
    // to describe the same secret differently -- `••••1234` here and
    // `set (…1234)` in a log line about the same key.
    draw(secretRow({ ...stored, masked: { present: true, lastFour: null, display: 'set' } }))
    expect(screen.getByText('set')).toBeTruthy()
  })
})

describe('replacing', () => {
  it('opens an empty box that is never seeded from anything', async () => {
    const user = userEvent.setup()
    draw(secretRow(stored))

    await user.click(screen.getByRole('button', { name: 'Replace' }))

    const field: HTMLInputElement = screen.getByLabelText('API key')
    expect(field.value).toBe('')
    expect(field.type).toBe('password')
  })

  it('returns to the masked display on Cancel', async () => {
    const user = userEvent.setup()
    draw(secretRow(stored))

    await user.click(screen.getByRole('button', { name: 'Replace' }))
    await user.type(screen.getByLabelText('API key'), 'sk-typed')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(document.querySelectorAll('input')).toHaveLength(0)
    expect(screen.getByText('set (…1234)')).toBeTruthy()
  })

  it('opts every password box out of password managers', () => {
    draw(secretRow(unset))
    const field = screen.getByLabelText('API key')
    // A masked display that looks like a filled password field is an
    // invitation to a manager, and a manager filling it is precisely the round
    // trip the contract forbids. `autoComplete` is what most honour;
    // `data-1p-ignore` is 1Password's own opt-out. Neither alone covers it.
    expect(field.getAttribute('autocomplete')).toBe('off')
    expect(field.hasAttribute('data-1p-ignore')).toBe(true)
  })
})

describe('a failed save', () => {
  it('keeps the paste, which is the defect this design exists to remove', async () => {
    const user = userEvent.setup()
    const put = vi
      .fn()
      .mockRejectedValue(
        new ApiError('a secret cannot be stored: AGENT_SETTINGS_KEY is not configured', 422),
      )
    draw(secretRow(unset), { settings: settingsFake({ put }) })

    await user.type(screen.getByLabelText('API key'), 'sk-live-abcdef')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    // Not cleared, not reset, not refetched. If any of those crept in, a
    // person would have to find and re-copy a key they pasted from a password
    // manager -- for a failure they cannot fix from this page.
    expect(screen.getByLabelText<HTMLInputElement>('API key').value).toBe('sk-live-abcdef')
    // And the deployment problem is named rather than reworded into a generic
    // validation message.
    expect(screen.getByRole('alert').textContent).toContain('AGENT_SETTINGS_KEY')
  })

  it('returns to the masked display when the save works', async () => {
    const user = userEvent.setup()
    draw(secretRow(stored))

    await user.click(screen.getByRole('button', { name: 'Replace' }))
    await user.type(screen.getByLabelText('API key'), 'sk-new')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(document.querySelectorAll('input')).toHaveLength(0))
  })

  it('never puts the typed key anywhere but the request body', async () => {
    const user = userEvent.setup()
    const put = vi.fn().mockResolvedValue(undefined)
    draw(secretRow(unset), { settings: settingsFake({ put }) })

    await user.type(screen.getByLabelText('API key'), 'sk-secret')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(put).toHaveBeenCalledWith('project', 'p1', 'api_key', 'sk-secret'))
    // The optimistic cache patch writes `layer` and leaves a secret's `value`
    // null, so the key cannot end up in a query cache a devtools panel or a
    // future serialiser would print.
    expect(document.body.innerHTML).not.toContain('sk-secret')
  })
})

describe('clearing a credential', () => {
  it('says which key the scope will fall back to, not just "are you sure"', async () => {
    const user = userEvent.setup()
    draw(
      secretRow(stored, {
        key: 'api_key',
        value: null,
        layer: 'tenant',
        scopeId: 't1',
        secret: true,
        masked: { present: true, lastFour: '9f21', display: 'set (…9f21)' },
      }),
    )

    await user.click(screen.getByRole('button', { name: 'Clear' }))

    // Only the second resolution can answer this. The schema's `default` is
    // `null` for every secret by contract, so the one field where "what
    // happens if I clear this" is frightening is the one field it cannot
    // answer at all.
    expect(screen.getByText(/It will then use set \(…9f21\), from tenant\./)).toBeTruthy()
  })

  it('says so when clearing leaves the provider with no credential', async () => {
    const user = userEvent.setup()
    draw(
      secretRow(stored, {
        key: 'api_key',
        value: null,
        layer: 'default',
        scopeId: null,
        secret: true,
        masked: { present: false, lastFour: null, display: 'not set' },
      }),
    )

    await user.click(screen.getByRole('button', { name: 'Clear' }))
    expect(screen.getByText(/will be unset/)).toBeTruthy()
  })
})

describe('a credential this caller may not edit', () => {
  it('shows the mask and offers neither Replace nor Clear', () => {
    // The permissive-default trap again: with `canEdit` unread this renders
    // two buttons and a password box, so all three assertions move together.
    draw(secretRow(stored), { canEdit: () => false })
    expect(screen.getByText('set (…1234)')).toBeTruthy()
    expect(screen.queryByRole('button', { name: 'Replace' })).toBeNull()
    expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull()
    expect(document.querySelectorAll('input')).toHaveLength(0)
  })
})

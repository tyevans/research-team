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

const CHAIN = [{ scope: 'project' as const, scopeId: 'p1' }]
const BELOW: [] = []

const spec = (over: Partial<SettingSpec> = {}): SettingSpec => ({
  key: 'model',
  envVar: 'AGENT_MODEL',
  type: 'string',
  label: 'Chat model',
  description: 'The model the research agent talks to.',
  group: 'Models',
  secret: false,
  default: 'qwen3.6-27b-mtp',
  choices: [],
  minimum: null,
  maximum: null,
  requiredWhen: null,
  scopes: ['project', 'user', 'tenant'],
  ...over,
})

const resolved = (over: Partial<ResolvedSetting> = {}): ResolvedSetting => ({
  key: 'model',
  value: 'my-model',
  layer: 'project',
  scopeId: 'p1',
  secret: false,
  masked: null,
  ...over,
})

const settingsFake = (over: Partial<SettingsRepository> = {}): SettingsRepository => ({
  schema: vi.fn(),
  resolved: vi.fn(),
  put: vi.fn().mockResolvedValue(undefined),
  clear: vi.fn().mockResolvedValue(true),
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

const row = (props: Partial<Parameters<typeof SettingRow>[0]> = {}) => (
  <SettingRow
    spec={spec()}
    resolved={resolved()}
    fallback={undefined}
    scope="project"
    scopeId="p1"
    chain={CHAIN}
    below={BELOW}
    {...props}
  />
)

describe('a row that this scope set', () => {
  it('offers Clear, and an inherited one does not', () => {
    draw(row())
    expect(screen.getByRole('button', { name: 'Clear' })).toBeTruthy()

    // `DELETE` answers 404 when there is no override, deliberately -- clearing
    // a key that was never set is almost always a misspelling -- so a button
    // whose only possible outcome is that 404 must not be on screen.
    draw(row({ resolved: resolved({ layer: 'tenant', scopeId: 't1' }) }))
    expect(screen.getAllByRole('button', { name: 'Clear' })).toHaveLength(1)
  })

  it('says what clearing it would fall back to, from the second resolution', () => {
    draw(
      row({
        fallback: resolved({ value: 'llama-3.3-70b', layer: 'tenant', scopeId: 't1' }),
      }),
    )
    // The line names both the value and the layer. Neither is derivable from
    // the schema's `default`, which is what this second request replaces.
    expect(screen.getByText(/clearing this falls back to/)).toBeTruthy()
    expect(screen.getByText('llama-3.3-70b')).toBeTruthy()
    expect(screen.getByText(/\(tenant\)/)).toBeTruthy()
  })

  it('names the fallback in the confirm rather than asking "are you sure"', async () => {
    const user = userEvent.setup()
    draw(row({ fallback: resolved({ value: 'llama-3.3-70b', layer: 'tenant', scopeId: 't1' }) }))

    await user.click(screen.getByRole('button', { name: 'Clear' }))

    // "It will then use X, from tenant" is a sentence somebody can act on;
    // "this cannot be undone" is not, and is what this fails on if the second
    // resolution ever stops reaching the confirm.
    expect(screen.getByText(/It will then use llama-3\.3-70b, from tenant\./)).toBeTruthy()
  })

  it('says so when the fallback is nothing at all', async () => {
    const user = userEvent.setup()
    draw(row({ fallback: resolved({ value: null, layer: 'default', scopeId: null }) }))

    await user.click(screen.getByRole('button', { name: 'Clear' }))

    // Clearing into nothing is the case worth a moment's pause, and it reads
    // differently from clearing into another layer's value.
    expect(screen.getByText(/will be unset/)).toBeTruthy()
  })
})

describe('writing', () => {
  it('creates an override from an inherited row without any unlock step', async () => {
    const user = userEvent.setup()
    const put = vi.fn().mockResolvedValue(undefined)
    draw(row({ resolved: resolved({ value: 'inherited', layer: 'tenant', scopeId: 't1' }) }), {
      settings: settingsFake({ put }),
    })

    const field = screen.getByLabelText('Chat model')
    await user.clear(field)
    await user.type(field, 'mine{Enter}')

    // The whole argument for a live control over a per-row "Override" toggle:
    // typing and committing is the interaction, and a test that only exercised
    // an already-overridden row could not see the toggle-less path work.
    await waitFor(() => expect(put).toHaveBeenCalledWith('project', 'p1', 'model', 'mine'))
  })

  it('does not write when a blur leaves an existing override unchanged', async () => {
    const user = userEvent.setup()
    const put = vi.fn().mockResolvedValue(undefined)
    draw(row(), { settings: settingsFake({ put }) })

    await user.click(screen.getByLabelText('Chat model'))
    await user.tab()

    expect(put).not.toHaveBeenCalled()
  })

  it('keeps the typed value and shows the server sentence on a 422', async () => {
    const user = userEvent.setup()
    const put = vi.fn().mockRejectedValue(new ApiError('extraction_chunk_size must be ≥ 200', 422))
    draw(row({ resolved: resolved({ value: 'old' }) }), { settings: settingsFake({ put }) })

    const field = screen.getByLabelText('Chat model')
    await user.clear(field)
    await user.type(field, 'rejected{Enter}')

    await waitFor(() => expect(screen.getByRole('alert')).toBeTruthy())
    // The server's own words, not a generic "could not save" -- the 422 that
    // happens most is "a secret with no AGENT_SETTINGS_KEY configured", which
    // is a deployment problem this page cannot fix and must therefore name.
    expect(screen.getByRole('alert').textContent).toContain('must be ≥ 200')
    // And the draft survives. This is the assertion S3 depends on, exercised
    // here on an ordinary string because it holds for every field.
    expect((field as HTMLInputElement).value).toBe('rejected')
  })

  it('distinguishes "cleared" from "there was nothing to clear"', async () => {
    const user = userEvent.setup()
    // The repository resolves `false` for the contract's deliberate 404.
    const clear = vi.fn().mockResolvedValue(false)
    draw(row(), { settings: settingsFake({ clear }) })

    await user.click(screen.getByRole('button', { name: 'Clear' }))
    await user.click(screen.getByRole('button', { name: 'Clear' }))

    await waitFor(() =>
      expect(screen.getByText(/There was no override here to clear/)).toBeTruthy(),
    )
  })
})

/** The permission seam, driven by a `canEdit` that answers **no**.
 *
 * This is the shape CLAUDE.md names under the interaction log: a permissive
 * default makes "never wired up" and "working" identical, so a test rendering
 * with the default `() => true` and asserting nothing threw would pass with
 * every call site of `canEdit` deleted. Only a refusing `canEdit` can tell the
 * two apart, and these three assertions all go red if `SettingRow` stops
 * consulting it. */
describe('a key this caller may not edit', () => {
  it('renders no control at all rather than a disabled one', () => {
    draw(row(), { canEdit: () => false })

    // No control, not `disabled`: a disabled element is still in the
    // accessibility tree and reads as "you could change this, later".
    expect(screen.queryByLabelText('Chat model')).toBeNull()
    expect(screen.queryByRole('textbox')).toBeNull()
  })

  it('leaves nothing of the row in the tab order but its layer chip', async () => {
    const user = userEvent.setup()
    draw(row(), { canEdit: () => false })

    await user.tab()
    // The chip stays reachable on purpose -- "why is this value what it is" is
    // a question a reader who cannot edit still gets to ask.
    expect(document.activeElement?.textContent).toBe('project')
    expect(screen.queryByRole('button', { name: 'Clear' })).toBeNull()
  })

  it('still shows the value, and says why it cannot be changed', () => {
    draw(row(), { canEdit: () => false })
    expect(screen.getByText('my-model')).toBeTruthy()
    expect(screen.getByText(/cannot change this setting/)).toBeTruthy()
  })

  it('is asked about the key it is rendering, not about the page', () => {
    // A `canEdit` that ignores its argument would pass every test above. This
    // one refuses one key and permits another, which is what a real capability
    // does.
    const canEdit = (key: string) => key !== 'model'
    draw(row(), { canEdit })
    expect(screen.queryByLabelText('Chat model')).toBeNull()

    draw(row({ spec: spec({ key: 'other', label: 'Other' }) }), { canEdit })
    expect(screen.getByLabelText('Other')).toBeTruthy()
  })
})

describe('the layer chip', () => {
  it('carries the word, so colour is never the only signal', () => {
    draw(row({ resolved: resolved({ layer: 'environment', scopeId: null }) }))
    expect(screen.getByRole('button', { name: /resolved from environment/ })).toBeTruthy()
  })

  it('opens the whole chain on demand, and nowhere else', async () => {
    const user = userEvent.setup()
    draw(row({ fallback: resolved({ value: 'llama', layer: 'tenant', scopeId: 't1' }) }))

    // Not inline: five lines times twenty-five rows is accurate and unreadable.
    expect(screen.queryByTestId('chain-default')).toBeNull()

    await user.click(screen.getByRole('button', { name: /resolved from project/ }))

    expect(screen.getByTestId('chain-project').textContent).toContain('my-model')
    expect(screen.getByTestId('chain-tenant').textContent).toContain('llama')
    // The layers this page genuinely does not know about say so rather than
    // claiming to be empty. The API reports the layer that *answered*; it does
    // not report what the ones below hold, except through the second
    // resolution -- which is exactly one of them.
    expect(screen.getByTestId('chain-environment').textContent).toContain('not consulted')
  })
})

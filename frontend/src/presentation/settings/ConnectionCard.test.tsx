import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import type { ResolvedSetting } from '@domain/settings/layer.ts'
import type { Provider } from '@domain/settings/provider.ts'
import type { SettingSpec } from '@domain/settings/spec.ts'

import { OverlayHost } from '../layout/OverlayHost.tsx'
import { ConnectionCard } from './ConnectionCard.tsx'

/** The connection card: the credential, the placeholders, and the test.
 *
 * The card is where the secret rules from S3 meet a provider catalogue, so
 * the assertions that matter are the ones about what leaves the browser —
 * which key is sent, and when the button can be pressed at all.
 */

const spec = (key: string): SettingSpec => ({
  key,
  envVar: 'AGENT_PROVIDER_KEY_X',
  type: 'string',
  label: 'API key',
  description: '',
  group: 'Provider credentials',
  secret: true,
  default: null,
  choices: [],
  minimum: null,
  maximum: null,
  requiredWhen: null,
  scopes: ['project', 'user', 'tenant'],
})

const unset = (key: string): ResolvedSetting => ({
  key,
  value: null,
  layer: 'default',
  scopeId: null,
  secret: true,
  masked: { present: false, lastFour: null, display: 'not set' },
})

const openai: Provider = {
  id: 'openai',
  displayName: 'OpenAI',
  baseUrl: 'https://api.openai.com/v1/',
  auth: 'bearer',
  openaiCompatible: true,
  capabilities: ['chat', 'embeddings'],
  credentials: [
    { name: 'api_key', label: 'API key', secret: true, required: true, settingKey: null },
  ],
  notes: '',
}

const azure: Provider = {
  ...openai,
  id: 'azure_openai',
  displayName: 'Azure OpenAI',
  baseUrl: 'https://{resource}.openai.azure.com/openai/deployments/{deployment}',
  openaiCompatible: false,
}

const draw = (provider: Provider, props: Partial<Parameters<typeof ConnectionCard>[0]> = {}) => {
  const key = `provider_key.${provider.id}.api_key`
  return render(
    <OverlayHost>
      <ConnectionCard
        provider={provider}
        credentialSpecs={new Map([['api_key', spec(key)]])}
        resolved={new Map([['api_key', unset(key)]])}
        scope="project"
        onTest={vi.fn()}
        testing={false}
        result={undefined}
        onSaveCredential={vi.fn()}
        onClearCredential={vi.fn()}
        {...props}
      />
    </OverlayHost>,
  )
}

describe('placeholders in the base url', () => {
  it('asks for one field per marker, and keeps Test disabled until all are filled', async () => {
    const user = userEvent.setup()
    draw(azure)

    // An unfilled url answers `unsupported` anyway, so this is the honest
    // second line of defence rather than the only one -- but a button that can
    // only fail is still a button worth not offering.
    expect(screen.getByRole('button', { name: 'Test' })).toHaveProperty('disabled', true)

    await user.type(screen.getByLabelText(/resource/i, { selector: 'input' }), 'acme')
    expect(screen.getByRole('button', { name: 'Test' })).toHaveProperty('disabled', true)

    await user.type(screen.getByLabelText(/deployment/i, { selector: 'input' }), 'gpt')
    expect(screen.getByRole('button', { name: 'Test' })).toHaveProperty('disabled', false)
  })

  it('renders the placeholder fields in the clear, not as secrets', () => {
    draw(azure)
    // The contract declares `resource` and `deployment` not-secret precisely so
    // they are readable. Masking a region would make this card useless for the
    // two providers that need it most.
    const resource = screen.getByLabelText(/resource/i, { selector: 'input' })
    expect(resource).toHaveProperty('type', 'text')
  })

  it('offers Test immediately for a provider whose url has no markers', () => {
    draw(openai)
    expect(screen.getByRole('button', { name: 'Test' })).toHaveProperty('disabled', false)
  })
})

describe('what the test sends', () => {
  it('sends the key currently typed, before it has been saved', async () => {
    const user = userEvent.setup()
    const onTest = vi.fn()
    draw(openai, { onTest })

    await user.type(screen.getByLabelText('API key'), 'sk-typed')
    await user.click(screen.getByRole('button', { name: 'Test' }))

    // Test-then-save puts the common failure -- a mistyped key -- before
    // storage rather than after it. Reading a saved key back to test it is not
    // an option: no such route exists, deliberately.
    expect(onTest).toHaveBeenCalledWith({
      apiKey: 'sk-typed',
      baseUrl: 'https://api.openai.com/v1/',
    })
  })

  it('omits the key entirely when none is typed', async () => {
    const user = userEvent.setup()
    const onTest = vi.fn()
    draw(openai, { onTest })

    await user.click(screen.getByRole('button', { name: 'Test' }))

    // Absent, not `''`. `exactOptionalPropertyTypes` makes the two different
    // types and the route makes them different requests: no key means "test
    // what you can without one".
    expect(onTest).toHaveBeenCalledWith({ baseUrl: 'https://api.openai.com/v1/' })
  })

  it('sends the filled url rather than the one with markers in it', async () => {
    const user = userEvent.setup()
    const onTest = vi.fn()
    draw(azure, { onTest })

    await user.type(screen.getByLabelText(/resource/i, { selector: 'input' }), 'acme')
    await user.type(screen.getByLabelText(/deployment/i, { selector: 'input' }), 'gpt')
    await user.click(screen.getByRole('button', { name: 'Test' }))

    expect(onTest).toHaveBeenCalledWith({
      baseUrl: 'https://acme.openai.azure.com/openai/deployments/gpt',
    })
  })

  it('tells the person a saved key has to be re-pasted to be tested', () => {
    const key = 'provider_key.openai.api_key'
    draw(openai, {
      resolved: new Map([
        [
          'api_key',
          {
            key,
            value: null,
            layer: 'project' as const,
            scopeId: 'p1',
            secret: true,
            masked: { present: true, lastFour: '1234', display: 'set (…1234)' },
          },
        ],
      ]),
    })
    // Stated rather than left as a surprise: the contract has no route that
    // reads a secret back, so an empty field beside a stored key is correct
    // and looks like a bug unless the card says why.
    expect(screen.getByText(/cannot be read back/)).toBeTruthy()
  })
})

describe('when the schema and the catalogue disagree', () => {
  it('says so rather than rendering nothing', () => {
    // A silently missing credential field is indistinguishable from a provider
    // that needs none, and this is exactly the seam where the catalogue and the
    // dynamic `provider_key.*` namespace have to agree.
    draw(openai, { credentialSpecs: new Map(), resolved: new Map() })
    expect(screen.getByText(/has no setting in this build/)).toBeTruthy()
  })
})

import { describe, expect, it } from 'vitest'

import { canServe, fillPlaceholders, isFilled, placeholdersIn, type Provider } from './provider.ts'
import { ROLES, sharedGroups, sharing, type ResolvedRole } from './role.ts'

/** The pure decisions S4 rests on, tested where they are decisions rather than
 *  through a component that would also be testing React.
 *
 * All three are things a component would otherwise have hardcoded: which
 * providers can answer which role, which parts of a url a form has to ask for,
 * and which roles move together when one is changed. Each is derived from data
 * the backend sends, and each has an obvious wrong implementation that a
 * component test would not distinguish.
 */

const provider = (over: Partial<Provider> = {}): Provider => ({
  id: 'openai',
  displayName: 'OpenAI',
  baseUrl: 'https://api.openai.com/v1/',
  auth: 'bearer',
  openaiCompatible: true,
  capabilities: ['chat', 'embeddings', 'tools', 'vision'],
  credentials: [
    { name: 'api_key', label: 'API key', secret: true, required: true, settingKey: null },
  ],
  notes: '',
  ...over,
})

describe('placeholders in a base url', () => {
  it('finds none in an ordinary url', () => {
    expect(placeholdersIn('https://api.openai.com/v1/')).toEqual([])
  })

  it('finds the Azure markers in reading order', () => {
    // Order is the url's own, which is the order somebody filling the form in
    // expects to be asked. Sorting them would be a second opinion about a
    // sequence the provider already chose.
    expect(
      placeholdersIn('https://{resource}.openai.azure.com/openai/deployments/{deployment}'),
    ).toEqual(['resource', 'deployment'])
  })

  it('asks once for a marker the url uses twice', () => {
    expect(placeholdersIn('https://bedrock.{region}.amazonaws.com/{region}/x')).toEqual(['region'])
  })

  it('leaves an unfilled marker standing rather than producing a plausible url', () => {
    // The failure this prevents: a half-filled url that *looks* like an
    // address, gets sent, and fails somewhere that names neither the missing
    // field nor the provider.
    expect(fillPlaceholders('https://{resource}.x.com/{deployment}', { resource: 'acme' })).toBe(
      'https://acme.x.com/{deployment}',
    )
    // An empty string counts as unfilled, not as a value. A person who cleared
    // the field has not answered the question.
    expect(fillPlaceholders('https://{a}.x', { a: '' })).toBe('https://{a}.x')
  })

  it('is filled only when every marker has a value', () => {
    const url = 'https://{resource}.x.com/{deployment}'
    expect(isFilled(url, {})).toBe(false)
    expect(isFilled(url, { resource: 'acme' })).toBe(false)
    expect(isFilled(url, { resource: 'acme', deployment: 'gpt' })).toBe(true)
    // A url with no markers is always ready, which is what keeps `Test`
    // enabled for the thirteen providers that have none.
    expect(isFilled('https://api.openai.com/v1/', {})).toBe(true)
  })
})

describe('capability gating', () => {
  it('offers a provider for embedding only when it declares embeddings', () => {
    const withOut = provider({ capabilities: ['chat', 'tools'] })
    expect(canServe(withOut, 'embedding')).toBe(false)
    expect(canServe(provider(), 'embedding')).toBe(true)
  })

  it('offers a provider for vision only when it declares vision', () => {
    expect(canServe(provider({ capabilities: ['chat'] }), 'vision')).toBe(false)
    expect(canServe(provider(), 'vision')).toBe(true)
  })

  it('asks for chat for the three roles that are chat', () => {
    // Parametrised over the remainder rather than naming them, so a sixth role
    // added to `ROLES` is a decision somebody has to make here rather than one
    // that silently falls into the chat branch.
    const chatRoles = ROLES.filter((role) => role !== 'embedding' && role !== 'vision')
    const chatless = provider({ capabilities: ['embeddings'] })
    for (const role of chatRoles) {
      expect(canServe(provider(), role)).toBe(true)
      expect(canServe(chatless, role)).toBe(false)
    }
  })
})

const role = (over: Partial<ResolvedRole>): ResolvedRole => ({
  role: 'research',
  model: 'm',
  layer: 'default',
  scopeId: null,
  settingKey: 'model',
  profile: null,
  dangling: false,
  ...over,
})

describe('roles that move together', () => {
  /** The live case: `research` and `extraction` both resolve from `model`, so
   *  choosing a cheap local model for extraction silently repoints the research
   *  agent. Derived from the response rather than written down, which is what
   *  this pair of tests is really checking. */
  const shared = [
    role({ role: 'research', settingKey: 'model' }),
    role({ role: 'extraction', settingKey: 'model' }),
    role({ role: 'curation', settingKey: 'curation_model' }),
    role({ role: 'embedding', settingKey: 'embedding_model' }),
    role({ role: 'vision', settingKey: 'vision_model' }),
  ]

  it('names the other roles on the same setting', () => {
    expect(sharing(shared, 'research')).toEqual(['extraction'])
    expect(sharing(shared, 'extraction')).toEqual(['research'])
  })

  it('says nothing for a role that has its setting to itself', () => {
    expect(sharing(shared, 'curation')).toEqual([])
  })

  it('reports only groups with more than one member', () => {
    // The banner must not print "curation resolves from the same setting as
    // curation", which is what a naive group-by would produce.
    expect(sharedGroups(shared)).toEqual([['research', 'extraction']])
  })

  it('goes quiet when the backend splits them', () => {
    // The reason this is derived rather than hardcoded: a frontend that wrote
    // `['research', 'extraction']` down would keep warning about a pairing that
    // no longer exists, and the warning would be indistinguishable from a real
    // one.
    const split = shared.map((entry) =>
      entry.role === 'extraction' ? role({ ...entry, settingKey: 'extraction_model' }) : entry,
    )
    expect(sharedGroups(split)).toEqual([])
    expect(sharing(split, 'research')).toEqual([])
  })

  it('answers nothing for a role the response did not carry', () => {
    expect(sharing([], 'research')).toEqual([])
  })
})

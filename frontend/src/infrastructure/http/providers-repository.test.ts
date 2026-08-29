import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@application/ports/errors.ts'

import { HttpClient } from './http-client.ts'
import { HttpProvidersRepository } from './providers-repository.ts'

/** The provider and profile transport, driven through a real `HttpClient`.
 *
 * A stub client would assert that this class called a method; what matters
 * here is what goes on the wire — an omitted `api_key` is a different request
 * from an empty one, and a 404 has to survive as an outcome rather than an
 * exception. Both are decided inside `HttpClient` and the mappers, so both
 * ends run.
 */
const clientOver = (respond: (url: string, init?: RequestInit) => Response) => {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => Promise.resolve(respond(url, init)))
  vi.stubGlobal('fetch', fetchMock)
  return { http: new HttpClient(''), fetchMock }
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('the connection test', () => {
  it('omits a key it was not given rather than sending an empty one', async () => {
    const { http, fetchMock } = clientOver(() =>
      json({ provider_id: 'ollama', outcome: 'ok', ok: true, detail: '', models: [] }),
    )
    const repository = new HttpProvidersRepository(http)

    await repository.test('ollama', { baseUrl: 'http://localhost:11434/v1/' })

    // Not `{api_key: ''}`. The route reads an absent key as "test what you can
    // without one", which is the only way a provider needing no auth gets
    // tested at all -- an empty string is a credential that is wrong.
    expect(JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string)).toEqual({
      base_url: 'http://localhost:11434/v1/',
    })
  })

  it('carries the models back, which is what fills the picker', async () => {
    const { http } = clientOver(() =>
      json({
        provider_id: 'openai',
        outcome: 'ok',
        ok: true,
        detail: '',
        models: ['gpt-4o', 'gpt-4o-mini'],
        latency_ms: 214,
      }),
    )
    const repository = new HttpProvidersRepository(http)

    const result = await repository.test('openai', { apiKey: 'sk-x' })

    // `models` rather than `ok` is the reason the button exists: it is the step
    // that turns an empty picker into a list.
    expect(result.models).toEqual(['gpt-4o', 'gpt-4o-mini'])
    expect(result.latencyMs).toBe(214)
  })

  it('keeps the five outcomes distinct rather than collapsing them to ok/not', async () => {
    for (const outcome of ['unauthorized', 'unreachable', 'unsupported', 'error'] as const) {
      const { http } = clientOver(() =>
        json({ provider_id: 'p', outcome, ok: false, detail: 'why', models: [] }),
      )
      const result = await new HttpProvidersRepository(http).test('p', {})
      // A wrong key and a firewall send a person to different places, so the
      // distinction has to survive the transport, not just the presenter.
      expect(result.outcome).toBe(outcome)
    }
  })
})

describe('profiles and roles', () => {
  it('reads them in one call, because the interesting question is the pair', async () => {
    const { http, fetchMock } = clientOver(() =>
      json({
        scope_chain: [{ scope: 'project', scope_id: 'p1' }],
        profiles: [
          {
            scope: 'project',
            scope_id: 'p1',
            name: 'cheap-local',
            provider_id: 'ollama',
            model: 'qwen',
            credential_key: null,
            base_url: null,
            parameters: { temperature: 0.2 },
          },
        ],
        roles: [
          {
            role: 'extraction',
            model: 'qwen',
            layer: 'project',
            scope_id: 'p1',
            setting_key: 'model',
            profile: 'cheap-local',
            dangling: false,
          },
        ],
      }),
    )
    const repository = new HttpProvidersRepository(http)

    const { profiles, roles } = await repository.profiles([{ scope: 'project', scopeId: 'p1' }])

    expect(fetchMock.mock.calls[0]![0]).toBe('/api/profiles?project=p1')
    // `parameters` is carried whole and uninterpreted -- provider-specific and
    // unenumerable by a catalogue, so nothing here has an opinion about it.
    expect(profiles[0]?.parameters).toEqual({ temperature: 0.2 })
    expect(roles[0]?.settingKey).toBe('model')
  })

  it('surfaces a dangling selection rather than hiding it', async () => {
    const { http } = clientOver(() =>
      json({
        scope_chain: [],
        profiles: [],
        roles: [
          {
            role: 'research',
            model: 'fallback',
            layer: 'default',
            scope_id: null,
            setting_key: 'model',
            profile: 'deleted-profile',
            dangling: true,
          },
        ],
      }),
    )
    const repository = new HttpProvidersRepository(http)

    const { roles } = await repository.profiles([])

    // A role silently repointed at the default model is the exact failure this
    // feature exists to prevent: the person believes they are running a local
    // model and are billing an API. The flag has to reach the component.
    expect(roles[0]?.dangling).toBe(true)
  })

  it('sends parameters explicitly, so a PUT replaces rather than merges', async () => {
    const { http, fetchMock } = clientOver(() =>
      json({
        scope: 'project',
        scope_id: 'p1',
        name: 'n',
        provider_id: 'openai',
        model: 'gpt-4o',
        credential_key: null,
        base_url: null,
        parameters: {},
      }),
    )
    const repository = new HttpProvidersRepository(http)

    await repository.saveProfile('project', 'p1', 'n', { providerId: 'openai', model: 'gpt-4o' })

    const body = JSON.parse((fetchMock.mock.calls[0]![1] as RequestInit).body as string) as {
      parameters: unknown
    }
    // `{}` rather than the field being absent: a PUT is a replacement, and
    // omitting the field would make saving a profile with no parameters leave
    // a previous definition's parameters in place.
    expect(body.parameters).toEqual({})
  })
})

describe('deleting', () => {
  it('reports "there was nothing here" for a 404 rather than failing', async () => {
    const { http } = clientOver(() => json({ detail: 'no such profile' }, 404))
    const repository = new HttpProvidersRepository(http)

    await expect(repository.deleteProfile('project', 'p1', 'gone')).resolves.toBe(false)
    await expect(repository.clearRole('project', 'p1', 'research')).resolves.toBe(false)
  })

  it('still throws on a 422, which is what an unknown role gets', async () => {
    // 404 and 422 both mean "that did nothing" from a distance, and only one of
    // them means the request was wrong. Collapsing both to `false` is the
    // plausible wrong fix.
    const { http } = clientOver(() => json({ detail: "'reserch' is not one of ..." }, 422))
    const repository = new HttpProvidersRepository(http)

    await expect(repository.clearRole('project', 'p1', 'research')).rejects.toBeInstanceOf(ApiError)
  })

  it('reports a real removal as removed', async () => {
    const { http } = clientOver(() => new Response(null, { status: 204 }))
    const repository = new HttpProvidersRepository(http)

    await expect(repository.deleteProfile('project', 'p1', 'old')).resolves.toBe(true)
  })
})

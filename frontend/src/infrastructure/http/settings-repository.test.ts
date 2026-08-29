import { describe, expect, it, vi } from 'vitest'

import { ApiError, ContractError } from '@application/ports/errors.ts'

import { HttpClient } from './http-client.ts'
import { HttpSettingsRepository } from './settings-repository.ts'

/** The adapter's own decisions, which are three: how a chain becomes a query
 *  string, what a `DELETE`'s 404 means, and that a secret's mask survives the
 *  mapper intact.
 *
 * The 404 case is the one that matters most and the one a fake would be
 * useless for, so it is driven through a real `HttpClient` over a stubbed
 * `fetch`: the status has to travel from a `Response` through `ApiError` to a
 * `false`, and every link in that is code this repository wrote. Stubbing the
 * client would assert that `isNotFound` was consulted, which is not the same
 * claim. */
const clientOver = (respond: (url: string, init?: RequestInit) => Response) => {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => Promise.resolve(respond(url, init)))
  vi.stubGlobal('fetch', fetchMock)
  return { http: new HttpClient(''), fetchMock }
}

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })

describe('HttpSettingsRepository', () => {
  it('builds the chain into a query string, and sends none for the fallback read', async () => {
    const { http, fetchMock } = clientOver(() => json({ scope_chain: [], settings: [] }))
    const repository = new HttpSettingsRepository(http)

    await repository.resolved([{ scope: 'project', scopeId: 'p1' }])
    // The second call the page makes: the same route with this scope omitted,
    // which is the *only* correct source for a fallback value. A bare path is
    // a real request -- environment and default alone -- and not a degenerate
    // one, so this asserts there is no stray `?`.
    await repository.resolved([])

    expect(fetchMock.mock.calls.map((call) => call[0])).toEqual([
      '/api/settings/resolved?project=p1',
      '/api/settings/resolved',
    ])
  })

  it('turns a DELETE 404 into "there was nothing to clear" rather than a failure', async () => {
    const { http } = clientOver(() => json({ detail: 'no override for model' }, 404))
    const repository = new HttpSettingsRepository(http)

    // Would reject rather than resolve `false` if the catch were removed, so
    // this is red without the adapter's one behavioural line.
    await expect(repository.clear('project', 'p1', 'model')).resolves.toBe(false)
  })

  it('still throws on a 422, which is the status a misspelled key gets', async () => {
    // The distinction the 404 exists to preserve, from the other side: 404 and
    // 422 both mean "that key did nothing" from a distance, and only one of
    // them means the key was spelled wrong. Collapsing both to `false` is the
    // plausible wrong fix, and this is what fails on it.
    const { http } = clientOver(() => json({ detail: 'unknown setting: modle' }, 422))
    const repository = new HttpSettingsRepository(http)

    await expect(repository.clear('project', 'p1', 'modle')).rejects.toBeInstanceOf(ApiError)
  })

  it('reports a cleared override as cleared', async () => {
    // A 204 with no body at all -- the shape the contract specifies. This is
    // red if `noContentDto` is tightened to `z.null()` in a build where
    // anything puts a body on the response, which is why it is not.
    const { http } = clientOver(() => new Response(null, { status: 204 }))
    const repository = new HttpSettingsRepository(http)

    await expect(repository.clear('project', 'p1', 'model')).resolves.toBe(true)
  })

  it('PUTs one key with the value as a string, whatever the setting type is', async () => {
    const { http, fetchMock } = clientOver(() =>
      json({ scope: 'project', scope_id: 'p1', key: 'extraction_chunk_size', stored: true }),
    )
    const repository = new HttpSettingsRepository(http)

    await repository.put('project', 'p1', 'extraction_chunk_size', '2000')

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/settings/project/p1/extraction_chunk_size')
    expect(init.method).toBe('PUT')
    // `"2000"`, not `2000`. One server-side parser is what keeps the HTTP
    // layer and the environment layer agreeing about what a value means, and a
    // client that helpfully sent a number would be a second parser.
    expect(JSON.parse(init.body as string)).toEqual({ value: '2000' })
  })

  it('carries a secret through as a mask and never as a value', async () => {
    const { http } = clientOver(() =>
      json({
        scope_chain: [{ scope: 'project', scope_id: 'p1' }],
        settings: [
          {
            key: 'api_key',
            value: null,
            layer: 'project',
            scope_id: 'p1',
            secret: true,
            masked: { present: true, last_four: '1234', display: 'set (…1234)' },
          },
          // A non-secret beside it, with no `masked` key at all -- which is
          // what the presenter actually omits rather than nulls. A DTO that
          // required the key would reject every ordinary setting.
          { key: 'model', value: 'my-model', layer: 'project', scope_id: 'p1', secret: false },
        ],
      }),
    )
    const repository = new HttpSettingsRepository(http)

    const resolved = await repository.resolved([{ scope: 'project', scopeId: 'p1' }])

    expect(resolved.settings[0]).toEqual({
      key: 'api_key',
      value: null,
      layer: 'project',
      scopeId: 'p1',
      secret: true,
      masked: { present: true, lastFour: '1234', display: 'set (…1234)' },
    })
    expect(resolved.settings[1]?.masked).toBeNull()
  })

  it('refuses a layer this build does not understand rather than rendering it as text', async () => {
    // The unions in `dto.ts` are closed on purpose. A sixth layer is a backend
    // this console genuinely cannot draw provenance for, and a `ContractError`
    // naming the field beats a chip reading `quantum`.
    const { http } = clientOver(() =>
      json({
        scope_chain: [],
        settings: [{ key: 'model', value: 'x', layer: 'quantum', scope_id: null, secret: false }],
      }),
    )
    const repository = new HttpSettingsRepository(http)

    await expect(repository.resolved([])).rejects.toBeInstanceOf(ContractError)
  })
})

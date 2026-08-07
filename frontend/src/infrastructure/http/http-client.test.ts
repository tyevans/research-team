import { afterEach, describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { ApiError, ContractError } from '@application/ports/errors.ts'

import { HttpClient, query, seg } from './http-client.ts'

const respond = (body: string, init: ResponseInit = {}) =>
  vi.stubGlobal('fetch', vi.fn(async () => new Response(body, { status: 200, ...init })))

const schema = z.object({ id: z.string() })

describe('HttpClient', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('returns a validated body', async () => {
    respond(JSON.stringify({ id: 'abc' }))
    await expect(new HttpClient().get('/api/x', schema)).resolves.toEqual({ id: 'abc' })
  })

  it('raises a ContractError, naming the field, when the shape is wrong', async () => {
    respond(JSON.stringify({ identifier: 'abc' }))
    // The alternative is `undefined` propagating into a row that renders blank,
    // which is the failure this layer exists to convert into a real error.
    const failure = await new HttpClient().get('/api/x', schema).catch((e: unknown) => e)
    expect(failure).toBeInstanceOf(ContractError)
    expect((failure as ContractError).detail).toContain('id')
  })

  it('carries the status, because four call sites branch on it', async () => {
    respond(JSON.stringify({ detail: 'no such file' }), { status: 404 })
    const failure = await new HttpClient().get('/api/x', schema).catch((e: unknown) => e)
    expect(failure).toBeInstanceOf(ApiError)
    expect((failure as ApiError).isNotFound).toBe(true)
    expect((failure as ApiError).message).toBe('no such file')
  })

  it('recognises the statuses the application makes decisions from', () => {
    expect(new ApiError('', 409).isConflict).toBe(true)
    expect(new ApiError('', 499).isCancelled).toBe(true)
    expect(new ApiError('', 500).isNotFound).toBe(false)
  })

  it('falls back through the raw body to the status line for a message', async () => {
    respond('upstream exploded', { status: 502, statusText: 'Bad Gateway' })
    const failure = await new HttpClient().get('/api/x', schema).catch((e: unknown) => e)
    expect((failure as ApiError).message).toBe('upstream exploded')

    respond('', { status: 502, statusText: 'Bad Gateway' })
    const bare = await new HttpClient().get('/api/x', schema).catch((e: unknown) => e)
    expect((bare as ApiError).message).toBe('502 Bad Gateway')
  })

  it('sends a JSON body on POST and none on GET', async () => {
    const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
      Promise.resolve(new Response(JSON.stringify({ id: 'a' }))),
    )
    vi.stubGlobal('fetch', fetchMock)

    await new HttpClient().post('/api/x', { a: 1 }, schema)
    expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ a: 1 }),
    })

    await new HttpClient().get('/api/x', schema)
    expect(fetchMock.mock.calls[1]?.[1]).not.toHaveProperty('body')
  })

  it('accepts an empty body where the route answers nothing', async () => {
    respond('')
    await expect(new HttpClient().post('/api/x', {}, z.unknown())).resolves.toBeNull()
  })
})

describe('url building', () => {
  it('encodes a segment, including a path with a slash or a space', () => {
    expect(seg('/course/a b.md')).toBe('%2Fcourse%2Fa%20b.md')
  })

  it('omits absent parameters rather than sending them empty', () => {
    expect(query({ path: '/a.md', at: null })).toBe('?path=%2Fa.md')
    expect(query({ at: undefined })).toBe('')
    // Zero is a real position, not an absence.
    expect(query({ at: 0 })).toBe('?at=0')
  })
})

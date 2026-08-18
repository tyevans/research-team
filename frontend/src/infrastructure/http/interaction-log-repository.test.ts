import { afterEach, expect, it, vi } from 'vitest'

import { HttpClient } from './http-client.ts'
import { HttpInteractionSink } from './interaction-log-repository.ts'

afterEach(() => vi.unstubAllGlobals())

const event = (seq: number) => ({
  kind: 'ViewEntered',
  browser_session_id: '11111111-1111-1111-1111-111111111111',
  install_id: '22222222-2222-2222-2222-222222222222',
  seq,
  view: 'home',
  occurred_at: '2026-08-17T10:00:00Z',
  payload: {},
})

it('posts a batch as one request', async () => {
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve(new Response(JSON.stringify({ accepted: 2, rejected: 0 }))),
  )
  vi.stubGlobal('fetch', fetchMock)

  await new HttpInteractionSink(new HttpClient()).send([event(1), event(2)])

  expect(fetchMock).toHaveBeenCalledTimes(1)
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit]
  expect(url).toBe('/api/interactions')
  expect(JSON.parse(init.body as string)).toEqual({ events: [event(1), event(2)] })
})

it('sends nothing when there is nothing to send', async () => {
  const fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)

  await new HttpInteractionSink(new HttpClient()).send([])

  expect(fetchMock).not.toHaveBeenCalled()
})

it('beacons a batch on unload', () => {
  /** jsdom does not implement sendBeacon, so this has to be stubbed rather
   *  than merely observed -- there is no stub for it in vitest.setup.ts. */
  const beacon = vi.fn((_url: string, _payload: Blob) => true)
  vi.stubGlobal('navigator', { sendBeacon: beacon })

  new HttpInteractionSink(new HttpClient()).sendOnUnload([event(1)])

  expect(beacon).toHaveBeenCalledTimes(1)
  const [url, payload] = beacon.mock.calls[0] as [string, Blob]
  expect(url).toBe('/api/interactions')
  expect(payload).toBeInstanceOf(Blob)
})

it('falls back to a keepalive fetch where sendBeacon is missing', () => {
  /** Not every browser this console runs in has it, and losing the tail of a
   *  session there would be invisible. */
  const fetchMock = vi.fn((_url: string, _init?: RequestInit) =>
    Promise.resolve(new Response('{}')),
  )
  vi.stubGlobal('navigator', {})
  vi.stubGlobal('fetch', fetchMock)

  new HttpInteractionSink(new HttpClient()).sendOnUnload([event(1)])

  expect(fetchMock).toHaveBeenCalledTimes(1)
  expect(fetchMock.mock.calls[0]?.[1]).toMatchObject({ keepalive: true })
})

it('does not throw when a batch is refused', async () => {
  /** The route is absent when AGENT_INTERACTION_LOG=0, and a console that
   *  broke because telemetry was switched off would be a worse bug than no
   *  telemetry. */
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve(new Response('{"detail":"not collecting"}', { status: 503 }))),
  )

  await expect(new HttpInteractionSink(new HttpClient()).send([event(1)])).resolves.toBeUndefined()
})

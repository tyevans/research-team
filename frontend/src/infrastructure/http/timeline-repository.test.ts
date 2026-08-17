/** The widened timeline read: a window, not just a type.
 *
 * `from` is spelled `from` on the wire and `from_` in the route signature --
 * FastAPI's `Query(alias="from")` is what reconciles them, and a client that
 * sent `from_` would get the whole timeline back with nothing saying the
 * window was ignored. That is what the first assertion is really about.
 */
import { expect, it, vi } from 'vitest'

import { ProjectId } from '@domain/shared/identifier.ts'

import { HttpTimelineRepository } from './timeline-repository.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const clientReturning = (body: unknown) => ({
  get: vi.fn().mockResolvedValue(body),
})

const EMPTY = { bands: [], undated_count: 0, truncated: false }

it('carries every part of the window into the query string', async () => {
  const http = clientReturning(EMPTY)
  const repository = new HttpTimelineRepository(http as never)

  await repository.timeline(PROJECT, {
    entityType: 'Person',
    from: '0300-01-01',
    to: '0400-01-01',
    limit: 50,
  })

  const [url] = http.get.mock.calls[0] as [string]
  expect(url).toContain('entity_type=Person')
  expect(url).toContain('from=0300-01-01')
  expect(url).toContain('to=0400-01-01')
  expect(url).toContain('limit=50')
  expect(url).not.toContain('from_=')
})

it('omits what the caller did not ask for', async () => {
  // `query()` returns the empty string rather than a bare `?` for an empty
  // record (`http-client.ts:156`), so an absent bound is an open end rather
  // than an empty parameter the route would have to interpret.
  const http = clientReturning(EMPTY)
  const repository = new HttpTimelineRepository(http as never)

  await repository.timeline(PROJECT)

  const [url] = http.get.mock.calls[0] as [string]
  expect(url).not.toContain('?')
})

it('carries the counts that say what was left out', async () => {
  const http = clientReturning({ bands: [], undated_count: 412, truncated: true })
  const repository = new HttpTimelineRepository(http as never)

  const timeline = await repository.timeline(PROJECT)

  expect(timeline.undatedCount).toBe(412)
  expect(timeline.truncated).toBe(true)
})

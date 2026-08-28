import { expect, it, vi } from 'vitest'

import { ProjectId, TopicId } from '@domain/shared/identifier.ts'

import { bulkDispatchDto } from './dto.ts'
import type { HttpClient } from './http-client.ts'
import { HttpTopicRepository } from './topic-repository.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')
const FIRST = TopicId('22222222-2222-4222-8222-222222222222')
const SECOND = TopicId('33333333-3333-4333-8333-333333333333')

const frame = (topicId: string) => ({
  type: 'dispatch',
  project_id: String(PROJECT),
  topic_id: topicId,
  dispatch_id: `d-${topicId}`,
  action: 'research',
  status: 'queued',
  question: 'q',
  position: 1,
  path: null,
  session_id: null,
  detail: null,
})

/** The adapter's half of the one seam nothing else in this repository checks.
 *
 * CLAUDE.md's co-mention entry is the cost of skipping this: a port with one
 * production adapter, the port tested against a stub and the adapter against
 * nothing, produced nothing for a whole release and every piece of it passed
 * its own tests. `dispatchBulk` is exactly that shape -- one `Protocol`-ish
 * interface in `application/ports`, one implementation in `infrastructure/`.
 *
 * What this can and cannot do, said plainly rather than implied: it drives the
 * real adapter, so the URL, the body keys and the response mapping are the
 * ones the browser will actually send and read, checked against the route's
 * documented contract (`dispatch_topics` in `app.py`). It cannot drive the
 * real server -- no vitest process here can -- so the *other* half of the
 * co-mention lesson is still owed, and `tests/interfaces/` is where it is
 * paid. What this rules out is the half that was silent last time: a client
 * that posts a shape the route never reads.
 */
it('posts the ids under the key the route reads, at the route that exists', async () => {
  const post = vi.fn().mockResolvedValue({ queued: [frame(String(FIRST))], unknown: [] })
  const repository = new HttpTopicRepository({ post } as unknown as HttpClient)

  await repository.dispatchBulk(PROJECT, 'research', [FIRST, SECOND])

  expect(post).toHaveBeenCalledWith(
    `/api/projects/${PROJECT}/dispatch/bulk`,
    // `topic_ids`, snake, and plain strings: the branded `TopicId` is a
    // TypeScript fiction the wire has never heard of, and `action` beside it
    // rather than nested. **Proved red** by spelling the key `topicIds`,
    // which the route ignores and FastAPI refuses with a 422 naming a field
    // nothing in the browser mentions.
    { action: 'research', topic_ids: [String(FIRST), String(SECOND)] },
    expect.anything(),
  )
})

/** Order survives the round trip, because the route's enqueue order is the
 *  order it is given and the queue's positions are numbered from it.
 *
 * A `Set` or a sort anywhere in this path would leave a person who pressed
 * this on a queue sorted by urgency watching the least urgent topic run first,
 * with nothing wrong on screen. **Proved red** by `[...topicIds].sort()`.
 */
it('sends the ids in the order it was given them', async () => {
  const post = vi.fn().mockResolvedValue({ queued: [], unknown: [] })
  const repository = new HttpTopicRepository({ post } as unknown as HttpClient)

  await repository.dispatchBulk(PROJECT, 'research', [SECOND, FIRST])

  expect(post.mock.calls[0]![1]).toStrictEqual({
    action: 'research',
    topic_ids: [String(SECOND), String(FIRST)],
  })
})

/** `unknown` reaches the caller rather than being dropped in the mapping.
 *
 * The field only exists so a client can say "started 11 of 12"; an adapter
 * that mapped `queued` and forgot `unknown` would typecheck if the field were
 * optional and is the reason it is not. **Proved red** by returning only
 * `{ queued }` from the adapter.
 */
it('carries the ids the project no longer holds back to the caller', async () => {
  const post = vi.fn().mockResolvedValue({
    queued: [frame(String(FIRST))],
    unknown: [String(SECOND)],
  })
  const repository = new HttpTopicRepository({ post } as unknown as HttpClient)

  const result = await repository.dispatchBulk(PROJECT, 'research', [FIRST, SECOND])

  expect(result.queued).toHaveLength(1)
  expect(result.queued[0]!.topicId).toBe(String(FIRST))
  expect(result.unknown).toStrictEqual([String(SECOND)])
})

/** The schema, asserted against the schema rather than through the adapter.
 *
 * This was first written as a fourth adapter test with a `post` stub resolving
 * `{}`, and it failed with `Cannot read properties of undefined` — which is
 * the honest answer: the stub returns its value *instead of* parsing, so
 * nothing in those three tests above exercises `bulkDispatchDto` at all. A
 * defaulting rule can only be checked where the parse happens.
 *
 * It is worth checking, because `BulkResearch` reads `unknown.length` with no
 * guard: a server that omits an empty array from a 202 — which is a shape
 * `dispatchCatchUpDto` beside it already defends against — would otherwise
 * throw inside the success branch of a fan-out that worked.
 *
 * **Proved red** by dropping `.default([])` from either field.
 */
it('defaults both arrays, so a 202 that omits an empty one still parses', () => {
  expect(bulkDispatchDto.parse({})).toStrictEqual({ queued: [], unknown: [] })
})

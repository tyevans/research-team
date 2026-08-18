/** The SSE parser for the dialogue stream.
 *
 * Owning the parser means framing bugs are this file's problem, which is why
 * buffering across reads and tolerating an unknown frame are both tested here:
 * nothing else in the stack would catch either.
 *
 * The frames below are shaped against `_socratic_frame` in
 * `research_team/interfaces/web/app.py`, read rather than recalled. Every key
 * on the wire is snake_case and every field of `DialogueEvent` is camelCase, so
 * the rename lives in the schema in `dialogue-repository.ts` and nowhere else.
 * A mistyped key there fails no type check in either language -- zod fills a
 * default or the frame is dropped -- and the only symptom is an empty question
 * or a composing indicator that never clears. That is why these assertions name
 * both sides of every rename rather than checking a frame merely parsed.
 */
import { expect, it, vi } from 'vitest'

import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { HttpDialogueRepository } from './dialogue-repository.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')

const streaming = (body: string) => {
  const encoder = new TextEncoder()
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader: () => {
        let sent = false
        return {
          read: async () => {
            if (sent) return { done: true, value: undefined }
            sent = true
            return { done: false, value: encoder.encode(body) }
          },
        }
      },
    },
  })
}

const frame = (body: unknown) => `data: ${JSON.stringify(body)}\n\n`

it('parses the dialogue frame the server actually sends', async () => {
  const events: unknown[] = []
  const fetcher = streaming(
    frame({
      type: 'dialogue',
      dialogue_id: 'd1',
      goal: 'understand it',
      stopping_condition: 'the reader explains it unaided',
      pending_blocks: [{ kind: 'markdown', text: 'Where would you start?' }],
    }),
  )

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'hello', (e) => events.push(e))

  expect(events).toEqual([
    {
      type: 'dialogue',
      dialogueId: 'd1',
      goal: 'understand it',
      stoppingCondition: 'the reader explains it unaided',
      pendingBlocks: [{ kind: 'markdown', text: 'Where would you start?' }],
    },
  ])
})

it('parses a prompt frame that has no text key at all', async () => {
  // The server dropped `text` from this frame when the answer key was found
  // shipping beside the projection. A schema requiring it would reject every
  // real frame; a schema defaulting it would invite a page to render the
  // default. Red against `text: z.string()` and against `.default('')`.
  const events: unknown[] = []
  const fetcher = streaming(
    frame({
      type: 'prompt',
      blocks: [{ kind: 'markdown', text: 'Why?' }],
      position: 2,
      citations: [{ kind: 'source', id: 's1' }],
      concluded: false,
    }),
  )

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', (e) => events.push(e))

  expect(events).toEqual([
    {
      type: 'prompt',
      blocks: [{ kind: 'markdown', text: 'Why?' }],
      position: 2,
      citations: [{ kind: 'source', id: 's1' }],
      concluded: false,
    },
  ])
  // The `toEqual` above already pins the shape, but it is the *absence* that
  // is load-bearing and an absence is easy to lose in a rewrite, so it gets its
  // own named assertion. Not `JSON.stringify(...).not.toContain('"text"')`,
  // which the brief proposed and which can never pass: the markdown block
  // legitimately carries `text`, and that string matches it. What must not
  // exist is a `text` key on the EVENT. Red against `text: z.string().default('')`.
  expect(Object.keys(events[0] as object)).not.toContain('text')
})

it('accepts a remark, which the ask stream never sends', async () => {
  const events: { kind?: string }[] = []
  const fetcher = streaming(
    frame({
      type: 'message',
      message_id: '',
      kind: 'remark',
      payload: { text: 'reading the corpus' },
      is_error: false,
    }),
  )

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', (e) =>
    events.push(e as { kind?: string }),
  )

  expect(events[0]?.kind).toBe('remark')
})

it('holds a frame that straddles two reads', async () => {
  // The network decides where a body splits, and a parser assuming one chunk
  // is one frame drops events the first time one straddles the boundary.
  const encoder = new TextEncoder()
  const whole = frame({ type: 'delta', message_id: 'm', text: 'why' })
  const chunks = [whole.slice(0, 12), whole.slice(12)]
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    body: {
      getReader: () => ({
        read: async () => {
          const next = chunks.shift()
          return next === undefined
            ? { done: true, value: undefined }
            : { done: false, value: encoder.encode(next) }
        },
      }),
    },
  })
  const events: unknown[] = []

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', (e) => events.push(e))

  expect(events).toEqual([{ type: 'delta', messageId: 'm', text: 'why' }])
})

it('skips a frame type it does not know rather than throwing', async () => {
  // The server skips a note it cannot render rather than sending an empty
  // one, so an unknown type here means a newer server. Dropping it is the same
  // contract the unknown-fence path keeps: an older reader draws what it can.
  const events: unknown[] = []
  const fetcher = streaming(
    frame({ type: 'something-new', detail: 'x' }) +
      frame({ type: 'error', detail: 'the model is down' }),
  )

  await new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', (e) => events.push(e))

  expect(events).toEqual([{ type: 'error', detail: 'the model is down' }])
})

it('rejects with the status when the stream never opens', async () => {
  // 404 for an unknown or concluded dialogue, 409 for one already running --
  // both raised before streaming, so both are statuses rather than in-band
  // error frames. A caller that only handled `error` events would show a turn
  // that silently stops.
  const fetcher = vi.fn().mockResolvedValue({
    ok: false,
    status: 409,
    text: async () => JSON.stringify({ detail: 'already running' }),
  })

  await expect(
    new HttpDialogueRepository('', fetcher).reply(PROJECT, 'd1', 'x', () => {}),
  ).rejects.toMatchObject({ status: 409 })
})

it('starts a dialogue and returns the server’s id', async () => {
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: async () => JSON.stringify({ dialogueId: 'd1' }),
  })

  const id = await new HttpDialogueRepository('', fetcher).start(PROJECT, 'the creed')

  expect(id).toBe('d1')
  expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
    method: 'POST',
    body: JSON.stringify({ topic: 'the creed' }),
  })
})

it('posts an attempt against the dialogue, not the ask', async () => {
  // The routes differ by one path segment and the wrong one is a 404 at the
  // moment a reader marks an answer -- no other test in this file touches the
  // attempts path. Red against `/asks/` here, and against a camelCase
  // `componentId` in the body, which the server's `SocraticAttempt` refuses.
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ correct: true, correct_options: [1] }), { status: 200 }),
    )

  const verdict = await new HttpDialogueRepository('', fetcher).submitDialogueAttempt(
    PROJECT,
    'd1',
    { position: 2, componentId: ComponentId('q1'), response: 1 },
  )

  const [url, init] = fetcher.mock.calls[0] as [string, RequestInit]
  expect(url).toBe(`/api/projects/${PROJECT}/dialogues/d1/attempts`)
  expect(JSON.parse(init.body as string)).toEqual({
    position: 2,
    component_id: 'q1',
    response: 1,
  })
  expect(verdict.correct).toBe(true)
  expect(verdict.correctOptions).toEqual([1])
})

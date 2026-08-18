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

it('starts a dialogue and returns its framing, not only its id', async () => {
  // Shaped against `_dialogue_view` in `app.py`, which the route now answers.
  // It returned `{"dialogueId"}` alone for three commits while its docstring
  // claimed the goal arrived there, so the page drew "Pick something to work
  // through." over an empty thread until the reader answered a question they
  // could not see.
  //
  // The extra keys are in the fixture on purpose: the real body carries
  // `topic`, `status`, `turnCount` and more, and `framingDto` reads four of
  // them. A schema that rejected the rest would 500 the page on a body the
  // server considers correct.
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: async () =>
      JSON.stringify({
        dialogueId: 'd1',
        projectId: PROJECT,
        topic: 'the creed',
        goal: 'understand what the creed settled',
        stoppingCondition: 'the reader explains it unaided',
        openingBlocks: [{ kind: 'markdown', text: 'Where would you start?' }],
        turnCount: 0,
        status: 'open',
      }),
  })

  const framing = await new HttpDialogueRepository('', fetcher).start(PROJECT, 'the creed')

  expect(framing.dialogueId).toBe('d1')
  expect(framing.goal).toBe('understand what the creed settled')
  expect(framing.stoppingCondition).toBe('the reader explains it unaided')
  expect(framing.openingBlocks).toEqual([{ kind: 'markdown', text: 'Where would you start?' }])
  expect(fetcher.mock.calls[0]?.[1]).toMatchObject({
    method: 'POST',
    body: JSON.stringify({ topic: 'the creed' }),
  })
})

it('refuses a framing missing a key the server always sends', async () => {
  // The three fields are required rather than defaulted, and this is what that
  // buys. `_dialogue_view` always sends `goal`, `stoppingCondition` and
  // `openingBlocks`, so their absence means a server-side rename -- and while
  // they were defaulted, a rename parsed cleanly into `''`, `''` and `[]`,
  // which the page draws as "Pick something to work through." over an empty
  // thread. That is the exact defect returning the framing from `start` was
  // written to remove, restored silently.
  //
  // Asserts the REJECTION rather than a value, because there is no value to
  // assert: the failure being caught is one where every value is plausible.
  // Red against the defaulted schema -- it resolves rather than throwing.
  const fetcher = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    text: async () =>
      JSON.stringify({
        dialogueId: 'd1',
        // `goal` renamed away. The other two are present so the test names one
        // failure rather than three at once.
        stoppingCondition: 'the reader explains it unaided',
        openingBlocks: [],
      }),
  })

  await expect(
    new HttpDialogueRepository('', fetcher).start(PROJECT, 'the creed'),
  ).rejects.toThrow()
})

it('reads back the answers this dialogue remembered', async () => {
  // B114. Two levels of key and both are asserted, because that is the shape
  // the third `progress_view` exists for: a component id is unique only within
  // one utterance, so `turn/0` cannot be dropped from the key. Red against a
  // mapper that flattened this to component ids -- which would find `council-1`
  // and lose which question it belonged to.
  //
  // The snake_case record keys are the server's (`item_view` emits them, unlike
  // `_dialogue_view` beside it); getting those wrong yields a well-formed
  // object of zeroes, which reads as a reader who has answered nothing.
  const fetcher = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        scope: 'dialogue',
        dialogueId: 'd1',
        items: {
          'turn/0': {
            'council-1': {
              attempts: 2,
              correct: true,
              best_score: 1,
              last_score: 1,
              checked: [],
            },
          },
        },
      }),
      { status: 200 },
    ),
  )

  const progress = await new HttpDialogueRepository('', fetcher).progress(PROJECT, 'd1')

  expect(fetcher.mock.calls[0]?.[0]).toBe(`/api/projects/${PROJECT}/dialogues/d1/progress`)
  const item = progress['turn/0']?.get(ComponentId('council-1'))
  expect(item?.correct).toBe(true)
  expect(item?.attempts).toBe(2)
  expect(item?.bestScore).toBe(1)
})

it('rejects rather than reporting an empty history when progress cannot be read', async () => {
  // An untouched dialogue answers `{"items": {}}` with a 200, so a swallowed
  // failure is indistinguishable from "you have answered nothing" -- which on
  // this surface is precisely the claim being made, and the wrong one to make
  // silently. Red against a `catch` returning `{}`.
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response(JSON.stringify({ detail: 'no dialogue' }), { status: 404 }))

  await expect(
    new HttpDialogueRepository('', fetcher).progress(PROJECT, 'd1'),
  ).rejects.toMatchObject({ status: 404 })
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

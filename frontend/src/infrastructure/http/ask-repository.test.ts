/** Parsing an SSE body that arrives in whatever chunks the network chose.
 *
 * The split-frame cases are the reason this is tested rather than trusted: a
 * parser that assumes one chunk is one frame works locally and drops events
 * the moment a body is split across packets.
 */
import { afterEach, expect, it, vi } from 'vitest'

import { ApiError } from '@application/ports/errors.ts'
import type { AskEvent } from '@domain/ask/conversation.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { HttpAskRepository } from './ask-repository.ts'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const body = (...chunks: string[]) => {
  const encoder = new TextEncoder()
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

const respond = (...chunks: string[]) =>
  vi.fn().mockResolvedValue(new Response(body(...chunks), { status: 200 }))

const collect = async (fetcher: typeof fetch) => {
  const seen: AskEvent[] = []
  await new HttpAskRepository('', fetcher).ask(PROJECT, 'c', 'why?', (e) => seen.push(e))
  return seen
}

it('yields one event per frame', async () => {
  const seen = await collect(
    respond(
      'data: {"type":"delta","message_id":"m1","text":"two"}\n\n',
      'data: {"type":"answer","text":"two papers","citations":[]}\n\n',
    ),
  )

  expect(seen).toEqual([
    { type: 'delta', messageId: 'm1', text: 'two' },
    { type: 'answer', text: 'two papers', blocks: [], position: 0, citations: [] },
  ])
})

it('parses the conversation frame naming the server-issued id', async () => {
  // The stream's first frame, and the only source in this codebase of the id
  // an attempt POST has to name -- see `AskState.conversationId`.
  const seen = await collect(
    respond('data: {"type":"conversation","conversation_id":"conv-1"}\n\n'),
  )

  expect(seen).toEqual([{ type: 'conversation', conversationId: 'conv-1' }])
})

it('reassembles a frame split across chunks', async () => {
  const seen = await collect(
    respond('data: {"type":"delta","mess', 'age_id":"m1","text":"two"}\n\n'),
  )

  expect(seen).toEqual([{ type: 'delta', messageId: 'm1', text: 'two' }])
})

it('reads two frames delivered in one chunk', async () => {
  const seen = await collect(
    respond(
      'data: {"type":"delta","message_id":"m1","text":"a"}\n\ndata: {"type":"delta","message_id":"m1","text":"b"}\n\n',
    ),
  )

  expect(seen).toHaveLength(2)
})

it('reads a last frame the server did not terminate', async () => {
  // A body that ends without its trailing blank line -- the final answer would
  // sit unparsed in the buffer forever if the loop only flushed on '\n\n'.
  const seen = await collect(respond('data: {"type":"answer","text":"x","citations":[]}\n'))

  expect(seen).toEqual([{ type: 'answer', text: 'x', blocks: [], position: 0, citations: [] }])
})

it('maps citations off the wire', async () => {
  const seen = await collect(
    respond('data: {"type":"answer","text":"x","citations":[{"kind":"source","id":"s1"}]}\n\n'),
  )

  expect(seen[0]).toEqual({
    type: 'answer',
    text: 'x',
    blocks: [],
    position: 0,
    citations: [{ kind: 'source', id: 's1' }],
  })
})

it('reads blocks and a position off an answer frame', async () => {
  const frame =
    'data: {"type":"answer","text":"try this","position":2,' +
    '"blocks":[{"kind":"component","type":"mcq","id":"q1","data":{},"errors":[],"withheld":["options[].correct"],"gradeable":true}],' +
    '"citations":[]}\n\n'

  const seen = await collect(respond(frame))

  expect(seen[0]).toMatchObject({ type: 'answer', position: 2 })
  expect(seen[0]).toHaveProperty('blocks.0.type', 'mcq')
})

it('defaults blocks and position on a server that sends neither', async () => {
  // Not compatibility -- this build is pre-release. It keeps the parse from
  // rejecting a frame outright during a partial deploy, where the alternative
  // is an answer the reader never sees at all.
  const seen = await collect(respond('data: {"type":"answer","text":"x","citations":[]}\n\n'))

  expect(seen[0]).toMatchObject({ type: 'answer', blocks: [], position: 0 })
})

it('drops a frame whose shape this build does not understand', async () => {
  // A frame from a newer server should cost one event, not the whole stream.
  const seen = await collect(
    respond(
      'data: {"type":"something_new"}\n\n',
      'data: {"type":"answer","text":"x","citations":[]}\n\n',
    ),
  )

  expect(seen).toEqual([{ type: 'answer', text: 'x', blocks: [], position: 0, citations: [] }])
})

it('carries a remark through rather than dropping the frame', async () => {
  // B117: the route flattened every remark into an empty `assistant` frame,
  // so this kind never arrived. A schema that had not learned it would drop
  // the frame in `parseFrame` -- silently, which is what makes this worth an
  // assertion rather than a type. Red against `z.enum(['assistant', 'tool'])`.
  const seen = await collect(
    respond(
      'data: {"type":"message","message_id":"","kind":"remark",' +
        '"payload":{"text":"dropped 3 sources"},"is_error":false}\n\n',
    ),
  )

  expect(seen).toEqual([
    {
      type: 'message',
      messageId: '',
      kind: 'remark',
      payload: { text: 'dropped 3 sources' },
      isError: false,
    },
  ])
})

it('carries an in-band failure through as an event', async () => {
  // After streaming starts the route has no status code left, so the only
  // report of an executor failure is this frame.
  const seen = await collect(respond('data: {"type":"error","detail":"model unreachable"}\n\n'))

  expect(seen).toEqual([{ type: 'error', detail: 'model unreachable' }])
})

it('raises an ApiError carrying the status when the server refuses', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('{"detail":"busy"}', { status: 409 }))

  await expect(
    new HttpAskRepository('', fetcher).ask(PROJECT, 'c', 'why?', () => {}),
  ).rejects.toMatchObject({ status: 409 })
  await expect(
    new HttpAskRepository('', fetcher).ask(PROJECT, 'c', 'why?', () => {}),
  ).rejects.toBeInstanceOf(ApiError)
})

it('posts the chat id and question', async () => {
  const fetcher = respond('data: {"type":"answer","text":"x","citations":[]}\n\n')

  await collect(fetcher)

  const [url, init] = fetcher.mock.calls[0] as [string, RequestInit]
  expect(url).toBe(`/api/projects/${PROJECT}/ask`)
  expect(JSON.parse(init.body as string)).toEqual({ chat_id: 'c', question: 'why?' })
})

it('posts an attempt against a block and parses the verdict', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ correct: true, correct_options: [1] }), { status: 200 }),
    )

  const verdict = await new HttpAskRepository('', fetcher).submitAskAttempt(PROJECT, 'c', {
    position: 2,
    componentId: ComponentId('q1'),
    response: 1,
  })

  const [url, init] = fetcher.mock.calls[0] as [string, RequestInit]
  expect(url).toBe(`/api/projects/${PROJECT}/asks/c/attempts`)
  expect(JSON.parse(init.body as string)).toEqual({
    position: 2,
    component_id: 'q1',
    response: 1,
  })
  expect(verdict.correct).toBe(true)
  expect(verdict.correctOptions).toEqual([1])
})

it('raises an ApiError when the attempt route refuses', async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response('{"detail":"no such block"}', { status: 404 }))

  await expect(
    new HttpAskRepository('', fetcher).submitAskAttempt(PROJECT, 'c', {
      position: 0,
      componentId: ComponentId('q1'),
      response: 1,
    }),
  ).rejects.toMatchObject({ status: 404 })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

/** The receiver matters, and only in a browser.
 *
 * `fetch` is defined on `Window`, and a browser rejects a call whose `this` is
 * anything else -- Firefox with "'fetch' called on an object that does not
 * implement interface Window", Chrome with "Illegal invocation". Holding the
 * global in an instance property and calling `this.fetcher(...)` hands it the
 * repository as its receiver, so every question failed in a real browser while
 * every test above passed: they all inject a `fetcher`, which left the default
 * -- the only branch `container.ts` uses -- unexercised.
 *
 * Node's `fetch` has no such brand check, so jsdom cannot fail this on its own
 * and the stub below supplies the check the browser would apply. Reverting the
 * fix turns these two red.
 */
const brandChecked = () =>
  vi.fn(function (this: unknown) {
    if (this !== undefined && this !== globalThis) {
      throw new TypeError("'fetch' called on an object that does not implement interface Window.")
    }
    return Promise.resolve(new Response('{}', { status: 200 }))
  })

it('asks through the global fetch with a receiver a browser accepts', async () => {
  const global = brandChecked()
  vi.stubGlobal('fetch', global)

  await new HttpAskRepository().ask(PROJECT, 'c', 'why?', () => {})

  expect(global).toHaveBeenCalledOnce()
})

it('forgets through the global fetch with a receiver a browser accepts', async () => {
  const global = brandChecked()
  vi.stubGlobal('fetch', global)

  await new HttpAskRepository().forget(PROJECT, 'c')

  expect(global).toHaveBeenCalledOnce()
})

it('forgets a chat by deleting it, and reports a refusal', async () => {
  const fetcher = vi.fn().mockResolvedValue(new Response('{"ok":true}', { status: 200 }))

  await new HttpAskRepository('', fetcher).forget(PROJECT, 'c 1')

  const [url, init] = fetcher.mock.calls[0] as [string, RequestInit]
  // The chat id is caller-chosen text, so the segment is encoded.
  expect(url).toBe(`/api/projects/${PROJECT}/ask/c%201`)
  expect(init.method).toBe('DELETE')

  const refusing = vi.fn().mockResolvedValue(new Response('', { status: 503 }))
  await expect(new HttpAskRepository('', refusing).forget(PROJECT, 'c')).rejects.toBeInstanceOf(
    ApiError,
  )
})

it('lists a project’s past conversations, camel-cased as the route sends them', async () => {
  // The list route writes `conversationId`/`firstQuestion`, where the SSE
  // frames beside it are snake_case. Mirrored rather than corrected: a schema
  // that accepted both would hide the day one of them changes. Red against
  // `z.object({ conversation_id: ... })`.
  const fetcher = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify([
        {
          conversationId: 'c-1',
          openedAt: '2026-09-01T10:00:00Z',
          firstQuestion: 'why?',
          turnCount: 2,
        },
      ]),
      { status: 200 },
    ),
  )

  const listed = await new HttpAskRepository('', fetcher).conversations(PROJECT)

  expect(listed).toEqual([
    {
      conversationId: 'c-1',
      openedAt: '2026-09-01T10:00:00Z',
      firstQuestion: 'why?',
      turnCount: 2,
    },
  ])
  expect(fetcher).toHaveBeenCalledWith(`/api/projects/${PROJECT}/asks`)
})

it('reads one stored conversation, and drops an answer a server should not send', async () => {
  // **The `answer` key is absent from the schema and that is the assertion.**
  // The route withholds the raw markdown because it carries the key `blocks`
  // was projected to remove -- and the leak it withholds was real (B106). A
  // schema that carried it through would make re-adding it server-side
  // invisible on this side. The fixture sends one anyway, as a server that had
  // regressed would; zod strips it.
  const fetcher = vi.fn().mockResolvedValue(
    new Response(
      JSON.stringify({
        conversationId: 'c-1',
        openedAt: '2026-09-01T10:00:00Z',
        firstQuestion: 'why?',
        turnCount: 1,
        turns: [
          {
            position: 0,
            question: 'why?',
            answer: 'the raw markdown, with `correct: true` in it',
            blocks: [{ kind: 'markdown', text: 'two papers' }],
            citations: [{ kind: 'source', id: 's1' }],
          },
        ],
      }),
      { status: 200 },
    ),
  )

  const conversation = await new HttpAskRepository('', fetcher).conversation(PROJECT, 'c-1')

  expect(conversation.turns[0]).toEqual({
    position: 0,
    question: 'why?',
    blocks: [{ kind: 'markdown', text: 'two papers' }],
    citations: [{ kind: 'source', id: 's1' }],
  })
  expect(JSON.stringify(conversation)).not.toContain('correct: true')
})

it('raises an ApiError when the history routes refuse', async () => {
  // A 503 from the list route means the ask projection is unwired, which the
  // route distinguishes from an empty project on purpose. Swallowing it into
  // `[]` here would throw that distinction away at the last step.
  const fetcher = vi
    .fn()
    .mockResolvedValue(
      new Response(JSON.stringify({ detail: 'ask history is not configured' }), { status: 503 }),
    )

  await expect(new HttpAskRepository('', fetcher).conversations(PROJECT)).rejects.toThrow(ApiError)
})

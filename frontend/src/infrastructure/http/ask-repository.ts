/** The one genuinely new piece of infrastructure on the ask page.
 *
 * `EventSource` cannot issue a POST, and `HttpClient` reads a whole body as
 * text, so neither can carry a streamed answer to a posted question. This
 * reads `response.body` and parses SSE frames itself, validating each through
 * zod as every other wire boundary here does.
 *
 * The cost of owning the parser is that framing bugs are this file's problem:
 * buffering across reads and tolerating an unknown frame type are both tested
 * here because nothing else in the stack would catch them.
 */
import { z } from 'zod'

import { ApiError } from '@application/ports/errors.ts'
import type { AskRepository } from '@application/ports/repositories.ts'
import type { AskEvent } from '@domain/ask/conversation.ts'
import type { ProjectId } from '@domain/shared/identifier.ts'

import { seg } from './http-client.ts'

// Source-only: the tool that would have produced a topic citation created
// topics rather than read them and left this read-only page's tool set, so a
// server cannot send any other kind. See `Citation` in the domain.
const citationDto = z.object({ kind: z.literal('source'), id: z.string() })

const askFrameDto = z.discriminatedUnion('type', [
  z.object({ type: z.literal('delta'), message_id: z.string(), text: z.string() }),
  z.object({
    type: z.literal('message'),
    message_id: z.string(),
    kind: z.enum(['assistant', 'tool']),
    payload: z.unknown(),
    // Absent on the route's fallback frame for note types added later, which
    // are never failures -- defaulting rather than requiring keeps those
    // readable instead of dropping them.
    is_error: z.boolean().default(false),
  }),
  z.object({
    type: z.literal('answer'),
    text: z.string(),
    citations: z.array(citationDto).default([]),
  }),
  z.object({ type: z.literal('error'), detail: z.string() }),
])

const toEvent = (raw: z.output<typeof askFrameDto>): AskEvent => {
  switch (raw.type) {
    case 'delta':
      return { type: 'delta', messageId: raw.message_id, text: raw.text }
    case 'message':
      return {
        type: 'message',
        messageId: raw.message_id,
        kind: raw.kind,
        payload: raw.payload,
        isError: raw.is_error,
      }
    case 'answer':
      return { type: 'answer', text: raw.text, citations: raw.citations }
    case 'error':
      return { type: 'error', detail: raw.detail }
  }
}

export class HttpAskRepository implements AskRepository {
  constructor(
    private readonly baseUrl: string = '',
    // Wrapped rather than passed bare: `fetch` is a method of `Window`, and
    // holding it in a property means `this.fetcher(...)` calls it with the
    // repository as its receiver, which a browser rejects outright. The arrow
    // keeps the global as the receiver while leaving the seam tests inject on.
    private readonly fetcher: typeof fetch = (...args) => fetch(...args),
  ) {}

  async ask(
    projectId: ProjectId,
    chatId: string,
    question: string,
    onEvent: (event: AskEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await this.fetcher(`${this.baseUrl}/api/projects/${seg(projectId)}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ chat_id: chatId, question }),
      // `null` rather than the optional parameter itself: `exactOptionalPropertyTypes`
      // rejects `undefined` here, and `null` is what "no signal" means to fetch.
      signal: signal ?? null,
    })

    if (!response.ok || !response.body) {
      throw new ApiError(await detail(response), response.status)
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    // Held across reads: the network decides where a body is split, and a
    // parser that assumed one chunk is one frame would drop events the first
    // time a frame straddled that boundary.
    let pending = ''
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      pending += decoder.decode(value, { stream: true })
      const frames = pending.split('\n\n')
      pending = frames.pop() ?? ''
      for (const frame of frames) emit(frame, onEvent)
    }
    // A body may end without its trailing blank line, and the last frame is
    // usually the answer -- the one event it would be worst to lose.
    emit(pending, onEvent)
  }

  async forget(projectId: ProjectId, chatId: string): Promise<void> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${seg(projectId)}/ask/${seg(chatId)}`,
      { method: 'DELETE' },
    )
    if (!response.ok) throw new ApiError(await detail(response), response.status)
  }
}

const emit = (frame: string, onEvent: (event: AskEvent) => void): void => {
  const event = parseFrame(frame)
  if (event !== null) onEvent(event)
}

/** `null` for a frame this build does not understand -- one lost event rather
 *  than a dead stream, since a newer server may send types added later. */
const parseFrame = (frame: string): AskEvent | null => {
  const line = frame.split('\n').find((candidate) => candidate.startsWith('data: '))
  if (!line) return null
  try {
    const parsed = askFrameDto.safeParse(JSON.parse(line.slice('data: '.length)))
    return parsed.success ? toEvent(parsed.data) : null
  } catch {
    return null
  }
}

const detail = async (response: Response): Promise<string> => {
  try {
    const body: unknown = JSON.parse(await response.text())
    if (body && typeof body === 'object' && 'detail' in body) return String(body.detail)
  } catch {
    /* fall through to the status text */
  }
  return response.statusText || `request failed with ${String(response.status)}`
}

/** The dialogue's streaming adapter: a sibling of `ask-repository.ts`.
 *
 * Same reason for existing -- `EventSource` cannot POST and `HttpClient` reads
 * a whole body as text -- and deliberately not a reuse of the ask's parser. The
 * two streams share a shape and disagree on every detail that matters: three
 * message kinds rather than two, a last frame typed `prompt` rather than
 * `answer`, and no raw prompt text anywhere. A shared union would have to admit
 * all of that on both surfaces, which is how the ask's handler ends up drawing
 * a dialogue's question in the reader's own column.
 *
 * **The snake_case/camelCase rename lives here and nowhere else.** The server
 * writes `dialogue_id`, `stopping_condition`, `pending_blocks`, `message_id`,
 * `is_error`; `DialogueEvent` is camelCase throughout. A key misspelt in the
 * schema below is invisible from both ends -- Python emits a well-formed frame,
 * TypeScript sees a well-formed object -- and surfaces only as an empty
 * question or a composing indicator that never clears. Every field is therefore
 * required rather than defaulted where the server always sends it, so a missing
 * key is a parse failure (and a dropped frame) rather than an `undefined`
 * flowing on into the fold. `dialogue-repository.test.ts` round-trips a frame
 * shaped against `_socratic_frame` in `research_team/interfaces/web/app.py`.
 */
import { z } from 'zod'

import { ApiError } from '@application/ports/errors.ts'
import type {
  DialogueFraming,
  DialogueProgress,
  DialogueRepository,
} from '@application/ports/repositories.ts'
import type { DialogueEvent } from '@domain/dialogue/conversation.ts'
import type { AttemptResponse, Verdict } from '@domain/lesson/attempt.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import type { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { dialogueProgressDto, verdictDto } from './dto.ts'
import { seg } from './http-client.ts'
import { toDialogueProgress, toVerdict } from './mappers.ts'

// Source-only, as on the ask: the citations a dialogue carries come from the
// same retrieval tools, and no server surface mints another kind.
const citationDto = z.object({ kind: z.literal('source'), id: z.string() })

const dialogueFrameDto = z.discriminatedUnion('type', [
  z.object({
    type: z.literal('dialogue'),
    dialogue_id: z.string(),
    goal: z.string(),
    stopping_condition: z.string(),
    // The question the reader is answering, projected -- on a resumed dialogue
    // this is the newest turn's prompt, key withheld, not an opening one.
    pending_blocks: z.array(z.unknown()).default([]),
  }),
  z.object({
    type: z.literal('delta'),
    message_id: z.string(),
    // **EMPTY on every real frame, always** (`app.py:3167`). The server empties
    // it rather than dropping the frame, because the raw prose streamed the
    // model's `mcq` fence with `correct: true` in it ahead of the withheld
    // projection. The frame survives as a liveness signal and nothing else.
    // Typed rather than dropped so the field on the wire has a name here, but
    // no reader should fold it: Task 1's `applyEvent` sets `composing` from
    // this frame and never reads `text`, and a page that rendered it would draw
    // the answer key the day anything refills the field.
    text: z.string(),
  }),
  z.object({
    type: z.literal('message'),
    message_id: z.string(),
    // Three kinds, not the ask's two. `remark` is Plan 2's way of carrying an
    // `ActivityRemark` -- which has no message id by design -- without a sixth
    // frame type; it arrives with an empty `message_id`. A union copied from
    // the ask's DTO rejects every one of them, and the frame is then dropped
    // silently by `parseFrame`, so the test that fails is `accepts a remark,
    // which the ask stream never sends`.
    kind: z.enum(['assistant', 'tool', 'remark']),
    payload: z.unknown(),
    // Absent on frames for note types added later, which are never failures.
    is_error: z.boolean().default(false),
  }),
  z.object({
    type: z.literal('prompt'),
    // **No `text`, and the absence is load-bearing.** The server dropped it
    // when the answer key was found shipping beside the projection. Requiring
    // it would reject every real frame; defaulting it would invite a page to
    // render the empty default as the dialogue's question, which looks like a
    // model that asked nothing rather than like a bug. `blocks` is the
    // question, or there is no question.
    //
    // `unknown` blocks for `ask-repository`'s reason: the domain's readers
    // narrow an open `data` record at the one boundary that needs it, and
    // re-deriving the component shape in zod would be a second schema to keep
    // in step with the registry.
    blocks: z.array(z.unknown()).default([]),
    position: z.number().int().nonnegative().default(0),
    citations: z.array(citationDto).default([]),
    concluded: z.boolean().default(false),
  }),
  z.object({ type: z.literal('error'), detail: z.string() }),
])

const toEvent = (raw: z.output<typeof dialogueFrameDto>): DialogueEvent => {
  switch (raw.type) {
    case 'dialogue':
      return {
        type: 'dialogue',
        dialogueId: raw.dialogue_id,
        goal: raw.goal,
        stoppingCondition: raw.stopping_condition,
        pendingBlocks: raw.pending_blocks as readonly DocumentBlock[],
      }
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
    case 'prompt':
      return {
        type: 'prompt',
        blocks: raw.blocks as readonly DocumentBlock[],
        position: raw.position,
        citations: raw.citations,
        concluded: raw.concluded,
      }
    case 'error':
      return { type: 'error', detail: raw.detail }
  }
}

export class HttpDialogueRepository implements DialogueRepository {
  constructor(
    private readonly baseUrl: string = '',
    // Wrapped rather than passed bare, for `ask-repository`'s reason: `fetch`
    // is a method of `Window` and a browser rejects a call whose receiver is
    // anything else, so holding the global in a property and calling
    // `this.fetcher(...)` would fail in a browser while every injected test
    // passed.
    private readonly fetcher: typeof fetch = (...args) => fetch(...args),
  ) {}

  async start(projectId: ProjectId, topic: string): Promise<DialogueFraming> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${seg(projectId)}/dialogues`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ topic }),
      },
    )
    if (!response.ok) throw new ApiError(await detail(response), response.status)
    // camelCase throughout, and this route is the server's own spelling -- it
    // answers `_dialogue_view`, where every SSE frame is snake_case. Reading
    // `dialogue_id` here yields `undefined` and a dialogue whose every later
    // request 404s.
    const framed = framingDto.parse(JSON.parse(await response.text()))
    return {
      dialogueId: framed.dialogueId,
      goal: framed.goal,
      stoppingCondition: framed.stoppingCondition,
      openingBlocks: framed.openingBlocks as readonly DocumentBlock[],
    }
  }

  async reply(
    projectId: ProjectId,
    dialogueId: string,
    reply: string,
    onEvent: (event: DialogueEvent) => void,
    signal?: AbortSignal,
  ): Promise<void> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${seg(projectId)}/dialogues/${seg(dialogueId)}/reply`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
        body: JSON.stringify({ reply }),
        // `null` rather than the optional parameter: `exactOptionalPropertyTypes`
        // rejects `undefined` here, and `null` is what "no signal" means to fetch.
        signal: signal ?? null,
      },
    )

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
    // usually the prompt -- the one event it would be worst to lose, since a
    // turn that never sees one stays composing forever.
    emit(pending, onEvent)
  }

  async submitDialogueAttempt(
    projectId: ProjectId,
    dialogueId: string,
    input: { position: number; componentId: ComponentId; response: AttemptResponse },
  ): Promise<Verdict> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${seg(projectId)}/dialogues/${seg(dialogueId)}/attempts`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          position: input.position,
          component_id: input.componentId,
          response: input.response,
        }),
      },
    )
    if (!response.ok) throw new ApiError(await detail(response), response.status)
    // Same verdict shape as the lesson and ask routes, so the same schema and
    // mapper. Unlike the ask's, this attempt is *recorded* server-side, and
    // `progress` below is what reads it back.
    return toVerdict(verdictDto.parse(JSON.parse(await response.text())))
  }

  async progress(projectId: ProjectId, dialogueId: string): Promise<DialogueProgress> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${seg(projectId)}/dialogues/${seg(dialogueId)}/progress`,
    )
    // Not swallowed into an empty map. An untouched dialogue already answers
    // `{"items": {}}` with a 200, so a caught failure would be indistinguishable
    // from "you have answered nothing" -- which on this surface is precisely the
    // claim being made, and the wrong one to make silently.
    if (!response.ok) throw new ApiError(await detail(response), response.status)
    return toDialogueProgress(dialogueProgressDto.parse(JSON.parse(await response.text())))
  }

  async end(projectId: ProjectId, dialogueId: string): Promise<void> {
    const response = await this.fetcher(
      `${this.baseUrl}/api/projects/${seg(projectId)}/dialogues/${seg(dialogueId)}/end`,
      { method: 'POST' },
    )
    // No body parsed. The route answers `{"status": "concluded"}` and reading it
    // would change nothing -- a caller that got a 200 already knows what it says.
    if (!response.ok) throw new ApiError(await detail(response), response.status)
  }
}

/** The framing route's body. `_dialogue_view` carries more than these four
 *  fields -- `topic`, `status`, `turnCount` and the rest -- and none of them are
 *  read here: a schema that demanded them would reject a body the server
 *  trimmed, and one that carried them would put a second copy of the dialogue
 *  list's shape in this file. zod ignores unknown keys, which is what makes
 *  taking four of them honest rather than lossy. */
/** Every field required, defaults nowhere -- this file's opening rule, which
 *  this schema used to be the one exception to.
 *
 * `_dialogue_view` (`app.py:3700`) always sends all four, so a missing `goal`,
 * `stoppingCondition` or `openingBlocks` is a server-side rename and nothing
 * else. Defaulted, that rename yielded `''`, `''` and `[]` -- exactly the
 * empty framing over an empty thread that returning the framing from `start`
 * existed to remove, and with no failure anywhere: the parse succeeded, the
 * store set three empty strings, and the page drew "Pick something to work
 * through." over a dialogue that had a goal.
 *
 * The test that fails without this is `refuses a framing missing a key the
 * server always sends`; it passes with the defaults restored only because it
 * asserts the rejection, which is the point. */
const framingDto = z.object({
  dialogueId: z.string(),
  goal: z.string(),
  stoppingCondition: z.string(),
  openingBlocks: z.array(z.unknown()),
})

const emit = (frame: string, onEvent: (event: DialogueEvent) => void): void => {
  const event = parseFrame(frame)
  if (event !== null) onEvent(event)
}

/** `null` for a frame this build does not understand -- one lost event rather
 *  than a dead stream. The server already skips a note it cannot render, so an
 *  unknown type here means a newer server, and an older reader drawing what it
 *  can is the same contract the unknown-fence path keeps.
 *
 *  The cost is stated plainly because it is real: this also swallows a frame
 *  the schema *should* have matched and did not -- a renamed key, say -- with
 *  no signal at all. That is what the round-trip tests are for. */
const parseFrame = (frame: string): DialogueEvent | null => {
  const line = frame.split('\n').find((candidate) => candidate.startsWith('data: '))
  if (!line) return null
  try {
    const parsed = dialogueFrameDto.safeParse(JSON.parse(line.slice('data: '.length)))
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

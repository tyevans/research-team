/** Turns, transcripts and component blocks for the ask surface -- and, for
 *  `componentBlock` alone, for the lesson widgets too.
 *
 * Here rather than inline for the reason `course/course-fixtures.ts` exists: a
 * transcript written out in five stories is five transcripts, and they drift
 * one story at a time until no two of them show the same component.
 *
 * `componentBlock` has outgrown the file's name and is left here anyway. It is
 * imported from `presentation/lesson` by every resolved widget's tests, and
 * moving it would touch each of those in a slice that is about none of them --
 * the shape it builds is `ComponentBlock`, which is a `domain/lesson` type, so
 * `domain/lesson` is where it belongs the day someone is already in those
 * files. Filed rather than done, deliberately.
 */
import type { AskActivity, AskTranscript, AskTurn } from '@domain/ask/conversation.ts'
import type { ComponentBlock } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

/** Fixed rather than generated: a story whose links change every render is a
 *  story whose screenshot can never be compared with yesterday's. */
export const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

/** `payload` is shaped the way the server really sends it -- langchain's
 *  `message_to_dict`, `{type, data}` -- not the flat `{name}` this fixture
 *  used to invent. The flat shape is what let `activityName`'s top-level
 *  lookup pass its test while reading `item.kind` in production; see
 *  `AskActivity.test.tsx`. */
export const activity = (over: Partial<AskActivity> = {}): AskActivity => ({
  messageId: 'm1',
  kind: 'tool',
  payload: { type: 'tool', data: { name: 'read_source' } },
  isError: false,
  ...over,
})

/** An assistant frame that dispatched one call, shaped as langchain sends it.
 *
 * `id` is not decoration: it is what a result frame's `tool_call_id` points
 * at, and a fixture without one would make every pairing test pass by
 * accident on the "no id, no join" path. */
export const assistantCall = ({
  name,
  args = {},
  id,
  messageId = `call:${id}`,
}: {
  name: string
  args?: Record<string, unknown>
  id: string
  messageId?: string
}): AskActivity => ({
  messageId,
  kind: 'assistant',
  payload: { type: 'ai', data: { tool_calls: [{ name, args, id }] } },
  isError: false,
})

/** The result frame that answers one call. */
export const toolResult = ({
  name,
  callId,
  content,
  isError = false,
  messageId = `result:${callId}`,
}: {
  name: string
  callId: string
  content: string
  isError?: boolean
  messageId?: string
}): AskActivity => ({
  messageId,
  kind: 'tool',
  payload: { type: 'tool', data: { name, content, tool_call_id: callId } },
  isError,
})

/** One `component:` block, as the server's answer frame carries it.
 *
 * Here at the second copy rather than the fifth, which is the point of this
 * file: six resolved widgets each want this exact shape, and an inline
 * literal per test is six places to get `unknown` or `errors` wrong -- either
 * one silently routes the block to a code block or an error panel instead of
 * the widget, which reads as "the renderer is not wired up".
 *
 * `resolved` defaults to `true` because every caller so far is a resolved
 * type. It drives nothing: `LessonDocument` deliberately does not read it (see
 * its `RENDERERS`), and it is carried only so the fixture matches the frame
 * the server really sends. `raw` defaults to the fence a reader would see if
 * the block fell through to the `unknown` path, so that failure shows
 * something recognisable rather than an empty `<pre>`.
 */
export const componentBlock = ({
  type,
  id = 'block-1',
  data = {},
  raw = `\`\`\`component:${type}\nid: ${id}\n\`\`\``,
  ...over
}: {
  type: string
  id?: string
  data?: Record<string, unknown>
  raw?: string
} & Partial<Omit<ComponentBlock, 'kind' | 'type' | 'id' | 'data' | 'raw'>>): ComponentBlock => ({
  kind: 'component',
  id: ComponentId(id),
  type,
  data,
  raw,
  lang: `component:${type}`,
  unknown: false,
  errors: [],
  withheld: [],
  resolved: true,
  ...over,
})

export const turn = (over: Partial<AskTurn> = {}): AskTurn => ({
  question: 'What did the two 2019 papers actually disagree about?',
  answer:
    'They agree on the effect and disagree on its size. Both find spaced review beats massed\nreview at two weeks; the second reports roughly half the advantage, and attributes the gap\nto its untimed final test.',
  blocks: [],
  position: 0,
  activity: [],
  citations: [{ kind: 'source', id: 's1' }],
  error: null,
  settled: true,
  ...over,
})

/** A transcript long enough to overflow any viewport a story picks. The
 *  questions differ so a reader can tell one turn from the next -- twelve
 *  identical turns would hide exactly the run-together this redesign is
 *  about. */
export const transcript = (count: number): AskTranscript =>
  Array.from({ length: count }, (_unused, index) =>
    turn({ question: `Question number ${String(index + 1)}: what follows from that?` }),
  )

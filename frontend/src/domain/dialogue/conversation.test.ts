/** The dialogue transcript, as a fold over the stream.
 *
 * Pure on purpose, for the reason `ask/conversation.ts` gives: streaming order
 * is the part that goes subtly wrong and is far cheaper to get right here than
 * through a rendered component.
 *
 * Two traps have their own tests because both produce something that still
 * looks like a conversation: the speakers running the wrong way, and the
 * question text coming from deltas rather than from the projection.
 */
import { expect, it } from 'vitest'

import type { DocumentBlock } from '@domain/lesson/document.ts'
import { ComponentId } from '@domain/shared/identifier.ts'

import { answered, applyEvent, composing } from './conversation.ts'
import type { DialogueTranscript } from './conversation.ts'

const BLOCKS: readonly DocumentBlock[] = [{ kind: 'markdown', text: 'Why do you say that?' }]

/** A component the projection has already stripped. Every field of
 *  `ComponentBlock` is present because the fold is typed against the real
 *  block rather than a sketch of one, and `data` has no `correct` precisely
 *  because it was withheld server-side. */
const KEYED: readonly DocumentBlock[] = [
  { kind: 'markdown', text: 'Try this:' },
  {
    kind: 'component',
    id: ComponentId('q1'),
    type: 'mcq',
    data: { options: [{ text: 'Nicaea' }] },
    raw: 'id: q1',
    lang: 'yaml',
    unknown: false,
    errors: [],
    withheld: ['correct'],
    resolved: false,
  },
]

const opened = (): DialogueTranscript => answered([], 'It settled Arianism.')

it('opens a turn on the reader’s answer, not on the dialogue’s question', () => {
  // `answered`, not `asked`. On this surface the reader's move is what opens a
  // turn: the dialogue has already asked, and its question is either the
  // opening one on the row or the previous turn's. Red against a fold copied
  // from the ask, where the turn opens on the question.
  const transcript = opened()

  expect(transcript).toHaveLength(1)
  expect(transcript[0]?.reply).toBe('It settled Arianism.')
  expect(transcript[0]?.blocks).toEqual([])
  expect(transcript[0]?.settled).toBe(false)
})

it('settles a turn from the prompt frame’s blocks', () => {
  const transcript = applyEvent(opened(), {
    type: 'prompt',
    blocks: BLOCKS,
    position: 3,
    citations: [{ kind: 'source', id: 's1' }],
    concluded: false,
  })

  expect(transcript[0]?.blocks).toEqual(BLOCKS)
  expect(transcript[0]?.position).toBe(3)
  expect(transcript[0]?.citations).toEqual([{ kind: 'source', id: 's1' }])
  expect(transcript[0]?.settled).toBe(true)
})

it('never puts delta text into the question, however much of it arrives', () => {
  // **The leak this fold exists to not have.** `delta` frames carried the
  // model's prose verbatim as it was produced -- including the raw fenced YAML
  // of a component, `correct: true` and all -- until `_socratic_frame` emptied
  // them. They are empty at the server today, and the fold must not depend on
  // that: `text` is still on the frame, so a fold that accumulated it would
  // render the answer key on screen the moment anything refilled it.
  //
  // Red against `blocks: [...turn.blocks, {kind: 'markdown', text: event.text}]`
  // or any other accumulation -- measured, not reasoned, in step 5 of this
  // task: the raw fence lands in the transcript and the assertion below finds
  // the key.
  const streamed = applyEvent(opened(), {
    type: 'delta',
    messageId: 'm1',
    text: '```component:mcq\nid: q1\noptions:\n  - text: "Nicaea"\n    correct: true\n```',
  })

  expect(streamed[0]?.blocks).toEqual([])
  expect(JSON.stringify(streamed)).not.toContain('correct')
})

it('reports that the dialogue is composing while deltas arrive, and stops when it settles', () => {
  // What the deltas are actually for. The reader gets a liveness signal and
  // never the text. Red against a fold that drops deltas entirely -- the page
  // then shows nothing at all between the reader's answer and the question,
  // which on a slow model reads as a hung page.
  const streaming = applyEvent(opened(), { type: 'delta', messageId: 'm1', text: 'Why' })
  expect(composing(streaming)).toBe(true)

  const settled = applyEvent(streaming, {
    type: 'prompt',
    blocks: BLOCKS,
    position: 0,
    citations: [],
    concluded: false,
  })
  expect(composing(settled)).toBe(false)
})

it('keeps activity, including a remark, in arrival order', () => {
  // `remark` is a third `kind` the ask never sees: Plan 2 carries an
  // `ActivityRemark` as a message with an empty `message_id` so a page can
  // style it apart from a model utterance without a sixth frame type. Red
  // against a fold whose `kind` union is copied from `AskActivity`.
  const transcript = applyEvent(
    applyEvent(opened(), {
      type: 'message',
      messageId: 'm1',
      kind: 'tool',
      payload: { name: 'read_source' },
      isError: false,
    }),
    {
      type: 'message',
      messageId: '',
      kind: 'remark',
      payload: { text: 'thinking' },
      isError: false,
    },
  )

  expect(transcript[0]?.activity.map((a) => a.kind)).toEqual(['tool', 'remark'])
})

it('settles a turn on an error and closes it to later frames', () => {
  const failed = applyEvent(opened(), { type: 'error', detail: 'the model is down' })
  expect(failed[0]?.error).toBe('the model is down')
  expect(failed[0]?.settled).toBe(true)

  // A settled turn is closed: a late frame belongs to nothing, and writing it
  // in would overwrite something the reader has already read.
  const late = applyEvent(failed, {
    type: 'prompt',
    blocks: BLOCKS,
    position: 0,
    citations: [],
    concluded: false,
  })
  expect(late[0]?.blocks).toEqual([])
})

it('carries the concluded flag off the prompt frame', () => {
  // Rendered from today and always false until Plan 4, which is the slice that
  // makes anything write `SocraticDialogueConcluded`. Constructed directly
  // here for that reason -- no live path produces it.
  const transcript = applyEvent(opened(), {
    type: 'prompt',
    blocks: BLOCKS,
    position: 0,
    citations: [],
    concluded: true,
  })

  expect(transcript[0]?.concluded).toBe(true)
})

it('ignores the dialogue frame, which is the store’s business and not a turn’s', () => {
  const transcript = applyEvent(opened(), {
    type: 'dialogue',
    dialogueId: 'd1',
    goal: 'g',
    stoppingCondition: 's',
    pendingBlocks: BLOCKS,
  })

  expect(transcript).toEqual(opened())
})

it('drops any event that arrives before the reader has answered anything', () => {
  expect(applyEvent([], { type: 'delta', messageId: 'm', text: 'hi' })).toEqual([])
})

it('does not let a withheld component’s key into the transcript', () => {
  // The projection has already withheld it server-side; this asserts the fold
  // carries blocks through without reconstructing anything.
  //
  // The assertion is `"correct":` -- the key with its colon -- rather than a
  // bare `"correct"`, which the withheld list itself contains
  // (`"withheld":["correct"]`) and which would therefore fail against a
  // perfectly correct fold. What must never appear is the key carrying a
  // value.
  const transcript = applyEvent(opened(), {
    type: 'prompt',
    blocks: KEYED,
    position: 0,
    citations: [],
    concluded: false,
  })

  expect(transcript[0]?.blocks).toEqual(KEYED)
  expect(JSON.stringify(transcript)).not.toContain('"correct":')
})

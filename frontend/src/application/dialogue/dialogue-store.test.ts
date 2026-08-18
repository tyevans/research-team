/** The dialogue store: what it refuses, and what it keeps.
 *
 * The ask's store mints a `chatId` in the browser and can send immediately.
 * This one cannot: the dialogue id is the server's, so every guard here is
 * about not sending before there is a dialogue to send to.
 */
import { expect, it, vi } from 'vitest'

import type { DialogueRepository } from '@application/ports/repositories.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { createDialogueStore } from './dialogue-store.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')
const BLOCKS: readonly DocumentBlock[] = [{ kind: 'markdown', text: 'Where would you start?' }]

const repo = (over: Partial<DialogueRepository> = {}): DialogueRepository => ({
  start: vi.fn<DialogueRepository['start']>().mockResolvedValue('d1'),
  reply: vi.fn<DialogueRepository['reply']>().mockResolvedValue(undefined),
  submitDialogueAttempt: vi.fn(),
  ...over,
})

const store = (dialogues: DialogueRepository) =>
  createDialogueStore({ dialogues, projectId: PROJECT })

it('keeps the framing on the store rather than in the transcript', async () => {
  // The design's §5: a dialogue whose goal the reader cannot see is a quiz
  // pretending to be a conversation. The framing arrives on the stream's first
  // frame and lives on the store, not in the transcript -- it is not a turn,
  // and a transcript that held it would draw it as something to answer.
  const dialogues = repo({
    reply: vi.fn<DialogueRepository['reply']>(async (_p, _d, _r, onEvent) => {
      onEvent({
        type: 'dialogue',
        dialogueId: 'd1',
        goal: 'understand the creed',
        stoppingCondition: 'the reader explains it unaided',
        pendingBlocks: BLOCKS,
      })
      onEvent({
        type: 'prompt',
        blocks: BLOCKS,
        position: 1,
        citations: [],
        concluded: false,
      })
    }),
  })
  const dialogue = store(dialogues)

  await dialogue.getState().start('the creed')
  await dialogue.getState().send('It settled Arianism.')

  expect(dialogue.getState().goal).toBe('understand the creed')
  expect(dialogue.getState().stoppingCondition).toBe('the reader explains it unaided')
  expect(dialogue.getState().pendingBlocks).toEqual(BLOCKS)
  // One turn, the reader's -- not three. Red against a store that folded the
  // framing frame in as a turn of its own.
  expect(dialogue.getState().transcript).toHaveLength(1)
  expect(dialogue.getState().transcript[0]!.reply).toBe('It settled Arianism.')
})

it('refuses to send before a dialogue has been started', async () => {
  // Red against a store that posts anyway: the route would 404 on a null id
  // rendered into the URL, and the reader would see a failure that reads as
  // the server's rather than as "you have not started yet".
  const reply = vi.fn<DialogueRepository['reply']>().mockResolvedValue(undefined)
  const dialogue = store(repo({ reply }))

  await dialogue.getState().send('hello?')

  expect(reply).not.toHaveBeenCalled()
})

it('refuses a second reply while one is running', async () => {
  // The server answers 409; not sending is the same answer without the round
  // trip. Red against a store with no `replying` guard.
  let release = (): void => {}
  const reply = vi.fn<DialogueRepository['reply']>(
    () => new Promise<void>((resolve) => (release = resolve)),
  )
  const dialogue = store(repo({ reply }))
  await dialogue.getState().start('t')

  const first = dialogue.getState().send('one')
  await dialogue.getState().send('two')
  release()
  await first

  expect(reply).toHaveBeenCalledTimes(1)
})

it('settles the open turn when the request fails before streaming', async () => {
  // A 404 or 409 arrives as a rejection rather than an in-band error frame, so
  // this is the only place that path closes the turn. Without it the turn
  // spins forever with no question and no reason, which reads as a hung model
  // rather than a failed request.
  const dialogues = repo({
    reply: vi.fn<DialogueRepository['reply']>().mockRejectedValue(new Error('already running')),
  })
  const dialogue = store(dialogues)
  await dialogue.getState().start('t')

  await dialogue.getState().send('one')

  const transcript = dialogue.getState().transcript
  expect(transcript[0]?.settled).toBe(true)
  expect(transcript[0]?.error).toContain('already running')
  expect(dialogue.getState().replying).toBe(false)
})

it('settles a turn whose stream ended without a question or an error', async () => {
  // The dropped-connection case, and the one neither the fold nor the
  // repository can close: `composing` is set by a `delta` frame and cleared
  // only by `prompt` or `error`, and a body that simply stops produces
  // neither while `reply` resolves normally. The fold is pure and cannot see
  // a stream end, so the store is the only place this can be settled.
  //
  // Red against a store that just clears `replying` in `finally`: the turn
  // stays unsettled with `composing` true, which draws a composing indicator
  // that never turns off -- indistinguishable on screen from a model still
  // thinking, and it never resolves.
  const dialogues = repo({
    reply: vi.fn<DialogueRepository['reply']>(async (_p, _d, _r, onEvent) => {
      onEvent({ type: 'delta', messageId: 'm1', text: '' })
    }),
  })
  const dialogue = store(dialogues)
  await dialogue.getState().start('t')

  await dialogue.getState().send('one')

  const turn = dialogue.getState().transcript[0]!
  expect(turn.settled).toBe(true)
  expect(turn.composing).toBe(false)
  expect(turn.error).not.toBeNull()
})

it('leaves a turn its stream completed alone', async () => {
  // The other half of the rule above: a stream that ended with a `prompt`
  // keeps its question rather than being overwritten with an error.
  //
  // **This test also passes with the store's `settled` check removed**, and
  // says so rather than posing as a guard: `applyEvent` ignores every event on
  // a settled turn, so an unconditional settle is absorbed by the fold. It
  // pins the composition -- store settle plus fold -- not the store's check,
  // and it would go red if the fold ever stopped closing settled turns.
  const dialogues = repo({
    reply: vi.fn<DialogueRepository['reply']>(async (_p, _d, _r, onEvent) => {
      onEvent({ type: 'prompt', blocks: BLOCKS, position: 1, citations: [], concluded: false })
    }),
  })
  const dialogue = store(dialogues)
  await dialogue.getState().start('t')

  await dialogue.getState().send('one')

  const turn = dialogue.getState().transcript[0]!
  expect(turn.error).toBeNull()
  expect(turn.blocks).toEqual(BLOCKS)
})

it('does not start a second dialogue while one is being framed', async () => {
  // Framing calls a model and takes seconds. A double-click would otherwise
  // mint two dialogues and strand the first, which is a stream nobody can
  // reach again.
  let release = (): void => {}
  const start = vi.fn<DialogueRepository['start']>(
    () => new Promise<string>((resolve) => (release = () => resolve('d1'))),
  )
  const dialogue = store(repo({ start }))

  const first = dialogue.getState().start('t')
  await dialogue.getState().start('t')
  release()
  await first

  expect(start).toHaveBeenCalledTimes(1)
})

it('surfaces a framing failure as an error rather than an empty dialogue', async () => {
  // The route answers 502 when the model botched the framing. A store that
  // swallowed it would leave the page on an empty dialogue with a composer
  // that 404s on every send.
  const dialogues = repo({
    start: vi
      .fn<DialogueRepository['start']>()
      .mockRejectedValue(new Error('the dialogue could not be framed')),
  })
  const dialogue = store(dialogues)

  await dialogue.getState().start('t')

  expect(dialogue.getState().dialogueId).toBeNull()
  expect(dialogue.getState().error).toContain('could not be framed')
  expect(dialogue.getState().starting).toBe(false)
})

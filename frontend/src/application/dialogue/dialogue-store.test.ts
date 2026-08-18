/** The dialogue store: what it refuses, and what it keeps.
 *
 * The ask's store mints a `chatId` in the browser and can send immediately.
 * This one cannot: the dialogue id is the server's, so every guard here is
 * about not sending before there is a dialogue to send to.
 */
import { expect, it, vi } from 'vitest'

import type { DialogueRepository } from '@application/ports/repositories.ts'
import type { DocumentBlock } from '@domain/lesson/document.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { createDialogueStore } from './dialogue-store.ts'

const PROJECT = ProjectId('11111111-1111-4111-8111-111111111111')
const BLOCKS: readonly DocumentBlock[] = [{ kind: 'markdown', text: 'Where would you start?' }]

/** The framing `POST /dialogues` answers. The goal and the opening question
 *  are on it because the route returns them: for three commits it answered an
 *  id alone while claiming otherwise, and the page drew an empty framing over
 *  an empty thread. */
const FRAMING = {
  dialogueId: 'd1',
  goal: 'understand the creed',
  stoppingCondition: 'the reader explains it unaided',
  openingBlocks: BLOCKS,
}

const repo = (over: Partial<DialogueRepository> = {}): DialogueRepository => ({
  start: vi.fn<DialogueRepository['start']>().mockResolvedValue(FRAMING),
  reply: vi.fn<DialogueRepository['reply']>().mockResolvedValue(undefined),
  submitDialogueAttempt: vi.fn(),
  progress: vi.fn<DialogueRepository['progress']>().mockResolvedValue({}),
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
  expect(dialogue.getState().openingBlocks).toEqual(BLOCKS)
  // One turn, the reader's -- not three. Red against a store that folded the
  // framing frame in as a turn of its own.
  expect(dialogue.getState().transcript).toHaveLength(1)
  expect(dialogue.getState().transcript[0]!.reply).toBe('It settled Arianism.')
})

it('keeps the OPENING question rather than the newest frame\u2019s', async () => {
  // The frame's `pending_blocks` is "the question being answered, not the one
  // about to be asked" (`app.py:3117`), so on the second exchange it is the
  // FIRST turn's question -- already drawn under the reader's first answer.
  // A store that overwrote would walk the opening question forward and show a
  // duplicate of a one-exchange-stale question at the top of the thread.
  //
  // Red against the store as it shipped in a78c44f, which set `pendingBlocks`
  // on every frame: this asserts the SECOND frame's blocks are not kept.
  const later: readonly DocumentBlock[] = [{ kind: 'markdown', text: 'And then what?' }]
  let blocks = BLOCKS
  const dialogues = repo({
    reply: vi.fn<DialogueRepository['reply']>(async (_p, _d, _r, onEvent) => {
      onEvent({
        type: 'dialogue',
        dialogueId: 'd1',
        goal: 'understand the creed',
        stoppingCondition: 'the reader explains it unaided',
        pendingBlocks: blocks,
      })
      blocks = later
    }),
  })
  const dialogue = store(dialogues)

  await dialogue.getState().start('the creed')
  await dialogue.getState().send('It settled Arianism.')
  await dialogue.getState().send('Because the bishops agreed.')

  expect(dialogue.getState().openingBlocks).toEqual(BLOCKS)
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
    () => new Promise((resolve) => (release = () => resolve(FRAMING))),
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

it('draws the framing the moment the dialogue is framed', async () => {
  // The largest hole this task closes. `POST /dialogues` answered
  // `{"dialogueId"}` alone while its docstring claimed the goal arrived there,
  // so a freshly framed dialogue showed "Pick something to work through." over
  // an empty thread until the reader answered a question they could not see.
  //
  // Asserted on all three fields rather than on `dialogueId`, which was
  // already set before this change and is therefore the one assertion that
  // could not fail. Red against a `start` that folds in the id alone.
  const dialogue = store(repo())

  await dialogue.getState().start('the Nicene settlement')

  expect(dialogue.getState().dialogueId).toBe('d1')
  expect(dialogue.getState().goal).toBe('understand the creed')
  expect(dialogue.getState().stoppingCondition).toBe('the reader explains it unaided')
  expect(dialogue.getState().openingBlocks).toEqual(BLOCKS)
})

it('reads back the answers the server remembered', async () => {
  // B114, and the whole argument for this surface being its own principal: an
  // ask discards an attempt, a dialogue records one. Until this route existed
  // the recording was real in the log and invisible in the browser.
  //
  // Asserted on the stored verdict reaching the state, never on the call
  // having been made: an empty map is the right answer for a dialogue nobody
  // has answered anything in, so a call-count assertion passes against a
  // repository reading the wrong id entirely.
  const marked = new Map([
    [
      ComponentId('council-1'),
      { attempts: 2, correct: true, bestScore: 1, lastScore: 1, checked: [] },
    ],
  ])
  // Held in a local rather than read back off the repository object:
  // `@typescript-eslint/unbound-method` refuses `dialogues.progress` as a bare
  // reference.
  const progress = vi.fn<DialogueRepository['progress']>().mockResolvedValue({ 'turn/0': marked })
  const dialogue = store(repo({ progress }))
  await dialogue.getState().start('t')

  await dialogue.getState().refreshProgress()

  expect(dialogue.getState().progress['turn/0']?.get(ComponentId('council-1'))?.correct).toBe(true)
  expect(progress).toHaveBeenCalledWith(PROJECT, 'd1')
})

it('does not ask for progress before there is a dialogue to ask about', async () => {
  // `dialogueId` is null until `start` returns, and a null rendered into the
  // path 404s -- which the page would then have to explain to a reader who has
  // done nothing wrong. `DialogueView` runs this effect on mount, so this is
  // the ordinary case rather than a corner.
  const progress = vi.fn<DialogueRepository['progress']>().mockResolvedValue({})
  const dialogue = store(repo({ progress }))

  await dialogue.getState().refreshProgress()

  expect(progress).not.toHaveBeenCalled()
})

it('leaves the page alone when the progress load fails', async () => {
  // Deliberately silent, and the cost is stated in the store: this request is
  // not the reader's action, and routing its failure into the page's error
  // banner would blame their last answer for a call they did not make. What a
  // failure looks like instead is a dialogue that forgot -- which is the bug
  // this route exists to fix, and nothing catches it.
  const dialogues = repo({
    progress: vi.fn<DialogueRepository['progress']>().mockRejectedValue(new Error('gone')),
  })
  const dialogue = store(dialogues)
  await dialogue.getState().start('t')

  await dialogue.getState().refreshProgress()

  expect(dialogue.getState().error).toBeNull()
  expect(dialogue.getState().progress).toEqual({})
})

it('says so quietly when the answers could not be loaded', async () => {
  // The other half of the silence above. Staying out of `error` is right --
  // this is not the reader's action -- but staying out of the page entirely
  // made a failed load indistinguishable from a dialogue that forgot, which is
  // the defect this route exists to fix. So there is exactly one flag, drawn as
  // one line beside the thread.
  //
  // Red against the store before the flag existed: `progressUnavailable` is
  // not a field, and `undefined` is not `true`.
  const dialogue = store(
    repo({
      progress: vi.fn<DialogueRepository['progress']>().mockRejectedValue(new Error('gone')),
    }),
  )
  await dialogue.getState().start('t')

  await dialogue.getState().refreshProgress()

  expect(dialogue.getState().progressUnavailable).toBe(true)
})

it('stops saying it once the answers load', async () => {
  // A transient failure must not stick: the flag is cleared on the next
  // success, not only set on failure. Written because the one-line version of
  // this fix -- `catch { set({ progressUnavailable: true }) }` alone -- passes
  // the test above and leaves the line on screen for the rest of the session.
  const progress = vi
    .fn<DialogueRepository['progress']>()
    .mockRejectedValueOnce(new Error('gone'))
    .mockResolvedValue({})
  const dialogue = store(repo({ progress }))
  await dialogue.getState().start('t')
  await dialogue.getState().refreshProgress()

  await dialogue.getState().refreshProgress()

  expect(dialogue.getState().progressUnavailable).toBe(false)
})

it('resumes the dialogue the URL named, rather than starting at none', async () => {
  // The seed, at the store's own level. `DialogueView` passes the id off the
  // route; without it the store began every mount at `null`, `refreshProgress`
  // returned on its guard, and no dialogue with any history in it was
  // reachable in a browser at all.
  const progress = vi.fn<DialogueRepository['progress']>().mockResolvedValue({})
  const dialogue = createDialogueStore({
    dialogues: repo({ progress }),
    projectId: PROJECT,
    dialogueId: 'd9',
  })

  await dialogue.getState().refreshProgress()

  expect(dialogue.getState().dialogueId).toBe('d9')
  expect(progress).toHaveBeenCalledWith(PROJECT, 'd9')
})

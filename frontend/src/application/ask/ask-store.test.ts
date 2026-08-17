/** What the ask store guarantees on top of the fold and the repository. */
import { expect, it, vi } from 'vitest'

import type { AskRepository } from '@application/ports/repositories.ts'
import { ProjectId } from '@domain/shared/identifier.ts'

import { createAskStore } from './ask-store.ts'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const fakeAsk = (over: Partial<AskRepository> = {}): AskRepository => ({
  ask: vi.fn<AskRepository['ask']>(async (_p, _c, _q, onEvent) => {
    onEvent({ type: 'answer', text: 'two papers', blocks: [], position: 0, citations: [] })
  }),
  forget: vi.fn().mockResolvedValue(undefined),
  submitAskAttempt: vi.fn(),
  ...over,
})

let counter = 0
const store = (ask: AskRepository = fakeAsk()) =>
  createAskStore({ ask, projectId: PROJECT, newChatId: () => `chat-${String(++counter)}` })

it('records the question before the first frame arrives', async () => {
  const ask = fakeAsk({
    ask: vi.fn(async () => {
      await Promise.resolve()
    }),
  })
  const asking = store(ask)

  const sending = asking.getState().send('what did we find?')

  expect(asking.getState().transcript[0]!.question).toBe('what did we find?')
  await sending
})

it('folds streamed events into the transcript', async () => {
  const asking = store()

  await asking.getState().send('what did we find?')

  expect(asking.getState().transcript[0]!.answer).toBe('two papers')
  expect(asking.getState().transcript[0]!.settled).toBe(true)
})

it('clears the asking flag once the answer settles', async () => {
  const asking = store()

  await asking.getState().send('why?')

  expect(asking.getState().asking).toBe(false)
})

it('surfaces a refusal rather than retrying it', async () => {
  const conflict = Object.assign(new Error('busy'), { status: 409 })
  const asking = store(fakeAsk({ ask: vi.fn().mockRejectedValue(conflict) }))

  await asking.getState().send('why?')

  expect(asking.getState().error).toBe('busy')
  expect(asking.getState().asking).toBe(false)
})

it('marks the open turn failed when the stream breaks', async () => {
  const asking = store(fakeAsk({ ask: vi.fn().mockRejectedValue(new Error('network gone')) }))

  await asking.getState().send('why?')

  // Without this the turn spins forever with no answer and no reason.
  expect(asking.getState().transcript[0]!.settled).toBe(true)
  expect(asking.getState().transcript[0]!.error).toBe('network gone')
})

it('refuses a second question while one is running', async () => {
  const ask = vi.fn(async () => {
    await new Promise((resolve) => setTimeout(resolve, 5))
  })
  const asking = store(fakeAsk({ ask }))

  const first = asking.getState().send('one')
  await asking.getState().send('two')
  await first

  expect(ask).toHaveBeenCalledTimes(1)
  expect(asking.getState().transcript).toHaveLength(1)
})

it('sends the same chat id for every question in a conversation', async () => {
  const ask = vi.fn<AskRepository['ask']>(async (_p, _c, _q, onEvent) => {
    onEvent({ type: 'answer', text: 'x', blocks: [], position: 0, citations: [] })
  })
  const asking = store(fakeAsk({ ask }))

  await asking.getState().send('one')
  await asking.getState().send('two')

  expect(ask.mock.calls[0]![1]).toBe(ask.mock.calls[1]![1])
})

it('records the server-issued conversation id, distinct from the chat id it asked with', async () => {
  // Never the same string: `chatId` is minted here and only ever used to ask
  // the server to open a conversation, never a value the server stores
  // anything under. Conflating the two is exactly the bug this field exists
  // to prevent -- see `AskState.conversationId`.
  const ask = vi.fn<AskRepository['ask']>(async (_p, _c, _q, onEvent) => {
    onEvent({ type: 'conversation', conversationId: 'server-id' })
    onEvent({ type: 'answer', text: 'x', blocks: [], position: 0, citations: [] })
  })
  const asking = store(fakeAsk({ ask }))

  expect(asking.getState().conversationId).toBeNull()
  await asking.getState().send('one')

  expect(asking.getState().conversationId).toBe('server-id')
  expect(asking.getState().conversationId).not.toBe(asking.getState().chatId)
})

it('reset forgets the server copy and starts a new chat id', async () => {
  const forget = vi.fn().mockResolvedValue(undefined)
  const asking = store(fakeAsk({ forget }))
  await asking.getState().send('one')
  const before = asking.getState().chatId

  await asking.getState().reset()

  expect(forget).toHaveBeenCalledWith(PROJECT, before)
  expect(asking.getState().transcript).toEqual([])
  expect(asking.getState().chatId).not.toBe(before)
})

it('clears the transcript even when forgetting the server copy fails', async () => {
  const asking = store(fakeAsk({ forget: vi.fn().mockRejectedValue(new Error('offline')) }))
  await asking.getState().send('one')

  await asking.getState().reset()

  // The server's copy expires on its own; refusing to clear the page would
  // strand the reader in a conversation they asked to leave.
  expect(asking.getState().transcript).toEqual([])
})

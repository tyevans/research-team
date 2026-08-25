/** The ask page, from a reader's point of view. */
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { ReactNode } from 'react'
import { expect, it, vi } from 'vitest'

import type { Container as AppContainer } from '@app/container.ts'
import { ContainerProvider } from '@app/container-context.tsx'
import type { AskRepository } from '@application/ports/repositories.ts'
import type { AskEvent } from '@domain/ask/conversation.ts'
import { ComponentId, ProjectId } from '@domain/shared/identifier.ts'

import { AskView } from './AskView.tsx'

const PROJECT = ProjectId('11111111-1111-1111-1111-111111111111')

const renderAsk = (ask: Partial<AskRepository>) => {
  const container = { ask: { forget: vi.fn(), ...ask } } as unknown as AppContainer
  const wrapper = ({ children }: { children: ReactNode }) => (
    <ContainerProvider container={container}>{children}</ContainerProvider>
  )
  return render(<AskView projectId={PROJECT} />, { wrapper })
}

/** `Citation.kind` is `'source'` alone -- the tool that would have produced a
 *  topic citation created topics rather than read them and was dropped from
 *  this read-only page, so nothing can emit one. */
const answering = (text: string, citations: { kind: 'source'; id: string }[] = []) =>
  vi.fn(
    async (
      _p: ProjectId,
      _c: string,
      _q: string,
      onEvent: (event: AskEvent) => void,
    ): Promise<void> => {
      onEvent({ type: 'answer', text, blocks: [], position: 0, citations })
    },
  )

const ask = async (question: string) => {
  await userEvent.type(screen.getByRole('textbox'), question)
  await userEvent.click(screen.getByRole('button', { name: /^ask$/i }))
}

it('shows the question and its answer', async () => {
  renderAsk({ ask: answering('two papers') })

  await ask('what did we find?')

  expect(await screen.findByText('what did we find?')).toBeInTheDocument()
  expect(await screen.findByText('two papers')).toBeInTheDocument()
})

it('links a source citation to the project document it came from', async () => {
  renderAsk({ ask: answering('two papers', [{ kind: 'source', id: 's1' }]) })

  await ask('why?')

  const link = await screen.findByRole('link', { name: /s1/ })
  expect(link).toHaveAttribute('href', `#/p/${PROJECT}/doc/s1`)
})

/** `expandReferences` only runs when `Markdown` is given a `projectId`, and
 *  every other test in this file supplies the answer text as plain prose --
 *  none of them can tell a caller that forgot to pass `projectId` through
 *  from one that remembered. `content.test.tsx` has the same blind spot for
 *  the reverse reason: it calls `Markdown` directly and hands the prop to
 *  itself. This test renders through the real `AskTurn`, the way a reader
 *  reaches it, so it fails if `AskTurn.tsx` stops threading `projectId` to
 *  `Markdown` -- proved red against a build with that prop removed before
 *  this was written. */
it('turns a model-written source reference into a link', async () => {
  renderAsk({ ask: answering('see [[src:s1]] for the source') })

  await ask('why?')

  // The accessible name is `Source 1: s1`, not `s1`: the reference renders as
  // a superscript number and the id lives on the `aria-label` (see
  // `references.ts`). Matching on the id rather than on the whole name keeps
  // this test about the thing it exists to catch -- `AskTurn` dropping
  // `projectId` -- rather than about the marker's wording.
  const link = await screen.findByRole('link', { name: /s1/ })
  expect(link).toHaveAttribute('href', `#/p/${PROJECT}/doc/s1`)
  expect(link).toHaveTextContent('1')
})

it('says the page keeps nothing', () => {
  // The contract is ephemerality; a reader who does not know that will expect
  // to find this conversation again tomorrow.
  //
  // Scoped to the subtitle rather than left as a page-wide text search. The
  // page says this in more than one place by design -- the head states it and
  // the empty thread repeats it, which is the two moments a reader could form
  // the wrong expectation -- and an unscoped `getByText` throws on the second
  // match. Narrowing the query keeps the claim and drops the accident.
  renderAsk({ ask: answering('x') })

  expect(screen.getByText(/not saved/i, { selector: '.ask-sub' })).toBeInTheDocument()
})

it('surfaces a refusal to the reader', async () => {
  renderAsk({ ask: vi.fn().mockRejectedValue(new Error('busy')) })

  await ask('why?')

  // Twice, and both are asserted because both are load-bearing: the banner is
  // what a reader who has scrolled away sees, and the turn's own copy is what
  // says *which question* failed. A page-wide `findByText(/busy/)` would throw
  // on the pair rather than checking either.
  expect(await screen.findByRole('alert')).toHaveTextContent(/busy/)
  // `article p` rather than a class: the turn's copy is a paragraph inside the
  // turn and the banner is a `div` outside every turn, which is the same
  // distinction the old `.ask-error` selector drew and is now the only one on
  // offer -- the page's styles are utilities, so there is no name to select.
  expect(screen.getByText(/busy/, { selector: 'article p' })).toBeInTheDocument()
})

it('clears the thread on a new chat', async () => {
  renderAsk({ ask: answering('two papers') })
  await ask('why?')
  expect(await screen.findByText('two papers')).toBeInTheDocument()

  await userEvent.click(screen.getByRole('button', { name: /new chat/i }))

  expect(screen.queryByText('two papers')).not.toBeInTheDocument()
})

it('keeps tool activity out of the way until asked for', async () => {
  const spy = vi.fn(
    async (
      _p: ProjectId,
      _c: string,
      _q: string,
      onEvent: (event: AskEvent) => void,
    ): Promise<void> => {
      onEvent({
        type: 'message',
        messageId: 'm1',
        kind: 'tool',
        payload: { type: 'tool', data: { name: 'read_source' } },
        isError: false,
      })
      onEvent({ type: 'answer', text: 'two papers', blocks: [], position: 0, citations: [] })
    },
  )
  renderAsk({ ask: spy })

  await ask('why?')

  // Collapsed, not absent: the reader wants the answer, and the trace second.
  // Sound in jsdom only because collapsed means *not rendered* -- `Disclosure`
  // renders `{open ? children : null}`. Were it hidden by a stylesheet this
  // assertion would pass against a page that showed the trace, and the claim
  // would belong in the browser suite instead.
  const disclosure = await screen.findByRole('button', { name: /looked at|activity/i })
  expect(disclosure).toBeInTheDocument()
  expect(screen.queryByText(/read_source/)).not.toBeInTheDocument()

  await userEvent.click(disclosure)
  expect(screen.getByText(/read_source/)).toBeInTheDocument()
})

/** The seam eight per-task reviews missed: the id an attempt POST names has
 *  to be the one the *server* opened the conversation under, not the browser's
 *  own `chatId`. Every other test in this file and in `AskTurn.test.tsx` uses
 *  its own literal id on each side of that seam ("c1" here, "c" there), so
 *  each half stays internally consistent and nothing crosses from the stream
 *  to the POST. This stubs a repository that emits a `conversation` frame
 *  naming one id and a widget-bearing answer, then asserts the attempt goes
 *  out under that id -- proved red against the build that aliased `chatId` as
 *  `conversationId` in `AskView.tsx`, where this asserted the store's own
 *  minted uuid instead and passed for the wrong reason. */
it('submits a widget attempt against the server-issued conversation id, not the browser chat id', async () => {
  const submitAskAttempt = vi.fn().mockResolvedValue({
    correct: true,
    score: 1,
    feedback: [],
    rationale: null,
    correctOptions: [0],
    blanks: [],
    progress: null,
  })
  const spy = vi.fn(
    async (
      _p: ProjectId,
      _c: string,
      _q: string,
      onEvent: (event: AskEvent) => void,
    ): Promise<void> => {
      onEvent({ type: 'conversation', conversationId: 'server-issued-id' })
      onEvent({
        type: 'answer',
        text: 'pick one',
        blocks: [
          {
            kind: 'component',
            id: ComponentId('q1'),
            type: 'mcq',
            data: { prompt: 'Which?', options: [{ text: 'A' }, { text: 'B' }], multiple: false },
            raw: '```component:mcq\n```',
            lang: 'component:mcq',
            unknown: false,
            errors: [],
            withheld: ['answer'],
            resolved: false,
          },
        ],
        position: 0,
        citations: [],
      })
    },
  )
  renderAsk({ ask: spy, submitAskAttempt })

  await ask('which papers agree?')

  await userEvent.click(screen.getByRole('radio', { name: 'A' }))
  await userEvent.click(screen.getByRole('button', { name: /check answer/i }))

  expect(submitAskAttempt).toHaveBeenCalledWith(
    PROJECT,
    'server-issued-id',
    expect.objectContaining({ position: 0 }),
  )
})

it('refuses to send while a question is in flight', async () => {
  // The store already refuses; this pins that the composer says so rather than
  // looking available and silently dropping the second question.
  const spy = vi.fn(async (): Promise<void> => new Promise(() => {}))
  renderAsk({ ask: spy })

  await ask('why?')

  expect(screen.getByRole('button', { name: /^ask$/i })).toBeDisabled()
  expect(screen.getByRole('textbox')).toBeDisabled()
})
